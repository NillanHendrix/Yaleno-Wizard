from __future__ import annotations

import os
from pathlib import Path

import pytest

from yaleno_wizard.catalog.placeholders import PathMapper


class MemoryKeyring:
    """Schlüsselbund für Tests – der echte des Systems wird nie angefasst."""

    priority = 10

    def __init__(self):
        self.data: dict[tuple[str, str], str] = {}

    def get_password(self, service, user):
        return self.data.get((service, user))

    def set_password(self, service, user, pw):
        self.data[(service, user)] = pw

    def delete_password(self, service, user):
        self.data.pop((service, user), None)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Einstellungen, Logs und Schlüsselbund jedes Tests in tmp_path."""
    import keyring

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("YALENO_CONFIG", raising=False)
    kr = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: kr)
    monkeypatch.setattr(keyring, "get_password", kr.get_password)
    monkeypatch.setattr(keyring, "set_password", kr.set_password)
    monkeypatch.setattr(keyring, "delete_password", kr.delete_password)
    from yaleno_wizard import settings
    monkeypatch.setattr(settings, "_config_override", None)
    return kr


def build_home(tmp_path: Path, name: str = "home", files: bool = True) -> dict[str, Path]:
    home = tmp_path / name
    m = {
        "HOME": home,
        "DOCUMENTS": home / "Dokumente",
        "PICTURES": home / "Bilder",
        "MUSIC": home / "Musik",
        "VIDEOS": home / "Videos",
        "DESKTOP": home / "Schreibtisch",
        "DOWNLOADS": home / "Downloads",
        "CONFIG": home / ".config",
        "DATA": home / ".local" / "share",
        "ROOT": tmp_path / f"{name}-root",
    }
    for p in m.values():
        p.mkdir(parents=True, exist_ok=True)
    if not files:
        return m

    def w(rel: Path, text: str) -> None:
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_text(text)

    w(m["DOCUMENTS"] / "Rechnungen" / "2026.pdf", "pdf-inhalt")
    w(m["DOCUMENTS"] / "notiz.txt", "hallo")
    w(m["DOCUMENTS"] / "node_modules" / "x.js", "nein")
    w(m["PICTURES"] / "Urlaub" / "IMG_0001.jpg", "bild")
    w(home / ".bashrc", "alias ll='ls -l'")
    w(home / ".ssh" / "id_ed25519", "PRIVATE")
    os.chmod(home / ".ssh" / "id_ed25519", 0o600)
    w(m["CONFIG"] / "fish" / "config.fish", "set -g x 1")
    w(m["CONFIG"] / "kdeglobals", "[General]")
    w(m["CONFIG"] / "kwinrc", "[Windows]")
    w(m["CONFIG"] / "hypr" / "hyprland.lua", "-- Hyprland")
    w(m["CONFIG"] / "waybar" / "config.jsonc", "{}")
    w(m["CONFIG"] / "someapp" / "settings.ini", "a=1")
    w(m["CONFIG"] / "someapp" / "Cache" / "blob", "cache")
    w(m["ROOT"] / "etc" / "fstab", "UUID=1 / ext4")
    return m


@pytest.fixture
def fake_home(tmp_path: Path) -> dict[str, Path]:
    return build_home(tmp_path)


@pytest.fixture
def mapper(fake_home) -> PathMapper:
    return PathMapper(fake_home)
