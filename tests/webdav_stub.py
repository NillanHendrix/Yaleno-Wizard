"""Echter WebDAV-Testserver (WsgiDAV + cheroot) mit Basic-Auth, wie bei Nextcloud."""

from __future__ import annotations

import logging
import socket
import threading
from pathlib import Path

from cheroot import wsgi
from wsgidav.wsgidav_app import WsgiDAVApp

USER, PASSWORD = "tester", "app-passwort"


class DavServer:
    def __init__(self, root: Path):
        config = {
            "provider_mapping": {"/dav": str(root)},
            "simple_dc": {"user_mapping": {"*": {USER: {"password": PASSWORD}}}},
            "http_authenticator": {"accept_basic": True, "accept_digest": False, "default_to_digest": False},
            "verbose": 0,
            "logging": {"enable": False},
            "lock_storage": True,
        }
        logging.getLogger("wsgidav").setLevel(logging.ERROR)
        app = WsgiDAVApp(config)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = wsgi.Server(("127.0.0.1", self.port), app)
        self.server.prepare()
        self.thread = threading.Thread(target=self.server.serve, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/dav"

    def close(self) -> None:
        self.server.stop()
