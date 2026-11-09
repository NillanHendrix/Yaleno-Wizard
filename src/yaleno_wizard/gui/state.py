"""Gemeinsamer Zustand aller Wizard-Seiten."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from enum import Enum

from ..catalog import Catalog, PathMapper, catalog_for, current_os
from ..core.entry import Entry
from ..core.manifest import Manifest, SnapshotInfo
from ..core.scanner import ScanResult
from ..settings import Profile
from ..storage.base import Storage


class Mode(str, Enum):
    BACKUP = "backup"
    RESTORE = "restore"


@dataclass
class WizardState:
    profile: Profile = field(default_factory=Profile.load)
    storage: Storage | None = None
    storage_key: tuple | None = None  # Verbindungsparameter des offenen Speichers
    base_path: str = "."

    mode: Mode = Mode.BACKUP
    host_name: str = field(default_factory=socket.gethostname)
    os_name: str = field(default_factory=current_os)
    catalog: Catalog = field(default_factory=catalog_for)
    mapper: PathMapper = field(default_factory=PathMapper.for_current_system)

    scan: ScanResult | None = None
    snapshot: SnapshotInfo | None = None
    manifest: Manifest | None = None

    categories: list[str] = field(default_factory=list)   # gewählte Kategorie-IDs
    selected: set[tuple[str, str]] | None = None          # gewählte Einträge (None = alle)

    def available_entries(self) -> list[Entry]:
        if self.mode == Mode.BACKUP:
            return self.scan.entries if self.scan else []
        return self.manifest.entries if self.manifest else []

    def category_names(self) -> dict[str, str]:
        names = {c.id: c.name for c in self.catalog.categories}
        if self.mode == Mode.RESTORE and self.manifest:
            for cid, meta in self.manifest.categories.items():
                names[cid] = meta.get("name", cid)
        return names

    def entries_in_categories(self) -> list[Entry]:
        cats = set(self.categories)
        return [e for e in self.available_entries() if e.category in cats]

    def selected_entries(self) -> list[Entry]:
        entries = self.entries_in_categories()
        if self.selected is None:
            return entries
        return [e for e in entries if e.key in self.selected]

    def close_storage(self) -> None:
        if self.storage is not None:
            try:
                self.storage.close()
            except Exception:
                pass
        self.storage = None
        self.storage_key = None
