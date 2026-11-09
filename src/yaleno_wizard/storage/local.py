"""Speicher in einem lokalen Ordner (USB-Platte, Netzlaufwerk, Tests)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO

from .base import Storage


class LocalStorage(Storage):
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        parts = [p for p in path.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise ValueError(f"Ungültiger Pfad: {path}")
        return self.root.joinpath(*parts)

    def listdir(self, path: str) -> list[str]:
        return sorted(os.listdir(self._p(path)))

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def is_dir(self, path: str) -> bool:
        return self._p(path).is_dir()

    def mkdir(self, path: str) -> None:
        self._p(path).mkdir()

    def open_read(self, path: str) -> BinaryIO:
        return open(self._p(path), "rb")

    def open_write(self, path: str) -> BinaryIO:
        return open(self._p(path), "wb")

    def rename(self, src: str, dst: str) -> None:
        os.replace(self._p(src), self._p(dst))

    def remove(self, path: str) -> None:
        self._p(path).unlink()

    def chmod(self, path: str, mode: int) -> None:
        try:
            os.chmod(self._p(path), mode)
        except OSError:
            pass

    @property
    def description(self) -> str:
        return f"Ordner {self.root}"
