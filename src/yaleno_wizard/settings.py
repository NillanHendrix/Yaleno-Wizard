"""Lokale Einstellungen (Verbindungsprofil). Passphrasen werden nie gespeichert."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_config_dir, user_log_dir

from . import APP_ID


def config_dir() -> Path:
    return Path(user_config_dir(APP_ID, appauthor=False))


def log_dir() -> Path:
    return Path(user_log_dir(APP_ID, appauthor=False))


def known_hosts_file() -> Path:
    return config_dir() / "known_hosts"


def default_staging_dir(snapshot: str) -> Path:
    return Path.home() / "Yaleno-Wiederherstellung" / snapshot


@dataclass
class Profile:
    storage_type: str = "sftp"  # "sftp" | "local"
    local_dir: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    key_path: str = ""
    base_path: str = "."
    backup_name: str = ""

    @classmethod
    def load(cls) -> "Profile":
        f = config_dir() / "profile.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        d = config_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "profile.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
