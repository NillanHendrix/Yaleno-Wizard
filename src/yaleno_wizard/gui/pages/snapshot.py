"""Seite 3 (nur Wiederherstellen): Snapshot auswählen."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWizardPage,
)

from ...core.entry import human_size
from ...core.manifest import Manifest, SnapshotInfo, list_snapshots, load_manifest
from ..state import WizardState


class SnapshotPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Sicherung auswählen")
        self.setSubTitle("Aus welcher Sicherung soll wiederhergestellt werden?")
        self._cache: dict[str, Manifest] = {}

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Rechner", "Datum"])
        self.tree.setRootIsDecorated(False)
        self.tree.itemSelectionChanged.connect(self._selected)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.info)

    def initializePage(self) -> None:
        self.tree.clear()
        self._cache.clear()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            snaps = list_snapshots(self.state.storage, self.state.base_path)  # type: ignore[arg-type]
        except Exception as exc:
            snaps = []
            self.info.setText(f"⚠ Konnte Sicherungen nicht auflisten: {exc}")
        finally:
            QApplication.restoreOverrideCursor()
        for s in snaps:
            date = s.date.strftime("%d.%m.%Y %H:%M:%S") if s.date else s.snapshot
            it = QTreeWidgetItem([s.host, date])
            it.setData(0, Qt.ItemDataRole.UserRole, s)
            self.tree.addTopLevelItem(it)
        self.tree.resizeColumnToContents(0)
        if not snaps:
            self.info.setText("Auf diesem Speicher wurden keine Sicherungen gefunden.")
        else:
            # eigene, neueste Sicherung vorauswählen
            for i in range(self.tree.topLevelItemCount()):
                it = self.tree.topLevelItem(i)
                if it.text(0) == self.state.host_name:
                    self.tree.setCurrentItem(it)
                    break
            else:
                self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _current(self) -> SnapshotInfo | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def _load(self, s: SnapshotInfo) -> Manifest | None:
        if s.path not in self._cache:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._cache[s.path] = load_manifest(self.state.storage, s.path)  # type: ignore[arg-type]
            except Exception as exc:
                self.info.setText(f"⚠ Manifest konnte nicht gelesen werden: {exc}")
                return None
            finally:
                QApplication.restoreOverrideCursor()
        return self._cache[s.path]

    def _selected(self) -> None:
        s = self._current()
        self.completeChanged.emit()
        if not s:
            return
        m = self._load(s)
        if not m:
            return
        os_name = "Windows" if m.os == "windows" else "Linux"
        cats = ", ".join(meta.get("name", cid) for cid, meta in m.categories.items())
        warn = ""
        if m.os != self.state.os_name:
            warn = (f"<br><b>Hinweis:</b> Sicherung stammt von {os_name}. Es lassen sich nur "
                    "persönliche Dateien auf diesem Betriebssystem wiederherstellen.")
        errs = f"<br>Fehler beim Sichern: {len(m.errors)}" if m.errors else ""
        self.info.setText(
            f"<b>{m.host}</b> · {os_name} · {len(m.entries)} Dateien · {human_size(m.total_size)}"
            f"<br>Kategorien: {cats}{errs}{warn}"
        )

    def isComplete(self) -> bool:
        s = self._current()
        return s is not None and s.path in self._cache

    def validatePage(self) -> bool:
        s = self._current()
        m = self._load(s) if s else None
        if not m:
            return False
        if self.state.snapshot is None or self.state.snapshot.path != s.path:
            self.state.categories = []
            self.state.selected = None
        self.state.snapshot = s
        self.state.manifest = m
        return True
