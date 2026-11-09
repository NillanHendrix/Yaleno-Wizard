from __future__ import annotations

import os
from pathlib import Path

import pytest

from yaleno_wizard.catalog.placeholders import PathMapper


@pytest.fixture
def fake_home(tmp_path: Path) -> dict[str, Path]:
    home = tmp_path / "home"
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
        "ROOT": tmp_path / "root",
    }
    for p in m.values():
        p.mkdir(parents=True, exist_ok=True)

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
    w(m["CONFIG"] / "someapp" / "settings.ini", "a=1")
    w(m["CONFIG"] / "someapp" / "Cache" / "blob", "cache")
    w(m["ROOT"] / "etc" / "fstab", "UUID=1 / ext4")
    return m


@pytest.fixture
def mapper(fake_home) -> PathMapper:
    return PathMapper(fake_home)
