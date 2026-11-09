"""Erzeugt aus assets/yaleno.svg alle Symbolgrößen (PNG) und die Windows-Symboldatei (ICO).

    .venv/bin/python scripts/make_icons.py

Nur nötig, wenn sich das Logo ändert – die Ergebnisse liegen im Repository.
"""

from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "src" / "yaleno_wizard" / "assets"
PNG_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def render(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(p)
    p.end()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data.data())


def build_ico(images: dict[int, bytes]) -> bytes:
    """ICO mit PNG-Einträgen (von Windows ab Vista für alle Größen unterstützt)."""
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    offset = 6 + 16 * len(images)
    for size, png in sorted(images.items()):
        dim = 0 if size >= 256 else size  # 0 bedeutet 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    return header + entries + blobs


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 – für QPainter nötig
    renderer = QSvgRenderer(str(ASSETS / "yaleno.svg"))
    if not renderer.isValid():
        print("yaleno.svg ist ungültig")
        return 1
    rendered = {s: render(renderer, s) for s in sorted(set(PNG_SIZES) | set(ICO_SIZES))}
    for s in PNG_SIZES:
        (ASSETS / f"yaleno-{s}.png").write_bytes(rendered[s])
    (ASSETS / "yaleno.ico").write_bytes(build_ico({s: rendered[s] for s in ICO_SIZES}))
    print(f"{len(PNG_SIZES)} PNG-Dateien und yaleno.ico in {ASSETS} geschrieben.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
