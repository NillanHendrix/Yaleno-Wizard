"""Einstellungen in einer YAML-Datei: Verbindung, Anmeldung, Abgleich, Hintergrund.

Standardort: ``~/.config/yaleno-wizard/yaleno.yml`` (Windows: ``%APPDATA%\\yaleno-wizard``).
Ein anderer Ort lässt sich mit ``--config DATEI`` oder der Umgebungsvariable ``YALENO_CONFIG``
wählen. Die Datei kann von Hand bearbeitet und auf andere Geräte kopiert werden, Beispiel::

    storage:
      type: webdav                 # webdav (Nextcloud) | sftp | local
      password_store: keyring      # keyring (Schlüsselbund) | file (hier im Klartext) | none
      webdav:
        url: https://cloud.example.org
        username: niko
        password: xxxxx-xxxxx-xxxxx-xxxxx-xxxxx   # nur bei password_store: file
        folder: Yaleno
      sftp:
        host: backup.example.org
        port: 22
        username: niko
        key_file: ~/.ssh/id_ed25519
        passphrase: ""             # nur bei password_store: file
        path: /srv/backup
      local:
        path: /mnt/nas/yaleno
    device: niko-pc
    sync:
      categories: [personal, shell, dev]
      conflicts: newer             # newer | local | remote
      exclude:                     # abgewählte Ordner/Dateien je Kategorie
        personal: ["{DOWNLOADS}/"]
    background:
      enabled: true
      interval_minutes: 15
      autostart: true
    plugins:
      enabled: [prismlauncher]     # aktive Plugins (siehe Plugin-Manager)
      check_updates: true          # Hintergrund-Abgleich sucht täglich nach Updates
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml
from platformdirs import user_config_dir, user_log_dir

from . import APP_ID

CONFIG_NAME = "yaleno.yml"
_config_override: Path | None = None


def config_dir() -> Path:
    return Path(user_config_dir(APP_ID, appauthor=False))


def config_file() -> Path:
    if _config_override is not None:
        return _config_override
    env = os.environ.get("YALENO_CONFIG")
    return Path(env).expanduser() if env else config_dir() / CONFIG_NAME


def set_config_file(path: str | os.PathLike | None) -> None:
    global _config_override
    _config_override = Path(path).expanduser().resolve() if path else None


def log_dir() -> Path:
    return Path(user_log_dir(APP_ID, appauthor=False))


def known_hosts_file() -> Path:
    return config_dir() / "known_hosts"


def sync_state_dir() -> Path:
    """Pro Speicher und Gerät: Stand des letzten Abgleichs (Grundlage für die Änderungserkennung)."""
    return config_dir() / "sync"


def default_staging_dir(tag: str) -> Path:
    return Path.home() / "Yaleno-Wiederherstellung" / tag


class ConfigError(ValueError):
    pass


@dataclass
class Profile:
    storage_type: str = "sftp"  # "sftp" | "webdav" | "local"
    local_dir: str = ""
    host: str = ""
    port: int = 22
    username: str = ""
    key_path: str = ""
    base_path: str = "."
    webdav_url: str = ""
    webdav_user: str = ""
    webdav_folder: str = "Yaleno"
    # Anmeldedaten: im Schlüsselbund oder (nur bei password_store=file) hier im Klartext
    password_store: str = "keyring"  # keyring | file | none
    webdav_password: str = ""
    sftp_passphrase: str = ""
    backup_name: str = ""
    sync_categories: list[str] | None = None  # zuletzt abgeglichene Kategorien
    sync_excludes: dict[str, list[str]] = field(default_factory=dict)
    conflicts: str = "newer"
    bg_enabled: bool = False
    bg_interval: int = 15
    bg_autostart: bool = False
    plugins_enabled: list[str] = field(default_factory=list)
    plugins_check_updates: bool = True

    # ------------------------------------------------------------------ YAML
    def to_yaml_dict(self, include_secrets: bool = True) -> dict:
        file_secrets = include_secrets and self.password_store == "file"
        webdav = {"url": self.webdav_url, "username": self.webdav_user, "folder": self.webdav_folder}
        sftp = {"host": self.host, "port": self.port, "username": self.username, "key_file": self.key_path,
                "path": self.base_path}
        if file_secrets:
            webdav["password"] = self.webdav_password
            sftp["passphrase"] = self.sftp_passphrase
        return {
            "storage": {
                "type": self.storage_type,
                "password_store": self.password_store,
                "webdav": webdav,
                "sftp": sftp,
                "local": {"path": self.local_dir},
            },
            "device": self.backup_name,
            "sync": {
                "categories": self.sync_categories,
                "conflicts": self.conflicts,
                "exclude": self.sync_excludes,
            },
            "background": {
                "enabled": self.bg_enabled,
                "interval_minutes": self.bg_interval,
                "autostart": self.bg_autostart,
            },
            "plugins": {
                "enabled": self.plugins_enabled,
                "check_updates": self.plugins_check_updates,
            },
        }

    @classmethod
    def from_yaml_dict(cls, d: dict) -> "Profile":
        if not isinstance(d, dict):
            raise ConfigError("Die Datei enthält keine Yaleno-Einstellungen.")

        def sec(parent: dict, key: str) -> dict:
            v = parent.get(key) or {}
            if not isinstance(v, dict):
                raise ConfigError(f"„{key}“ muss ein Abschnitt sein.")
            return v

        st, sync, bg, pl = sec(d, "storage"), sec(d, "sync"), sec(d, "background"), sec(d, "plugins")
        wd, sf, lo = sec(st, "webdav"), sec(st, "sftp"), sec(st, "local")
        typ = str(st.get("type", "sftp")).lower()
        if typ == "nextcloud":
            typ = "webdav"
        if typ not in ("sftp", "webdav", "local"):
            raise ConfigError(f"Unbekannter Speichertyp „{typ}“ (erlaubt: webdav, sftp, local).")
        has_plain = bool(wd.get("password") or sf.get("passphrase"))
        store = str(st.get("password_store") or ("file" if has_plain else "keyring")).lower()
        if store not in ("keyring", "file", "none"):
            raise ConfigError(f"Unbekannter password_store „{store}“ (erlaubt: keyring, file, none).")
        conflicts = str(sync.get("conflicts") or "newer").lower()
        if conflicts not in ("newer", "local", "remote"):
            raise ConfigError(f"Unbekannte Konfliktregel „{conflicts}“ (erlaubt: newer, local, remote).")
        cats = sync.get("categories")
        excl = sync.get("exclude") or {}
        if cats is not None and not isinstance(cats, list):
            raise ConfigError("sync.categories muss eine Liste sein.")
        if not isinstance(excl, dict):
            raise ConfigError("sync.exclude muss ein Abschnitt je Kategorie sein.")
        enabled = pl.get("enabled") or []
        if not isinstance(enabled, list):
            raise ConfigError("plugins.enabled muss eine Liste sein.")
        try:
            port = int(sf.get("port") or 22)
            interval = int(bg.get("interval_minutes") or 15)
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"Ungültige Zahl: {exc}") from exc
        return cls(
            storage_type=typ,
            local_dir=str(lo.get("path") or ""),
            host=str(sf.get("host") or ""), port=port, username=str(sf.get("username") or ""),
            key_path=str(sf.get("key_file") or ""), base_path=str(sf.get("path") or "."),
            webdav_url=str(wd.get("url") or ""), webdav_user=str(wd.get("username") or ""),
            webdav_folder=str(wd.get("folder") if wd.get("folder") is not None else "Yaleno"),
            password_store=store,
            webdav_password=str(wd.get("password") or ""), sftp_passphrase=str(sf.get("passphrase") or ""),
            backup_name=str(d.get("device") or ""),
            sync_categories=[str(c) for c in cats] if cats is not None else None,
            sync_excludes={str(k): [str(x) for x in (v or [])] for k, v in excl.items()},
            conflicts=conflicts,
            bg_enabled=bool(bg.get("enabled", False)),
            bg_interval=max(1, interval),
            bg_autostart=bool(bg.get("autostart", False)),
            plugins_enabled=[str(x) for x in enabled],
            plugins_check_updates=bool(pl.get("check_updates", True)),
        )

    def to_yaml(self, include_secrets: bool = True) -> str:
        head = ("# Yaleno Wizard – Verbindung, Anmeldung und Abgleich\n"
                "# Bearbeitbar; Format siehe README („Einstellungsdatei“).\n")
        return head + yaml.safe_dump(self.to_yaml_dict(include_secrets), allow_unicode=True, sort_keys=False)

    # ------------------------------------------------------------------ Laden/Speichern
    @classmethod
    def read(cls, path: Path) -> "Profile":
        """Liest eine Einstellungsdatei; ConfigError bei Fehlern."""
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"Datei kann nicht gelesen werden: {exc}") from exc
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Ungültiges YAML: {exc}") from exc
        return cls.from_yaml_dict(data)

    @classmethod
    def load(cls) -> "Profile":
        f = config_file()
        if f.exists():
            try:
                return cls.read(f)
            except ConfigError:
                return cls()
        legacy = config_dir() / "profile.json"  # ältere Versionen
        if legacy.exists() and _config_override is None:
            try:
                data = json.loads(legacy.read_text(encoding="utf-8"))
                names = {f.name for f in fields(cls)}
                return cls(**{k: v for k, v in data.items() if k in names})
            except (OSError, ValueError, TypeError):
                pass
        return cls()

    def write(self, path: Path, include_secrets: bool = True) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        # Anmeldedaten können enthalten sein → nur für den Benutzer lesbar
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self.to_yaml(include_secrets))
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def save(self) -> None:
        self.write(config_file())
