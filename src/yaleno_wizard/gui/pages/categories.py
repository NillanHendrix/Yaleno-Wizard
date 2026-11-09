"""Seite 4: Kategorien auswählen (beim Abgleich mit vorherigem Scan dieses Geräts)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QVBoxLayout,
    QWizardPage,
)

from ...core.entry import human_size
from ...core.scanner import Scanner
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
        if self.state.mode == Mode.SYNC:
            self.setSubTitle("Was soll abgeglichen werden? „hier“ = auf diesem Gerät gefunden, "
                             "„Speicher“ = zentral abgelegt und für dieses Gerät verfügbar.")
            self.rescan_btn.show()
            if self.state.scan is None:
                self._start_scan()
            else:
                self._fill_sync()
        else:
            self.setSubTitle("Was soll aus dieser Version geholt werden?")
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
        self.busy_label.setText("Durchsuche dieses Gerät …")
        self.rescan_btn.setEnabled(False)
        state = self.state
        store = state.store

        def job(rep):
            rep.log("Lese aktuellen Stand des Speichers …")
            remote = store.load_head() if store else None
            scan = Scanner(state.mapper, progress=rep.log, cancelled=rep.cancelled).scan(state.catalog)
            return scan, remote

        self._worker = Worker(job, self)
        self._worker.log.connect(self.busy_label.setText)
        self._worker.succeeded.connect(self._scan_done)
        self._worker.failed.connect(lambda msg: self.busy_label.setText(f"⚠ Fehler beim Durchsuchen: {msg}"))
        self._worker.start()

    def _scan_done(self, result) -> None:
        self.state.scan, self.state.remote = result
        self.state.selected = None
        self.state.plan = None
        self.busy.hide()
        self.busy_label.hide()
        self.rescan_btn.setEnabled(True)
        self._fill_sync()

    # ------------------------------------------------------------------ füllen
    def _add(self, cid: str, name: str, desc: str, counts: str, enabled: bool,
             checked: bool, tags: list[str], reason: str = "") -> None:
        text = f"{name}   —   {counts}"
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

    def _previous(self, cid: str, default: bool, remembered: list[str] | None = None) -> bool:
        if self.state.categories:
            return cid in self.state.categories
        if remembered is not None:
            return cid in remembered
        return default

    @staticmethod
    def _totals(entries) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for e in entries:
            n, s = out.get(e.category, (0, 0))
            out[e.category] = (n + 1, s + e.size)
        return out

    def _fill_sync(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        scan = self.state.scan
        here = scan.totals() if scan else {}
        there = self._totals(self.state.remote_entries())
        remembered = self.state.profile.sync_categories
        for c in self.state.catalog.categories:
            n, s = here.get(c.id, (0, 0))
            rn, rs = there.get(c.id, (0, 0))
            tags = []
            if c.sensitive:
                tags.append("⚠ sensibel")
            if c.requires_admin:
                tags.append("nur dieses Gerät")
            if c.cross_os:
                tags.append("alle Geräte, auch Windows/Linux")
            counts = f"hier {n} Dateien · {human_size(s)}"
            if self.state.remote is not None:
                counts += f"   |   Speicher {rn} · {human_size(rs)}"
            ok = n > 0 or rn > 0
            self._add(c.id, c.name, c.description, counts, ok,
                      self._previous(c.id, c.default_selected, remembered), tags, "" if ok else "nichts gefunden")
        self.list.blockSignals(False)
        if scan and scan.skipped:
            self.skipped_label.setText(f"{len(scan.skipped)} Dateien übersprungen (keine Leserechte, Links …)")
            self.skipped_label.setToolTip("\n".join(f"{p}: {r}" for p, r in scan.skipped[:40]))
        self._ready = True
        self.completeChanged.emit()

    def _fill_restore(self) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        rev = self.state.revision
        assert rev is not None
        totals = self._totals(self.state.available_entries())
        src_os = self.state.source_os
        same_os = src_os == self.state.os_name
        for cid, meta in rev.categories.items():
            n, s = totals.get(cid, (0, 0))
            if n == 0:
                continue
            ok = same_os or bool(meta.get("cross_os"))
            reason = "" if ok else ("nur auf " + ("Windows" if src_os == "windows" else "Linux"))
            tags = ["⚠ sensibel"] if meta.get("sensitive") else []
            if meta.get("requires_admin"):
                tags.append("in Ablageordner")
            default = not meta.get("requires_admin") and not meta.get("sensitive")
            self._add(cid, meta.get("name", cid), meta.get("description", ""),
                      f"{n} Dateien · {human_size(s)}", ok, self._previous(cid, default), tags, reason)
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
        cats = self._checked()
        if cats != self.state.categories:
            self.state.plan = None
        self.state.categories = cats
        if self.state.mode == Mode.SYNC and self.state.profile.sync_categories != cats:
            self.state.profile.sync_categories = cats
            try:
                self.state.profile.save()
            except OSError:
                pass
        return True

    def cleanupPage(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()
