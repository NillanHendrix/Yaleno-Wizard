"""Datenmodell des Katalogs: Kategorien und deren Einträge (Items)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Literal

OSName = Literal["linux", "windows"]

# Ordner-/Dateinamen, die nie gesichert werden (Caches, Müll, Lockfiles).
GLOBAL_EXCLUDES: tuple[str, ...] = (
    "Cache", "cache", "Caches", "caches", "cache2", "CachedData", "CachedExtensions",
    "CachedExtensionVSIXs", "Code Cache", "GPUCache", "GrShaderCache", "ShaderCache",
    "DawnCache", "DawnGraphiteCache", "DawnWebGPUCache", "Service Worker", "startupCache",
    "Crash Reports", "Crashpad", "crashes", "minidumps",
    "node_modules", "__pycache__", ".Trash", ".Trash-*", "$RECYCLE.BIN",
    "*.tmp", "*.part", "*.crdownload", "lock", ".lock", "parent.lock", "SingletonLock",
    "SingletonCookie", "SingletonSocket", "desktop.ini", "Thumbs.db",
)


@dataclass(frozen=True)
class Item:
    """Ein Eintrag einer Kategorie.

    kind="path": ``paths`` enthält logische Pfade wie ``{CONFIG}/k*rc`` (Globs erlaubt).
    kind="command": ``backup_cmd`` erzeugt eine Datei (stdout oder ``{OUT}``),
    ``restore_cmd`` spielt sie wieder ein (stdin oder ``{IN}``).
    """

    id: str
    label: str
    kind: Literal["path", "command"] = "path"
    paths: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    backup_cmd: tuple[str, ...] = ()
    restore_cmd: tuple[str, ...] = ()
    output_ext: str = "txt"

    @property
    def command_available(self) -> bool:
        return bool(self.backup_cmd) and shutil.which(self.backup_cmd[0]) is not None

    @property
    def command_logical(self) -> str:
        return f"@cmd/{self.id}.{self.output_ext}"


@dataclass(frozen=True)
class Category:
    id: str
    name: str
    description: str
    os: OSName
    items: tuple[Item, ...]
    cross_os: bool = False
    sensitive: bool = False
    requires_admin: bool = False
    # Niedriger Wert = Dateien werden zuerst dieser Kategorie zugeordnet.
    claim_priority: int = 0
    default_selected: bool = True

    def item(self, item_id: str) -> Item | None:
        for it in self.items:
            if it.id == item_id:
                return it
        return None

    def meta(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "cross_os": self.cross_os,
            "sensitive": self.sensitive,
            "requires_admin": self.requires_admin,
        }


@dataclass
class Catalog:
    os: OSName
    categories: list[Category] = field(default_factory=list)

    def get(self, cat_id: str) -> Category | None:
        for c in self.categories:
            if c.id == cat_id:
                return c
        return None
