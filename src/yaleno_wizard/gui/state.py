"""Gemeinsamer Zustand aller Wizard-Seiten."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from enum import Enum

from ..catalog import Catalog, PathMapper, catalog_for, current_os
from ..core.entry import Entry
from ..core.scanner import ScanResult
from ..core.store import Revision, Store, device_scopes, sanitize_host
from ..core.sync import SyncPlan, SyncState
from ..settings import Profile
from ..storage.base import Storage


class Mode(str, Enum):
    SYNC = "sync"          # Gerät und Speicher abgleichen
    HISTORY = "history"    # im Verlauf springen / einzelne Dateien zurückholen


class HistoryAction(str, Enum):
    RESTORE = "restore"    # ausgewählte Dateien einer Version auf dieses Gerät holen
    RESET = "reset"        # gesamten Speicher auf eine Version zurück-/vorsetzen


@dataclass
class WizardState:
    profile: Profile = field(default_factory=Profile.load)
    storage: Storage | None = None
    storage_key: tuple | None = None  # Verbindungsparameter des offenen Speichers
    base_path: str = "."
    store: Store | None = None

    mode: Mode = Mode.SYNC
    history_action: HistoryAction = HistoryAction.RESTORE
    host_name: str = field(default_factory=lambda: sanitize_host(socket.gethostname()))
    os_name: str = field(default_factory=current_os)
    catalog: Catalog = field(default_factory=catalog_for)
    mapper: PathMapper = field(default_factory=PathMapper.for_current_system)

    # Abgleich
    scan: ScanResult | None = None
    remote: Revision | None = None        # aktueller Stand im Speicher (zum Zeitpunkt des Scans)
    plan: SyncPlan | None = None
    sync_state: SyncState | None = None

    # Verlauf
    revision: Revision | None = None      # gewählte Version
    source_host: str = ""                 # Gerät, dessen Daten aus der Version geholt werden

    categories: list[str] = field(default_factory=list)   # gewählte Kategorie-IDs
    selected: set[tuple[str, str]] | None = None          # gewählte Einträge (None = alle)

    # ------------------------------------------------------------------
    @property
    def source_os(self) -> str:
        if self.revision and self.source_host in self.revision.devices:
            return self.revision.devices[self.source_host]
        return self.os_name

    def remote_entries(self) -> list[Entry]:
        """Einträge im Speicher, die zu diesem Gerät gehören (alle Geräte / gleiches OS / dieses Gerät)."""
        if not self.remote:
            return []
        return self.remote.entries_for_device(self.os_name, self.host_name)

    def available_entries(self) -> list[Entry]:
        if self.mode == Mode.SYNC:
            local = self.scan.entries if self.scan else []
            seen = {e.logical for e in local}
            known = {c.id for c in self.catalog.categories}
            extra = [e for e in self.remote_entries() if e.logical not in seen and e.category in known]
            return local + extra
        if not self.revision:
            return []
        return self.revision.entries_for_device(self.source_os, self.source_host)

    def remote_only(self, e: Entry) -> bool:
        return self.mode == Mode.SYNC and e.source is None and not e.is_command

    def category_names(self) -> dict[str, str]:
        names = {c.id: c.name for c in self.catalog.categories}
        rev = self.remote if self.mode == Mode.SYNC else self.revision
        if rev:
            for cid, meta in rev.categories.items():
                names.setdefault(cid, meta.get("name", cid))
        return names

    def entries_in_categories(self) -> list[Entry]:
        cats = set(self.categories)
        return [e for e in self.available_entries() if e.category in cats]

    def selected_entries(self) -> list[Entry]:
        entries = self.entries_in_categories()
        if self.selected is None:
            return entries
        return [e for e in entries if e.key in self.selected]

    def device_scopes(self) -> set[str]:
        return device_scopes(self.os_name, self.host_name)

    def reset_run(self) -> None:
        """Vor einer neuen Aktion: alles verwerfen, was von der letzten Aktion abhängt."""
        self.scan = None
        self.remote = None
        self.plan = None
        self.sync_state = None
        self.revision = None
        self.selected = None
        self.categories = []

    def close_storage(self) -> None:
        if self.storage is not None:
            try:
                self.storage.close()
            except Exception:
                pass
        self.storage = None
        self.storage_key = None
        self.store = None
