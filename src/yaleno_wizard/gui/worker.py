"""Hintergrund-Ausführung langer Aufgaben (Scan, Sicherung, Wiederherstellung)."""

from __future__ import annotations

import time
import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from ..core.reporter import Reporter


class Worker(QThread):
    progress = Signal(object, object, str)   # done, total (object: > 2^31 möglich), aktuelles Element
    log = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Reporter], Any], parent=None):
        super().__init__(parent)
        self._fn = fn
        self._last = 0.0
        self.reporter = Reporter(on_progress=self._on_progress, on_log=self.log.emit)

    def _on_progress(self, done: int, total: int, current: str) -> None:
        now = time.monotonic()
        if now - self._last >= 0.05 or done >= total:
            self._last = now
            self.progress.emit(done, total, current)

    def cancel(self) -> None:
        self.reporter.cancel()

    def run(self) -> None:
        try:
            result = self._fn(self.reporter)
        except Exception as exc:  # an die GUI melden statt abzustürzen
            self.log.emit(traceback.format_exc())
            self.failed.emit(str(exc) or exc.__class__.__name__)
            return
        self.succeeded.emit(result)
