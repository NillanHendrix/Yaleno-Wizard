"""Logo und Symbole des Yaleno Wizard."""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parent
PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)


def png(size: int) -> Path:
    return ASSETS / f"yaleno-{size}.png"


def svg() -> Path:
    return ASSETS / "yaleno.svg"


def ico() -> Path:
    return ASSETS / "yaleno.ico"


def app_icon():
    """QIcon mit allen Größen (Fenster, Taskleiste, Infobereich)."""
    from PySide6.QtGui import QIcon

    icon = QIcon()
    for s in PNG_SIZES:
        p = png(s)
        if p.exists():
            icon.addFile(str(p))
    return icon
