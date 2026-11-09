"""Hintergrund-Abgleich: Symbol im Infobereich, gleicht in festem Abstand ab."""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .. import APP_NAME
from ..core.background import BackgroundOutcome, append_log, summarize, sync_once
from ..core.reporter import Reporter
from ..core.store import StoreLocked
from ..settings import Profile, config_dir
from .worker import Worker

RETRY_LOCKED = timedelta(minutes=2)


def acquire_single_instance() -> QLockFile | None:
    """Nur ein Hintergrund-Abgleich pro Benutzer. Gibt None zurück, wenn schon einer läuft."""
    config_dir().mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(config_dir() / "hintergrund.lock"))
    lock.setStaleLockTime(0)  # nur über PID prüfen (abgestürzte Prozesse werden erkannt)
    return lock if lock.tryLock(0) else None


class BackgroundSync(QObject):
    """Zeitgesteuerter Abgleich mit optionalem Tray-Symbol."""

    finished = Signal(object)  # BackgroundOutcome | str (Fehler)

    def __init__(self, parent=None, sync_fn=sync_once, show_tray: bool = True, plugin_check_fn=None):
        super().__init__(parent)
        self._sync_fn = sync_fn
        self._plugin_check_fn = plugin_check_fn
        self._plugin_worker: Worker | None = None
        self.plugin_updates: list = []
        self.worker: Worker | None = None
        self.last: str = "noch nicht abgeglichen"
        self.paused = False
        self.profile = Profile.load()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.sync_now)
        self._apply_interval()

        self.tray: QSystemTrayIcon | None = None
        if show_tray and QSystemTrayIcon.isSystemTrayAvailable():
            self._make_tray()

    # ------------------------------------------------------------------ Tray
    def _icon(self, busy: bool = False) -> QIcon:
        if busy:
            theme = QIcon.fromTheme("view-refresh")
            return theme if not theme.isNull() else \
                QApplication.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        from ..assets import app_icon
        return app_icon()

    def _make_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._icon(), self)
        menu = QMenu()
        self.a_status = QAction(self.last, menu)
        self.a_status.setEnabled(False)
        a_now = QAction("Jetzt abgleichen", menu)
        a_now.triggered.connect(self.sync_now)
        self.a_pause = QAction("Pausieren", menu, checkable=True)
        self.a_pause.toggled.connect(self.set_paused)
        a_wizard = QAction("Yaleno Wizard öffnen …", menu)
        a_wizard.triggered.connect(self.open_wizard)
        self.a_plugins = QAction("Plugin-Updates installieren …", menu)
        self.a_plugins.triggered.connect(self.open_plugins)
        self.a_plugins.setVisible(False)
        a_quit = QAction("Hintergrund-Abgleich beenden", menu)
        a_quit.triggered.connect(self.quit)
        for a in (self.a_status, None, a_now, self.a_pause, a_wizard, self.a_plugins, None, a_quit):
            menu.addSeparator() if a is None else menu.addAction(a)
        self._menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(
            lambda reason: self.open_wizard() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        self._update_tooltip()
        self.tray.show()

    def _update_tooltip(self) -> None:
        if self.tray is None:
            return
        state = "pausiert" if self.paused else f"alle {self.profile.bg_interval} min"
        self.tray.setToolTip(f"{APP_NAME} – Hintergrund-Abgleich ({state})\n{self.last}")
        self.a_status.setText(self.last)

    def _notify(self, title: str, msg: str, warn: bool = False) -> None:
        if self.tray is not None:
            icon = QSystemTrayIcon.MessageIcon.Warning if warn else QSystemTrayIcon.MessageIcon.Information
            self.tray.showMessage(title, msg, icon, 10000)

    # ------------------------------------------------------------------ Ablauf
    def _apply_interval(self) -> None:
        self.timer.start(max(1, self.profile.bg_interval) * 60 * 1000)

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        self._update_tooltip()

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def sync_now(self, automatic: bool = False) -> None:
        automatic = automatic or self.sender() is self.timer
        if self.running or (self.paused and automatic):
            return
        # Einstellungen können sich im Wizard geändert haben
        self.profile = Profile.load()
        if automatic and not self.profile.bg_enabled:
            append_log(["Hintergrund-Abgleich wurde in den Einstellungen ausgeschaltet – beende."])
            self.quit()
            return
        self._apply_interval()
        if self.tray is not None:
            self.tray.setIcon(self._icon(busy=True))
        profile, fn = self.profile, self._sync_fn

        def job(rep: Reporter) -> BackgroundOutcome | StoreLocked:
            try:
                return fn(profile, rep)
            except StoreLocked as exc:  # anderes Gerät gleicht gerade ab → gleich nochmal
                return exc

        self.worker = Worker(job, self)
        self.worker.succeeded.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()

    def _done(self, out) -> None:
        if isinstance(out, StoreLocked):
            self.last = f"{datetime.now():%H:%M}: {out} – neuer Versuch in 2 min"
            QTimer.singleShot(int(RETRY_LOCKED.total_seconds() * 1000), lambda: self.sync_now(automatic=True))
            self._finish()
            self.finished.emit(str(out))
            return
        res = out.result
        append_log(self.worker.reporter.lines if self.worker else [])
        self.last = f"Zuletzt {out.started:%H:%M}: {summarize(res)}"
        if res.conflicts:
            self._notify(APP_NAME, f"{res.conflicts} Konflikte beim Abgleich – die andere Fassung liegt "
                                   "jeweils als „(Konflikt …)“-Kopie daneben.")
        if res.failed:
            self._notify(APP_NAME, f"{len(res.failed)} Dateien konnten nicht abgeglichen werden "
                                   "(Details im Log).", warn=True)
        self._finish()
        self.finished.emit(out)

    def _failed(self, msg: str) -> None:
        lines = self.worker.reporter.lines if self.worker else []
        append_log(lines + [f"FEHLER: {msg}"])
        self.last = f"Fehler {datetime.now():%H:%M}: {msg}"
        self._notify(f"{APP_NAME} – Abgleich fehlgeschlagen", msg, warn=True)
        self._finish()
        self.finished.emit(msg)

    def _finish(self) -> None:
        if self.tray is not None:
            self.tray.setIcon(self._icon())
        self._update_tooltip()
        self.check_plugin_updates()

    # ------------------------------------------------------------------ Plugin-Updates
    def check_plugin_updates(self, force: bool = False) -> None:
        """Höchstens einmal am Tag nach Plugin-Updates suchen (im Hintergrund)."""
        from ..plugins import manager
        if self._plugin_worker is not None and self._plugin_worker.isRunning():
            return
        if not force and not manager.update_due(self.profile):
            return
        fn = self._plugin_check_fn or manager.check_updates
        profile = self.profile
        self._plugin_worker = Worker(lambda _rep: fn(profile), self)
        self._plugin_worker.succeeded.connect(self._plugins_checked)
        self._plugin_worker.failed.connect(lambda msg: append_log([f"Plugin-Updates: {msg}"]))
        self._plugin_worker.start()

    def _plugins_checked(self, res) -> None:
        self.plugin_updates = list(res.updates)
        if res.errors:
            append_log([f"Plugin-Updates: {e}" for e in res.errors])
        if self.tray is not None:
            self.a_plugins.setVisible(bool(self.plugin_updates))
        if self.plugin_updates:
            names = ", ".join(f"{u.current.name} {u.pending.plugin.version}" for u in self.plugin_updates)
            self._notify("Plugin-Updates verfügbar", f"{names} – im Menü „Plugin-Updates installieren …“.")

    def open_plugins(self) -> None:
        from .plugin_dialog import PluginDialog
        dlg = PluginDialog(Profile.load())
        dlg.updates = {u.id: u for u in self.plugin_updates}
        dlg.reload()
        dlg.exec()
        self.plugin_updates = [u for u in self.plugin_updates if u.id in dlg.updates]
        if self.tray is not None:
            self.a_plugins.setVisible(bool(self.plugin_updates))

    def open_wizard(self) -> None:
        from .wizard import YalenoWizard
        if getattr(self, "_wizard", None) is not None and self._wizard.isVisible():
            self._wizard.raise_()
            self._wizard.activateWindow()
            return
        self._wizard = YalenoWizard()
        self._wizard.show()

    def quit(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(30000)
        if self._plugin_worker is not None and self._plugin_worker.isRunning():
            self._plugin_worker.wait(30000)
        QApplication.quit()


def run_background(app: QApplication) -> int:
    lock = acquire_single_instance()
    if lock is None:
        print("Der Hintergrund-Abgleich läuft bereits.")
        return 0
    if not Profile.load().bg_enabled:
        msg = "Der Hintergrund-Abgleich ist ausgeschaltet – im Wizard unter „Hintergrund-Abgleich …“ aktivieren."
        print(msg)
        lock.unlock()
        if QSystemTrayIcon.isSystemTrayAvailable():  # von Hand gestartet (Startmenü) → Hinweis zeigen
            from PySide6.QtWidgets import QMessageBox
            box = QMessageBox(QMessageBox.Icon.Information, APP_NAME, msg)
            open_btn = box.addButton("Wizard öffnen", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Close)
            box.exec()
            if box.clickedButton() is open_btn:
                from .wizard import YalenoWizard
                w = YalenoWizard()
                w.show()
                return app.exec()
        return 0
    app.setQuitOnLastWindowClosed(False)
    bg = BackgroundSync()
    if bg.tray is None:
        print("Kein Infobereich verfügbar – Hintergrund-Abgleich läuft ohne Symbol.")
    QTimer.singleShot(5000, lambda: bg.sync_now(automatic=True))  # kurz nach dem Start einmal abgleichen
    code = app.exec()
    lock.unlock()
    return code
