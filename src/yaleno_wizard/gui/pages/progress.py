"""Seite 7: Ausführung mit Fortschritt und Log."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout, QWizardPage,
)

from ...core.entry import human_size
from ...core.restore import ActionKind, RestoreResult, run_restore
from ...core.store import Revision
from ...core.sync import SyncResult, plan_sync, run_sync
from ...settings import log_dir
from ..state import WizardState
from ..worker import Worker
from .summary import SummaryPage


class ProgressPage(QWizardPage):
    def __init__(self, state: WizardState, summary: SummaryPage):
        super().__init__()
        self.state = state
        self.summary = summary
        self.setTitle("Wird ausgeführt …")
        self.worker: Worker | None = None
        self._done = False

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.current = QLabel()
        self.current.setWordWrap(True)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.log.setMaximumBlockCount(20000)
        self.cancel_btn = QPushButton("Abbrechen")
        self.cancel_btn.clicked.connect(self.cancel)
        self.result = QLabel()
        self.result.setWordWrap(True)

        row = QHBoxLayout()
        row.addWidget(self.current, 1)
        row.addWidget(self.cancel_btn)
        lay = QVBoxLayout(self)
        lay.addWidget(self.bar)
        lay.addLayout(row)
        lay.addWidget(self.log, 1)
        lay.addWidget(self.result)

    def isComplete(self) -> bool:
        return self._done

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def cancel(self) -> None:
        if self.worker and self.worker.isRunning():
            self.cancel_btn.setEnabled(False)
            self.current.setText("Breche ab …")
            self.worker.cancel()

    def initializePage(self) -> None:
        self._done = False
        self.log.clear()
        self.result.clear()
        self.bar.setValue(0)
        self.cancel_btn.setEnabled(True)
        s = self.state
        store = s.store
        assert store is not None
        kind = self.summary.kind

        if kind == "sync":
            self.setTitle("Abgleich läuft …")
            winner, dry = self.summary.sync_options()
            plan, st = s.plan, s.sync_state
            assert plan is not None and st is not None
            entries, cats, selected = s.scan.entries if s.scan else [], set(s.categories), s.selected

            def job(rep):
                def replan():
                    return plan_sync(store, entries, st, s.catalog, s.mapper, s.os_name, s.host_name,
                                     cats, selected, reporter=rep)
                return run_sync(store, plan, st, s.catalog, s.mapper, s.os_name, s.host_name, winner, rep,
                                dry_run=dry, replan=replan)
        elif kind == "reset":
            self.setTitle("Speicher wird zurückgesetzt …")
            rev = s.revision
            assert rev is not None

            def job(rep):
                with store.locked(s.host_name):
                    rep.log(f"Setze Speicher auf Version {rev.number} …")
                    new = store.revert_to(rev.number, s.host_name, s.os_name)
                    rep.log(f"Neue Version {new.number}: {new.info.message}")
                    return new
        else:
            self.setTitle("Wiederherstellung läuft …")
            policy, dry = self.summary.options()
            actions = self.summary.actions
            rev = s.revision
            assert rev is not None

            def job(rep):
                return run_restore(store, rev, actions, s.catalog, policy, rep, dry_run=dry)

        self.worker = Worker(job, self)
        self.worker.progress.connect(self._progress)
        self.worker.log.connect(self.log.appendPlainText)
        self.worker.succeeded.connect(self._finished)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _progress(self, done: int, total: int, current: str) -> None:
        self.bar.setValue(int(done * 1000 / total) if total else 0)
        self.current.setText(f"{current}   ({human_size(done)} / {human_size(total)})")

    def _finish_common(self) -> None:
        self._done = True
        self.cancel_btn.setEnabled(False)
        # Nach einer Aktion ist der Stand veraltet – bei „Neue Aktion“ wird neu gelesen.
        self.state.plan = None
        try:
            d = log_dir()
            d.mkdir(parents=True, exist_ok=True)
            f = d / f"{self.summary.kind}-{datetime.now():%Y-%m-%d_%H%M%S}.log"
            f.write_text(self.log.toPlainText(), encoding="utf-8")
            self.log.appendPlainText(f"\nLog gespeichert: {f}")
        except OSError:
            pass
        self.completeChanged.emit()

    def _finished(self, res) -> None:
        self.bar.setValue(1000)
        fails: list = []
        if isinstance(res, SyncResult):
            self.setTitle("Abgleich abgebrochen" if res.cancelled else "Abgleich abgeschlossen")
            msg = (f"✔ {res.uploaded} hochgeladen, {res.downloaded} heruntergeladen, "
                   f"{res.deleted_remote + res.deleted_local} gelöscht, {res.conflicts} Konflikte"
                   f" · Speicher-Version {res.revision}")
            if res.cancelled:
                msg = "Abgebrochen – erledigte Änderungen wurden übernommen, der Rest folgt beim nächsten Abgleich."
            fails = res.failed
        elif isinstance(res, Revision):
            self.setTitle("Speicher zurückgesetzt")
            msg = (f"✔ Aktueller Stand ist jetzt Version {res.number} ({res.info.message}). "
                   "Die Geräte übernehmen ihn beim nächsten Abgleich.")
        else:
            assert isinstance(res, RestoreResult)
            self.setTitle("Wiederherstellung abgebrochen" if res.cancelled else "Wiederherstellung abgeschlossen")
            msg = (f"{res.written} geschrieben, {res.unchanged} unverändert, {res.skipped} übersprungen"
                   + (f", {res.commands} Befehle" if res.commands else ""))
            if any(a.kind == ActionKind.STAGING for a in self.summary.actions):
                msg += f"<br>Ablageordner: {self.summary.staging.text()}"
            fails = res.failed
        if fails:
            msg += f"<br><b>{len(fails)} Fehler</b> – Details im Log."
        self.result.setText(msg)
        self.current.clear()
        self._finish_common()

    def _failed(self, msg: str) -> None:
        self.setTitle("Fehler")
        self.result.setText(f"⚠ {msg}")
        self._finish_common()
