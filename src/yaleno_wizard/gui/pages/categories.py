"""Seite 4: Kategorien auswählen (beim Sichern mit vorherigem Scan)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
    QWizardPage,
)

from ...core.entry import human_size
from ...core.scanner import ScanResult, Scanner
from ..state import Mode, WizardState
from ..worker import Worker


class CategoriesPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Kategorien auswählen")
        self._worker: Worker | None = None
        self._ready = False

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.busy_label = QLabel()
        self.list = QListWidget()
        self.list.itemChanged.connect(lambda _i: self.completeChanged.emit())
        self.list.currentItemChanged.connect(self._show_desc)
        self.desc = QLabel()
        self.desc.setWordWrap(True)
        self.desc.setMinimumHeight(48)
        self.rescan_btn = QPushButton("Neu durchsuchen")
        self.rescan_btn.clicked.connect(self._start_scan)
        self.skipped_label = QLabel()
        self.skipped_label.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(self.busy_label)
        lay.addWidget(self.busy)
        lay.addWidget(self.list, 1)
        lay.addWidget(self.desc)
        row = QHBoxLayout()
        row.addWidget(self.skipped_label, 1)
        row.addWidget(self.rescan_btn)
        lay.addLayout(row)

    # ------------------------------------------------------------------ init
    def initializePage(self) -> None:
        if self.state.mode == Mode.BACKUP:
            self.setSubTitle("Was soll gesichert werden? Die Zahlen zeigen, was auf diesem Rechner gefunden wurde.")
            self.rescan_btn.show()
            if self.state.scan is None:
                self._start_scan()
            else:
                self._fill_backup()
        else:
            self.setSubTitle("Was soll wiederhergestellt werden?")
            self.rescan_btn.hide()
            self.busy.hide()
            self.busy_label.hide()
            self.skipped_label.clear()
            self._fill_restore()

    def _start_scan(self) -> None:
        self._ready = False
        self.list.clear()
        self.completeChanged.emit()
        self.busy.show()
        self.busy_label.show()
        self.busy_label.setText("Durchsuche diesen Rechner …")
        self.rescan_btn.setEnabled(False)
        state = self.state

        def job(rep) -> ScanResult:
            return Scanner(state.mapper, progress=rep.log, cancelled=rep.cancelled).scan(state.catalog)

        self._worker = Worker(job, self)
        self._worker.log.connect(self.busy_label.setText)
        self._worker.succeeded.connect(self._scan_done)
        self._worker.failed.connect(lambda msg: self.busy_label.setText(f"⚠ Fehler beim Durchsuchen: {msg}"))
        self._worker.start()

    def _scan_done(self, result: ScanResult) -> None:
        self.state.scan = result
        self.state.selected = None
        self.busy.hide()
        self.busy_label.hide()
        self.rescan_btn.setEnabled(True)
        self._fill_backup()

    # ------------------------------------------------------------------ füllen
    def _add(self, cid: str, name: str, desc: str, count: int, size: int, enabled: bool,
             checked: bool, tags: list[str], reason: str = "") -> None:
        text = f"{name}   —   {count} Dateien · {human_size(size)}"
        if tags:
            text += "   [" + ", ".join(tags) + "]"
        if reason:
            text += f"   ({reason})"
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, cid)
        it.setData(Qt.ItemDataRole.UserRole + 1, desc)
        it.setToolTip(desc)
        flags = Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable
        if enabled:
            flags |= Qt.ItemFlag.ItemIsEnabled
        it.setFlags(flags)
        it.setCheckState(Qt.CheckState.Checked if checked and enabled else Qt.CheckState.Unchecked)
        self.list.addItem(it)

    def _previous(self, cid: str, default: bool) -> bool:
        return cid in self.state.categories if self.state.categories else default

    def _fill_backup(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        scan = self.state.scan
        totals = scan.totals() if scan else {}
        for c in self.state.catalog.categories:
            n, s = totals.get(c.id, (0, 0))
            tags = []
            if c.sensitive:
                tags.append("⚠ sensibel")
            if c.requires_admin:
                tags.append("System")
            if c.cross_os:
                tags.append("auch für Windows/Linux")
            self._add(c.id, c.name, c.description, n, s, n > 0, self._previous(c.id, c.default_selected),
                      tags, "" if n else "nichts gefunden")
        self.list.blockSignals(False)
        if scan and scan.skipped:
            self.skipped_label.setText(f"{len(scan.skipped)} Dateien übersprungen (keine Leserechte, Links …)")
            self.skipped_label.setToolTip("\n".join(f"{p}: {r}" for p, r in scan.skipped[:40]))
        self._ready = True
        self.completeChanged.emit()

    def _fill_restore(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        m = self.state.manifest
        assert m is not None
        totals: dict[str, tuple[int, int]] = {}
        for e in m.entries:
            n, s = totals.get(e.category, (0, 0))
            totals[e.category] = (n + 1, s + e.size)
        same_os = m.os == self.state.os_name
        for cid, meta in m.categories.items():
            n, s = totals.get(cid, (0, 0))
            ok = n > 0 and (same_os or bool(meta.get("cross_os")))
            reason = "" if ok else ("nur auf " + ("Windows" if m.os == "windows" else "Linux"))
            tags = ["⚠ sensibel"] if meta.get("sensitive") else []
            if meta.get("requires_admin"):
                tags.append("in Ablageordner")
            default = not meta.get("requires_admin") and not meta.get("sensitive")
            self._add(cid, meta.get("name", cid), meta.get("description", ""), n, s, ok,
                      self._previous(cid, default), tags, reason)
        self.list.blockSignals(False)
        self._ready = True
        self.completeChanged.emit()

    def _show_desc(self, cur: QListWidgetItem | None, _prev=None) -> None:
        self.desc.setText(cur.data(Qt.ItemDataRole.UserRole + 1) if cur else "")

    # ------------------------------------------------------------------ wizard
    def _checked(self) -> list[str]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked and it.flags() & Qt.ItemFlag.ItemIsEnabled:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out

    def isComplete(self) -> bool:
        return self._ready and bool(self._checked())

    def validatePage(self) -> bool:
        self.state.categories = self._checked()
        return True

    def cleanupPage(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
