"""Anmeldung im Browser (Nextcloud Login Flow, OIDC) mit Warte-Fenster und Abbrechen."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QEventLoop
from PySide6.QtWidgets import QProgressDialog, QWidget

from ..core.reporter import Reporter
from .worker import Worker


class Cancelled(Exception):
    pass


def run_waiting(parent: QWidget | None, title: str, text: str, fn: Callable[[Reporter], Any]) -> Any:
    """Führt ``fn`` im Hintergrund aus und zeigt solange ein Fenster mit „Abbrechen“.

    Gibt das Ergebnis zurück; Fehler kommen als ``RuntimeError``, Abbruch als ``Cancelled``.
    """
    dlg = QProgressDialog(text, "Abbrechen", 0, 0, parent)
    dlg.setWindowTitle(title)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    worker = Worker(fn, parent)
    out: dict[str, Any] = {}
    worker.succeeded.connect(lambda r: out.setdefault("ok", r))
    worker.failed.connect(lambda m: out.setdefault("err", m))
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    dlg.canceled.connect(worker.cancel)
    dlg.show()
    worker.start()
    loop.exec()  # endet über worker.finished (in der Warteschlange nach succeeded/failed)
    worker.wait()
    dlg.close()
    if "ok" in out:
        return out["ok"]
    if worker.reporter.cancelled():
        raise Cancelled()
    raise RuntimeError(out.get("err", "unbekannter Fehler"))
