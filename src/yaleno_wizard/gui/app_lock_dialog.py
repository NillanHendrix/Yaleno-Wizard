"""App-Sperre: Entsperren beim Start und Einstellungen."""

from __future__ import annotations

import time

from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from ..security import app_lock, fido2
from ..settings import Profile


def gui_backend(parent: QWidget | None, status: QLabel | None = None) -> fido2.Fido2Backend:
    """FIDO2-Backend mit PIN-Abfrage und Hinweisen im Fenster."""
    be = fido2.backend()
    if isinstance(be, fido2.HardwareBackend):
        def ask_pin() -> str | None:
            pin, ok = QInputDialog.getText(parent, "Security-Key", "PIN des Security-Keys:",
                                           QLineEdit.EchoMode.Password)
            return pin if ok and pin else None

        def prompt(msg: str) -> None:
            if status is not None:
                status.setText(msg)
            QApplication.processEvents()
        be.ask_pin, be.prompt = ask_pin, prompt
    return be


class AppUnlockDialog(QDialog):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.failures = 0
        self.setWindowTitle("Yaleno Wizard – gesperrt")
        intro = QLabel("🔒 Der Yaleno Wizard ist gesperrt.")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.pw.setPlaceholderText("Passwort")
        self.pw.setVisible(bool(profile.app_lock_password))
        self.key_btn = QPushButton("Mit Security-Key / Passkey entsperren …")
        self.key_btn.setVisible(bool(profile.app_lock_keys))
        self.key_btn.clicked.connect(self._key)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b00020")
        self.error.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Entsperren")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setVisible(bool(profile.app_lock_password))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Beenden")
        buttons.accepted.connect(self._try)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.pw)
        lay.addWidget(self.key_btn)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self.setMinimumWidth(380)

    def _fail(self, msg: str) -> None:
        self.failures += 1
        self.error.setText(msg)
        if self.failures >= 3:  # Raten bremsen
            QApplication.processEvents()
            time.sleep(min(10, 2 ** (self.failures - 3)))

    def _try(self) -> None:
        if app_lock.check_password(self.profile.app_lock_password, self.pw.text()):
            self.accept()
        else:
            self.pw.selectAll()
            self._fail("Falsches Passwort.")

    def _key(self) -> None:
        self.error.setText("Security-Key berühren bzw. bestätigen …")
        QApplication.processEvents()
        try:
            ok = app_lock.unlock_with_key(self.profile, gui_backend(self, self.error))
        except (fido2.Fido2Error, app_lock.AppLockError) as exc:
            self._fail(str(exc))
            return
        if ok:
            self.accept()
        else:
            self._fail("Dieser Security-Key ist nicht eingerichtet.")


def ensure_app_unlocked(profile: Profile | None = None, parent=None) -> bool:
    profile = profile or Profile.load()
    if not app_lock.active(profile):
        return True
    return AppUnlockDialog(profile, parent).exec() == QDialog.DialogCode.Accepted


class AppLockSettingsDialog(QDialog):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("App-Sperre")
        intro = QLabel("Fragt beim Öffnen des Wizards nach einem Passwort oder Security-Key/Passkey. Das schützt "
                       "die Bedienung – nicht die Dateien auf der Festplatte (dafür: Verschlüsselung).")
        intro.setWordWrap(True)
        self.enabled = QCheckBox("App-Sperre aktivieren")
        self.enabled.setChecked(profile.app_lock_enabled)
        self.enabled.toggled.connect(self._toggle)
        self.pw_label = QLabel()
        pw_btn = QPushButton("Passwort festlegen …")
        pw_btn.clicked.connect(self._set_pw)
        self.pw_clear = QPushButton("Passwort entfernen")
        self.pw_clear.clicked.connect(self._clear_pw)
        row = QHBoxLayout()
        row.addWidget(self.pw_label, 1)
        row.addWidget(pw_btn)
        row.addWidget(self.pw_clear)
        self.keys = QListWidget()
        add = QPushButton("Security-Key / Passkey hinzufügen …")
        add.clicked.connect(self._add_key)
        rm = QPushButton("Entfernen")
        rm.clicked.connect(self._remove_key)
        krow = QHBoxLayout()
        krow.addWidget(add)
        krow.addWidget(rm)
        krow.addStretch(1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: gray")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.enabled)
        lay.addLayout(row)
        lay.addWidget(QLabel("Security-Keys / Passkeys:"))
        lay.addWidget(self.keys, 1)
        lay.addLayout(krow)
        lay.addWidget(self.status)
        lay.addWidget(buttons)
        self.resize(520, 380)
        self.refresh()

    def refresh(self) -> None:
        p = self.profile
        self.pw_label.setText("Passwort: gesetzt" if p.app_lock_password else "Passwort: keins")
        self.pw_clear.setEnabled(bool(p.app_lock_password))
        self.keys.clear()
        for k in p.app_lock_keys:
            self.keys.addItem(k.get("label") or "Security-Key")
        self.enabled.blockSignals(True)
        self.enabled.setChecked(p.app_lock_enabled)
        self.enabled.blockSignals(False)

    def _toggle(self, on: bool) -> None:
        try:
            app_lock.set_enabled(self.profile, on)
        except app_lock.AppLockError as exc:
            QMessageBox.information(self, "App-Sperre", str(exc))
        self.refresh()

    def _set_pw(self) -> None:
        pw, ok = QInputDialog.getText(self, "App-Sperre", "Neues Passwort (mind. 6 Zeichen):",
                                      QLineEdit.EchoMode.Password)
        if not ok or not pw:
            return
        again, ok = QInputDialog.getText(self, "App-Sperre", "Passwort wiederholen:", QLineEdit.EchoMode.Password)
        if not ok:
            return
        if pw != again:
            QMessageBox.warning(self, "App-Sperre", "Die Passwörter stimmen nicht überein.")
            return
        try:
            app_lock.set_password(self.profile, pw)
        except app_lock.AppLockError as exc:
            QMessageBox.warning(self, "App-Sperre", str(exc))
            return
        self.status.setText("Passwort gespeichert (nur als Hash).")
        self.refresh()

    def _clear_pw(self) -> None:
        app_lock.set_password(self.profile, None)
        if not self.profile.app_lock_keys:
            app_lock.set_enabled(self.profile, False)
        self.refresh()

    def _add_key(self) -> None:
        label, ok = QInputDialog.getText(self, "Security-Key", "Bezeichnung:", text="Security-Key")
        if not ok:
            return
        self.status.setText("Security-Key berühren bzw. bestätigen …")
        QApplication.processEvents()
        try:
            app_lock.add_key(self.profile, label or "Security-Key", gui_backend(self, self.status))
        except fido2.Fido2Error as exc:
            QMessageBox.warning(self, "Security-Key", str(exc))
            self.status.setText("")
            return
        self.status.setText("Security-Key hinzugefügt.")
        self.refresh()

    def _remove_key(self) -> None:
        row = self.keys.currentRow()
        if row >= 0:
            app_lock.remove_key(self.profile, row)
            self.refresh()
