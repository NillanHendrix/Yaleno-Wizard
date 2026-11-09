"""Verschlüsselten Speicher entsperren: Passwort, Wiederherstellungsschlüssel oder Security-Key."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
    QVBoxLayout, QWidget,
)

from ..core.crypto import CryptoError, StoreKeys
from ..core.store import Store
from ..credentials import load_store_key, save_store_key
from ..storage.base import StorageError


class UnlockDialog(QDialog):
    def __init__(self, store: Store, parent=None):
        super().__init__(parent)
        self.store = store
        self.keys: StoreKeys | None = None
        self.setWindowTitle("Speicher entsperren")
        info = store.encryption
        types = {s.type for s in info.slots} if info else set()

        intro = QLabel("Der Speicher ist Ende-zu-Ende verschlüsselt. Zum Öffnen brauchst du dein Passwort, "
                       "den Wiederherstellungsschlüssel oder einen eingerichteten Security-Key.")
        intro.setWordWrap(True)
        self.rb_pw = QRadioButton("Passwort")
        self.rb_rec = QRadioButton("Wiederherstellungsschlüssel")
        self.rb_pw.setChecked("password" in types or "recovery" not in types)
        self.rb_rec.setChecked(not self.rb_pw.isChecked())
        self.rb_pw.setEnabled("password" in types)
        self.rb_rec.setEnabled("recovery" in types)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        self.rb_pw.toggled.connect(self._mode)

        self.key_btn = QPushButton("Mit Security-Key / Passkey entsperren …")
        self.key_btn.setVisible("fido2" in types)
        self.key_btn.clicked.connect(self._fido2)

        self.remember = QCheckBox("Auf diesem Gerät merken (nötig für den Hintergrund-Abgleich)")
        self.remember.setChecked(True)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b00020")
        self.error.setWordWrap(True)

        form = QFormLayout()
        form.addRow(self.rb_pw)
        form.addRow(self.rb_rec)
        form.addRow("Eingabe:", self.secret)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Entsperren")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._try)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addLayout(form)
        lay.addWidget(self.key_btn)
        lay.addWidget(self.remember)
        lay.addWidget(self.error)
        lay.addWidget(buttons)
        self.setMinimumWidth(460)
        self._mode()

    def _mode(self) -> None:
        self.secret.setEchoMode(QLineEdit.EchoMode.Password if self.rb_pw.isChecked() else QLineEdit.EchoMode.Normal)
        self.secret.setPlaceholderText("" if self.rb_pw.isChecked() else "XXXX-XXXX-XXXX-…")
        self.secret.setFocus()

    def _done(self, keys: StoreKeys) -> None:
        self.keys = keys
        if self.remember.isChecked():
            try:
                save_store_key(self.store.id, keys.master)
            except OSError as exc:
                self.error.setText(f"Entsperrt, aber nicht gemerkt: {exc}")
        self.accept()

    def _try(self) -> None:
        text = self.secret.text()
        if not text:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            keys = self.store.unlock_password(text) if self.rb_pw.isChecked() else self.store.unlock_recovery(text)
        except (CryptoError, StorageError) as exc:
            self.error.setText(str(exc))
            self.secret.selectAll()
            return
        finally:
            QApplication.restoreOverrideCursor()
        self._done(keys)

    def _fido2(self) -> None:
        from ..security.fido2 import Fido2Error, unlock_store
        self.error.setText("Security-Key berühren bzw. bestätigen …")
        QApplication.processEvents()
        try:
            keys = unlock_store(self.store)
        except (Fido2Error, CryptoError, StorageError) as exc:
            self.error.setText(str(exc))
            return
        self._done(keys)


def unlock_store(parent: QWidget, store: Store) -> bool:
    """Entsperrt ``store`` – zuerst mit dem gemerkten Schlüssel, sonst per Dialog. True bei Erfolg."""
    if not store.encrypted or store.unlocked:
        return True
    cached = load_store_key(store.id)
    if cached is not None:
        try:
            store.unlock(cached)
            return True
        except CryptoError:
            pass  # veraltet → neu fragen
    return UnlockDialog(store, parent).exec() == QDialog.DialogCode.Accepted
