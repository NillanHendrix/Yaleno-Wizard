"""SFTP-Speicher über paramiko mit SSH-Key-Authentifizierung.

Host-Keys werden nach dem Trust-on-first-use-Prinzip in einer eigenen
known_hosts-Datei abgelegt; zusätzlich wird ~/.ssh/known_hosts (nur lesend) geprüft.
"""

from __future__ import annotations

import base64
import hashlib
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable

import paramiko

from .base import Storage, StorageError


class HostKeyRejected(StorageError):
    pass


class HostKeyMismatch(StorageError):
    pass


class KeyPassphraseRequired(StorageError):
    pass


@dataclass
class ConnectionSettings:
    host: str
    port: int = 22
    username: str = ""
    key_path: str = ""
    base_path: str = "."


# (host_label, key_type, sha256_fingerprint) -> bool
HostKeyConfirm = Callable[[str, str, str], bool]


def fingerprint_sha256(key: paramiko.PKey) -> str:
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


def load_private_key(path: str, passphrase: str | None = None) -> paramiko.PKey:
    p = Path(path).expanduser()
    if not p.is_file():
        raise StorageError(f"SSH-Key nicht gefunden: {p}")
    pw = passphrase.encode("utf-8") if passphrase else None
    try:
        return paramiko.PKey.from_path(p, pw)  # type: ignore[arg-type]
    except paramiko.PasswordRequiredException as exc:
        raise KeyPassphraseRequired("Der SSH-Key ist mit einer Passphrase geschützt.") from exc
    except TypeError as exc:
        # cryptography: "password was not provided" / "not given but private key is encrypted"
        if pw is None:
            raise KeyPassphraseRequired("Der SSH-Key ist mit einer Passphrase geschützt.") from exc
        raise StorageError(f"SSH-Key konnte nicht geladen werden: {exc}") from exc
    except (ValueError, paramiko.SSHException) as exc:
        if passphrase:
            raise StorageError(f"SSH-Key konnte nicht geladen werden (Passphrase falsch?): {exc}") from exc
        raise StorageError(f"SSH-Key konnte nicht geladen werden: {exc}") from exc


class SFTPStorage(Storage):
    def __init__(self, transport: paramiko.Transport, sftp: paramiko.SFTPClient, label: str):
        self._transport = transport
        self._sftp = sftp
        self._label = label

    # ---------------------------------------------------------------- connect
    @classmethod
    def connect(
        cls,
        settings: ConnectionSettings,
        known_hosts_file: Path,
        confirm_host_key: HostKeyConfirm,
        passphrase: str | None = None,
        timeout: float = 15.0,
    ) -> "SFTPStorage":
        pkey = load_private_key(settings.key_path, passphrase)
        host_label = settings.host if settings.port == 22 else f"[{settings.host}]:{settings.port}"

        try:
            sock = socket.create_connection((settings.host, settings.port), timeout=timeout)
        except OSError as exc:
            raise StorageError(f"Verbindung zu {settings.host}:{settings.port} fehlgeschlagen: {exc}") from exc

        transport = paramiko.Transport(sock)
        try:
            transport.start_client(timeout=timeout)
            server_key = transport.get_remote_server_key()
            cls._verify_host_key(host_label, server_key, known_hosts_file, confirm_host_key)
            try:
                transport.auth_publickey(settings.username, pkey)
            except paramiko.AuthenticationException as exc:
                raise StorageError(
                    f"Anmeldung als '{settings.username}' mit dem SSH-Key wurde abgelehnt. "
                    "Ist der öffentliche Schlüssel in ~/.ssh/authorized_keys des Servers hinterlegt?"
                ) from exc
            transport.set_keepalive(30)
            sftp = paramiko.SFTPClient.from_transport(transport)
            if sftp is None:
                raise StorageError("SFTP-Subsystem nicht verfügbar.")
        except StorageError:
            transport.close()
            raise
        except (paramiko.SSHException, OSError, EOFError) as exc:
            transport.close()
            raise StorageError(f"SSH-Fehler: {exc}") from exc
        except BaseException:
            transport.close()
            raise

        return cls(transport, sftp, f"sftp://{settings.username}@{settings.host}:{settings.port}")

    @staticmethod
    def _verify_host_key(
        host_label: str, key: paramiko.PKey, known_hosts_file: Path, confirm: HostKeyConfirm
    ) -> None:
        own = paramiko.HostKeys()
        if known_hosts_file.exists():
            own.load(str(known_hosts_file))
        system = paramiko.HostKeys()
        sys_file = Path.home() / ".ssh" / "known_hosts"
        if sys_file.exists():
            try:
                system.load(str(sys_file))
            except Exception:
                pass

        for store in (own, system):
            entry = store.lookup(host_label)
            if entry is None:
                continue
            known = entry.get(key.get_name())
            if known is None:
                continue
            if known.asbytes() == key.asbytes():
                return
            raise HostKeyMismatch(
                f"WARNUNG: Der Host-Key von {host_label} hat sich geändert!\n"
                f"Neu: {fingerprint_sha256(key)}\n"
                "Das kann auf einen Angriff hindeuten. Verbindung abgebrochen."
            )

        if not confirm(host_label, key.get_name(), fingerprint_sha256(key)):
            raise HostKeyRejected("Host-Key wurde nicht bestätigt.")
        own.add(host_label, key.get_name(), key)
        known_hosts_file.parent.mkdir(parents=True, exist_ok=True)
        own.save(str(known_hosts_file))

    # ---------------------------------------------------------------- storage
    def listdir(self, path: str) -> list[str]:
        return sorted(self._sftp.listdir(path or "."))

    def _stat(self, path: str):
        try:
            return self._sftp.stat(path)
        except FileNotFoundError:
            return None
        except IOError as exc:
            if getattr(exc, "errno", None) == 2:
                return None
            raise

    def exists(self, path: str) -> bool:
        return self._stat(path) is not None

    def is_dir(self, path: str) -> bool:
        st = self._stat(path)
        return st is not None and stat.S_ISDIR(st.st_mode or 0)

    def mkdir(self, path: str) -> None:
        self._sftp.mkdir(path, mode=0o700)

    def open_read(self, path: str) -> BinaryIO:
        fh = self._sftp.open(path, "rb")
        fh.prefetch()
        return fh  # type: ignore[return-value]

    def open_write(self, path: str) -> BinaryIO:
        fh = self._sftp.open(path, "wb")
        fh.set_pipelined(True)
        return fh  # type: ignore[return-value]

    def create_exclusive(self, path: str, data: bytes) -> None:
        try:
            fh = self._sftp.open(path, "wxb")
        except IOError as exc:
            # SFTP meldet bei O_EXCL nur "Failure" – daher nachsehen, ob die Datei existiert.
            if self.exists(path):
                raise FileExistsError(path) from exc
            raise
        with fh:
            fh.write(data)

    def rename(self, src: str, dst: str) -> None:
        try:
            self._sftp.posix_rename(src, dst)
        except IOError:
            # Server ohne posix-rename@openssh.com
            if self.exists(dst):
                self._sftp.remove(dst)
            self._sftp.rename(src, dst)

    def remove(self, path: str) -> None:
        self._sftp.remove(path)

    def rmdir(self, path: str) -> None:
        self._sftp.rmdir(path)

    def chmod(self, path: str, mode: int) -> None:
        try:
            self._sftp.chmod(path, mode)
        except IOError:
            pass

    def close(self) -> None:
        try:
            self._sftp.close()
        finally:
            self._transport.close()

    @property
    def description(self) -> str:
        return self._label
