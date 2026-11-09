"""Seite 3 (nur Verlauf): Version wählen – vor- und zurückspringen."""

from __future__ import annotations

import html

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWizardPage,
)

from ...core.entry import human_size
from ...core.store import Revision, RevisionInfo
from ..state import HistoryAction, WizardState


def _changes(i: RevisionInfo) -> str:
    parts = [f"+{i.added}" if i.added else "", f"~{i.changed}" if i.changed else "",
             f"−{i.deleted}" if i.deleted else ""]
    return " ".join(p for p in parts if p) or "–"


class HistoryPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Verlauf")
        self.setSubTitle("Jede Version ist ein vollständiger Stand des Speichers. Springe zu einer Version, "
                         "um einzelne Dateien zurückzuholen oder den ganzen Speicher auf diesen Stand zu setzen.")
        self._cache: dict[int, Revision] = {}
        self._head = 0

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Version", "Datum", "Gerät", "Änderungen", "Bestand", "Beschreibung"])
        self.tree.setRootIsDecorated(False)
        self.tree.setToolTip("+ neu  ~ geändert  − gelöscht")
        self.tree.itemSelectionChanged.connect(self._selected)

        self.older = QPushButton("◀ Älter")
        self.older.clicked.connect(lambda: self._step(+1))
        self.newer = QPushButton("Neuer ▶")
        self.newer.clicked.connect(lambda: self._step(-1))
        nav = QHBoxLayout()
        nav.addWidget(self.older)
        nav.addWidget(self.newer)
        nav.addStretch(1)

        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)

        self.source = QComboBox()
        self.source.setToolTip("Persönliche Dateien gelten für alle Geräte. Einstellungen gelten pro "
                               "Betriebssystem, Systemdateien und Paketlisten pro Gerät.")
        self.source.currentIndexChanged.connect(lambda _i: self.completeChanged.emit())
        self.rb_restore = QRadioButton("Einzelne Dateien aus dieser Version auf dieses Gerät holen")
        self.rb_reset = QRadioButton("Speicher auf diese Version setzen – alle Geräte übernehmen den Stand "
                                     "beim nächsten Abgleich")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_restore)
        grp.addButton(self.rb_reset)
        self.rb_restore.setChecked(True)
        self.rb_restore.toggled.connect(self._update_source)

        form = QFormLayout()
        form.addRow("Daten von Gerät:", self.source)

        lay = QVBoxLayout(self)
        lay.addWidget(self.tree, 1)
        lay.addLayout(nav)
        lay.addWidget(self.info)
        lay.addWidget(self.rb_restore)
        lay.addLayout(form)
        lay.addWidget(self.rb_reset)

    # ------------------------------------------------------------------
    def initializePage(self) -> None:
        self.tree.clear()
        self._cache.clear()
        store = self.state.store
        assert store is not None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            self._head = store.head()
            infos = store.list_revisions()
        except Exception as exc:
            infos = []
            self.info.setText(f"⚠ Verlauf konnte nicht gelesen werden: {html.escape(str(exc))}")
        finally:
            QApplication.restoreOverrideCursor()
        for i in infos:
            date = i.date.strftime("%d.%m.%Y %H:%M") if i.date else i.created
            label = f"{i.number}" + ("  (aktuell)" if i.number == self._head else "")
            it = QTreeWidgetItem([label, date, i.host, _changes(i), f"{i.files} · {human_size(i.size)}",
                                  i.message])
            it.setData(0, Qt.ItemDataRole.UserRole, i.number)
            if i.number == self._head:
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
            self.tree.addTopLevelItem(it)
        for c in range(5):
            self.tree.resizeColumnToContents(c)
        if not infos:
            self.info.setText("Im Speicher gibt es noch keine Versionen.")
            return
        # bisherige Wahl beibehalten, sonst die aktuelle Version
        want = self.state.revision.number if self.state.revision else self._head
        for idx in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(idx)
            if it.data(0, Qt.ItemDataRole.UserRole) == want:
                self.tree.setCurrentItem(it)
                break
        else:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _step(self, delta: int) -> None:
        cur = self.tree.currentItem()
        row = self.tree.indexOfTopLevelItem(cur) if cur else 0
        row = max(0, min(self.tree.topLevelItemCount() - 1, row + delta))
        self.tree.setCurrentItem(self.tree.topLevelItem(row))

    def _current(self) -> int | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else None

    def _load(self, n: int) -> Revision | None:
        if n not in self._cache:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                self._cache[n] = self.state.store.load_revision(n)  # type: ignore[union-attr]
            except Exception as exc:
                self.info.setText(f"⚠ Version {n} konnte nicht gelesen werden: {html.escape(str(exc))}")
                return None
            finally:
                QApplication.restoreOverrideCursor()
        return self._cache[n]

    def _selected(self) -> None:
        n = self._current()
        row = self.tree.indexOfTopLevelItem(self.tree.currentItem()) if self.tree.currentItem() else -1
        self.newer.setEnabled(row > 0)
        self.older.setEnabled(0 <= row < self.tree.topLevelItemCount() - 1)
        self.completeChanged.emit()
        if n is None:
            return
        rev = self._load(n)
        if not rev:
            return
        is_head = n == self._head
        self.rb_reset.setEnabled(not is_head)
        if is_head and self.rb_reset.isChecked():
            self.rb_restore.setChecked(True)

        # Geräte-Auswahl: dieses Gerät zuerst
        prev = self.source.currentData() or self.state.source_host or self.state.host_name
        self.source.blockSignals(True)
        self.source.clear()
        hosts = sorted(rev.devices, key=lambda h: (h != self.state.host_name, h.lower()))
        if self.state.host_name not in rev.devices:
            hosts.insert(0, self.state.host_name)
        for h in hosts:
            os_name = rev.devices.get(h, self.state.os_name)
            label = f"{h} ({'Windows' if os_name == 'windows' else 'Linux'})"
            if h == self.state.host_name:
                label += " – dieses Gerät"
            self.source.addItem(label, h)
        idx = self.source.findData(prev)
        self.source.setCurrentIndex(max(idx, 0))
        self.source.blockSignals(False)
        self._update_source()

        i = rev.info
        date = i.date.strftime("%d.%m.%Y %H:%M") if i.date else i.created
        hint = "Das ist der aktuelle Stand." if is_head else (
            f"Älterer Stand. Der aktuelle Stand (Version {self._head}) bleibt beim Zurücksetzen im Verlauf "
            "erhalten – du kannst jederzeit wieder vorspringen.")
        self.info.setText(
            f"<b>Version {n}</b> vom {date} · von {html.escape(i.host)} · {i.files} Dateien · "
            f"{human_size(i.size)}<br>{html.escape(i.message)}<br><i>{hint}</i>"
        )

    def _update_source(self) -> None:
        self.source.setEnabled(self.rb_restore.isChecked())

    def isComplete(self) -> bool:
        n = self._current()
        return n is not None and n in self._cache

    def validatePage(self) -> bool:
        n = self._current()
        rev = self._load(n) if n is not None else None
        if not rev:
            return False
        source = self.source.currentData() or self.state.host_name
        action = HistoryAction.RESTORE if self.rb_restore.isChecked() else HistoryAction.RESET
        if (self.state.revision is None or self.state.revision.number != n
                or self.state.source_host != source):
            self.state.categories = []
            self.state.selected = None
        self.state.revision = rev
        self.state.source_host = source
        self.state.history_action = action
        return True
