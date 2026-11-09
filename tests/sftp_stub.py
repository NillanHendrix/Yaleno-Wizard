"""Minimaler SFTP-Testserver (nach dem Vorbild der paramiko-Demos)."""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

import paramiko
from paramiko import SFTPAttributes, SFTPHandle, SFTPServer, SFTPServerInterface
from paramiko.sftp import SFTP_OK


class _Handle(SFTPHandle):
    def stat(self):
        try:
            return SFTPAttributes.from_stat(os.fstat(self.readfile.fileno()))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)


class _SFTP(SFTPServerInterface):
    ROOT = "/"

    def _p(self, path):
        return self.ROOT + self.canonicalize(path)

    def list_folder(self, path):
        path = self._p(path)
        try:
            out = []
            for name in os.listdir(path):
                a = SFTPAttributes.from_stat(os.stat(os.path.join(path, name)))
                a.filename = name
                out.append(a)
            return out
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return SFTPAttributes.from_stat(os.stat(self._p(path)))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)

    lstat = stat

    def open(self, path, flags, attr):
        path = self._p(path)
        try:
            fd = os.open(path, flags, getattr(attr, "st_mode", None) or 0o666)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        if flags & os.O_WRONLY:
            mode = "ab" if flags & os.O_APPEND else "wb"
        elif flags & os.O_RDWR:
            mode = "a+b" if flags & os.O_APPEND else "r+b"
        else:
            mode = "rb"
        f = os.fdopen(fd, mode)
        h = _Handle(flags)
        h.filename = path
        h.readfile = f
        h.writefile = f
        return h

    def remove(self, path):
        try:
            os.remove(self._p(path))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def rename(self, old, new):
        try:
            os.rename(self._p(old), self._p(new))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def posix_rename(self, old, new):
        try:
            os.replace(self._p(old), self._p(new))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def mkdir(self, path, attr):
        try:
            os.mkdir(self._p(path))
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK

    def chattr(self, path, attr):
        try:
            if attr.st_mode is not None:
                os.chmod(self._p(path), attr.st_mode)
        except OSError as e:
            return SFTPServer.convert_errno(e.errno)
        return SFTP_OK


class _Server(paramiko.ServerInterface):
    def __init__(self, allowed: paramiko.PKey, user: str):
        self.allowed = allowed
        self.user = user

    def check_auth_publickey(self, username, key):
        if username == self.user and key.asbytes() == self.allowed.asbytes():
            return paramiko.AUTH_SUCCESSFUL
        return paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "publickey"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED


class StubServer:
    def __init__(self, root: Path, client_key: paramiko.PKey, user: str = "tester"):
        self.root = root
        self.host_key = paramiko.Ed25519Key.generate() if hasattr(paramiko.Ed25519Key, "generate") \
            else paramiko.RSAKey.generate(2048)
        self.client_key = client_key
        self.user = user
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self._stop = False
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        root = str(self.root)

        class Bound(_SFTP):
            ROOT = root

        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            t = paramiko.Transport(conn)
            t.add_server_key(self.host_key)
            t.set_subsystem_handler("sftp", SFTPServer, Bound)
            try:
                t.start_server(server=_Server(self.client_key, self.user))
            except Exception:
                continue

    def close(self):
        self._stop = True
        self.sock.close()
