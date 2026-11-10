"""Verschlüsselung des Speichers einschalten und Schlüsselplätze verwalten."""

from __future__ import annotations

from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from ..core import encryption
from ..core.crypto import CryptoError
from ..core.store import Store
from ..credentials import delete_store_key, load_store_key, save_store_key
from ..storage.base import StorageError
from .worker import Worker


def show_recovery_code(parent: QWidget, code: str) -> None:
    """Zeigt den Wiederherstellungsschlüssel – erst schließbar, wenn bestätigt wurde, dass er notiert ist."""
    dlg = QDialog(parent)
    dlg.setWindowTitle("Wiederherstellungsschlüssel")
    text = QLabel("Schreib diesen Schlüssel auf oder drucke ihn aus und bewahre ihn sicher auf. Er öffnet den "
                  "Speicher, falls du dein Passwort vergisst. <b>Ohne Passwort und ohne diesen Schlüssel sind "
                  "deine Daten verloren</b> – niemand kann sie wiederherstellen.")
    text.setWordWrap(True)
    field = QLineEdit(code)
    field.setReadOnly(True)
    mono = QFont("monospace")
    mono.setStyleHint(QFont.StyleHint.Monospace)
    mono.setPointSize(mono.pointSize() + 2)
    field.setFont(mono)
    copy = QPushButton("Kopieren")
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(code))
    row = QHBoxLayout()
    row.addWidget(field, 1)
    row.addWidget(copy)
    ok = QCheckBox("Ich habe den Schlüssel sicher notiert.")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
    btn.setEnabled(False)
    ok.toggled.connect(btn.setEnabled)
    buttons.accepted.connect(dlg.accept)
    lay = QVBoxLayout(dlg)
    lay.addWidget(text)
    lay.addLayout(row)
    lay.addWidget(ok)
    lay.addWidget(buttons)
    dlg.setMinimumWidth(620)
    dlg.reject = lambda: None  # nicht per Esc/Fenster schließen, solange nicht bestätigt
    dlg.exec()


def ask_new_password(parent: QWidget, title: str) -> str | None:
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    pw1, pw2 = QLineEdit(), QLineEdit()
    for f in (pw1, pw2):
        f.setEchoMode(QLineEdit.EchoMode.Password)
    err = QLabel()
    err.setStyleSheet("color: #b00020")
    form = QFormLayout(dlg)
    form.addRow("Passwort (mind. 8 Zeichen):", pw1)
    form.addRow("Wiederholen:", pw2)
    form.addRow(err)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    form.addRow(buttons)

    def check() -> None:
        if len(pw1.text()) < 8:
            err.setText("Mindestens 8 Zeichen.")
        elif pw1.text() != pw2.text():
            err.setText("Die Passwörter stimmen nicht überein.")
        else:
            dlg.accept()
    buttons.accepted.connect(check)
    buttons.rejected.connect(dlg.reject)
    return pw1.text() if dlg.exec() == QDialog.DialogCode.Accepted else None


class EncryptionDialog(QDialog):
    def __init__(self, store: Store, host: str, parent=None):
        super().__init__(parent)
        self.store = store
        self.host = host
        self.worker: Worker | None = None
        self.setWindowTitle("Verschlüsselung")

        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.slots = QListWidget()
        self.btn_enable = QPushButton("Speicher jetzt verschlüsseln …")
        self.btn_enable.clicked.connect(self._enable)
        self.btn_pw = QPushButton("Passwort hinzufügen …")
        self.btn_pw.clicked.connect(self._add_password)
        self.btn_rec = QPushButton("Neuer Wiederherstellungsschlüssel …")
        self.btn_rec.clicked.connect(self._add_recovery)
        self.btn_key = QPushButton("Security-Key / Passkey hinzufügen …")
        self.btn_key.clicked.connect(self._add_fido2)
        self.btn_remove = QPushButton("Entfernen")
        self.btn_remove.clicked.connect(self._remove)
        self.remember = QCheckBox("Schlüssel auf diesem Gerät merken (für den Hintergrund-Abgleich)")
        self.remember.toggled.connect(self._remember)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: gray")

        row = QHBoxLayout()
        for b in (self.btn_pw, self.btn_rec, self.btn_key, self.btn_remove):
            row.addWidget(b)
        row.addStretch(1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.buttons.button(QDialogButtonBox.StandardButton.Close).setText("Schließen")
        self.buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.intro)
        lay.addWidget(self.btn_enable)
        lay.addWidget(QLabel("Schlüsselplätze – jeder davon öffnet den Speicher:"))
        lay.addWidget(self.slots, 1)
        lay.addLayout(row)
        lay.addWidget(self.remember)
        lay.addWidget(self.progress)
        lay.addWidget(self.status)
        lay.addWidget(self.buttons)
        self.resize(640, 440)
        self.refresh()

    # ------------------------------------------------------------------ Anzeige
    def refresh(self) -> None:
        enc = self.store.encrypted
        busy = self.worker is not None and self.worker.isRunning()
        if enc:
            self.intro.setText("🔐 Der Speicher ist Ende-zu-Ende verschlüsselt (AES-256-GCM). Inhalte, Dateinamen "
                               "und Versionsverlauf verlassen dieses Gerät nur verschlüsselt.")
        else:
            self.intro.setText("Der Speicher ist <b>nicht</b> verschlüsselt: Wer Zugriff auf den Server hat, kann "
                               "deine Dateien lesen. Beim Verschlüsseln werden alle Inhalte und Versionen einmal "
                               "neu geschrieben; danach brauchen alle Geräte das Passwort oder den "
                               "Wiederherstellungsschlüssel. Ältere Versionen des Wizards können den Speicher "
                               "dann nicht mehr öffnen.")
        self.btn_enable.setVisible(not enc)
        self.btn_enable.setEnabled(not busy)
        for b in (self.btn_pw, self.btn_rec, self.btn_key, self.btn_remove):
            b.setEnabled(enc and self.store.unlocked and not busy)
        self.slots.clear()
        info = self.store.encryption if enc else None
        if info:
            for s in info.slots:
                it = QListWidgetItem(encryption.describe_slot(s))
                it.setData(256, s.id)
                self.slots.addItem(it)
        self.remember.blockSignals(True)
        self.remember.setVisible(enc)
        self.remember.setChecked(bool(enc and load_store_key(self.store.id)))
        self.remember.blockSignals(False)

    # ------------------------------------------------------------------ Aktionen
    def _enable(self) -> None:
        pw = ask_new_password(self, "Passwort für den Speicher")
        if not pw:
            return
        store, host = self.store, self.host
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.status.setText("Verschlüssele … Bitte warten, das kann bei vielen Dateien dauern.")
        self.worker = Worker(lambda rep: encryption.enable_encryption(
            store, host, pw, log=rep.log, progress=rep.progress, cancelled=rep.cancelled), self)

        def on_progress(done, total, current) -> None:
            if total:
                self.progress.setRange(0, 1000)
                self.progress.setValue(int(done * 1000 / total))
            self.status.setText(current)

        def ok(result) -> None:
            keys, code = result
            self.progress.setVisible(False)
            self.status.setText("Fertig – der Speicher ist jetzt verschlüsselt.")
            try:
                save_store_key(store.id, keys.master)
            except OSError:
                pass
            self.refresh()
            show_recovery_code(self, code)

        def fail(msg: str) -> None:
            self.progress.setVisible(False)
            self.status.setText(f"⚠ Nicht verschlüsselt: {msg} – der bisherige Stand ist unverändert.")
            self.refresh()

        self.worker.progress.connect(on_progress)
        self.worker.succeeded.connect(ok)
        self.worker.failed.connect(fail)
        self.worker.start()
        self.refresh()

    def _run_change(self, fn, done_msg: str):
        try:
            result = fn()
        except (CryptoError, StorageError, OSError) as exc:
            QMessageBox.warning(self, "Verschlüsselung", str(exc))
            return None
        self.status.setText(done_msg)
        self.refresh()
        return result

    def _add_password(self) -> None:
        pw = ask_new_password(self, "Weiteres Passwort")
        if not pw:
            return
        label, ok = QInputDialog.getText(self, "Bezeichnung", "Bezeichnung (z. B. für wen/welches Gerät):",
                                         text="Passwort")
        if ok:
            self._run_change(lambda: encryption.add_password(self.store, self.host, pw, label or "Passwort"),
                             "Passwort hinzugefügt.")

    def _add_recovery(self) -> None:
        code = self._run_change(lambda: encryption.add_recovery(self.store, self.host),
                                "Neuer Wiederherstellungsschlüssel angelegt. Alte bleiben gültig, bis du sie entfernst.")
        if code:
            show_recovery_code(self, code)

    def _add_fido2(self) -> None:
        from ..security.fido2 import Fido2Error, add_store_slot
        from .app_lock_dialog import gui_backend
        label, ok = QInputDialog.getText(self, "Security-Key", "Bezeichnung (z. B. „YubiKey blau“):",
                                         text="Security-Key")
        if not ok:
            return
        self.status.setText("Security-Key berühren bzw. bestätigen …")
        try:
            add_store_slot(self.store, self.host, label or "Security-Key", gui_backend(self, self.status))
        except (Fido2Error, CryptoError, StorageError) as exc:
            QMessageBox.warning(self, "Security-Key", str(exc))
            self.status.setText("")
            return
        self.status.setText("Security-Key hinzugefügt.")
        self.refresh()

    def _remove(self) -> None:
        it = self.slots.currentItem()
        if it is None:
            return
        ans = QMessageBox.question(self, "Schlüsselplatz entfernen",
                                   f"„{it.text()}“ entfernen? Damit lässt sich der Speicher nicht mehr öffnen.")
        if ans == QMessageBox.StandardButton.Yes:
            self._run_change(lambda: encryption.remove_slot(self.store, self.host, it.data(256)), "Entfernt.")

    def _remember(self, on: bool) -> None:
        try:
            if on and self.store.keys is not None:
                where = save_store_key(self.store.id, self.store.keys.master)
                self.status.setText("Im Schlüsselbund gemerkt." if where == "keyring"
                                    else "Im Einstellungsordner gemerkt (nur für dich lesbar).")
            elif not on:
                delete_store_key(self.store.id)
                self.status.setText("Vergessen – der Hintergrund-Abgleich kann den Speicher nicht mehr öffnen.")
        except OSError as exc:
            QMessageBox.warning(self, "Verschlüsselung", str(exc))

    def done(self, r: int) -> None:
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "Verschlüsselung", "Bitte warten, bis die Verschlüsselung fertig ist.")
            return
        super().done(r)
