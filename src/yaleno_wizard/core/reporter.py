"""Schnittstelle für Fortschritt, Log und Abbruch (GUI-unabhängig)."""

from __future__ import annotations

import threading
from typing import Callable


class Reporter:
    def __init__(
        self,
        on_progress: Callable[[int, int, str], None] | None = None,
        on_log: Callable[[str], None] | None = None,
    ):
        self._on_progress = on_progress
        self._on_log = on_log
        self._cancel = threading.Event()
        self.lines: list[str] = []

    def progress(self, done: int, total: int, current: str = "") -> None:
        if self._on_progress:
            self._on_progress(done, total, current)

    def log(self, msg: str) -> None:
        self.lines.append(msg)
        if self._on_log:
            self._on_log(msg)

    def cancel(self) -> None:
        self._cancel.set()

    def cancelled(self) -> bool:
        return self._cancel.is_set()
