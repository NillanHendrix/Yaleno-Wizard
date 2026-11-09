"""Seite 2: Abgleichen oder im Verlauf springen."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton, QVBoxLayout,
    QWizardPage,
)

from ...core.store import sanitize_host
from ..state import Mode, WizardState


class ModePage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Was möchtest du tun?")
        self.setSubTitle("Der Speicher ist die zentrale Ablage deiner Daten. Jedes Gerät gleicht sich mit "
                         "ihm ab; frühere Stände bleiben im Verlauf erhalten.")

        self.rb_sync = QRadioButton("Abgleichen – Änderungen dieses Geräts hochladen und Änderungen "
                                    "anderer Geräte übernehmen")
        self.rb_history = QRadioButton("Verlauf – zu einem früheren Stand springen oder einzelne Dateien "
                                       "zurückholen")
        self.rb_sync.setChecked(state.mode == Mode.SYNC)
        self.rb_history.setChecked(state.mode == Mode.HISTORY)

        self.name = QLineEdit(state.profile.backup_name or state.host_name)
        self.name.setToolTip("Unter diesem Namen kennt der Speicher dieses Gerät. Gerätebezogene Daten "
                             "(Systemdateien, Paketlisten) werden darunter abgelegt.")
        form = QFormLayout()
        form.addRow("Name dieses Geräts:", self.name)

        os_label = QLabel(f"Betriebssystem: {'Windows' if state.os_name == 'windows' else 'Linux'}")
        os_label.setStyleSheet("color: gray")
        self.store_label = QLabel()
        self.store_label.setStyleSheet("color: gray")
        self.store_label.setWordWrap(True)

        lay = QVBoxLayout(self)
        lay.addWidget(self.rb_sync)
        lay.addWidget(self.rb_history)
        lay.addSpacing(12)
        lay.addLayout(form)
        lay.addWidget(os_label)
        lay.addWidget(self.store_label)
        lay.addStretch(1)
        self.bg_btn = QPushButton("Hintergrund-Abgleich …")
        self.bg_btn.setToolTip("Regelmäßig automatisch abgleichen, mit Symbol im Infobereich.")
        self.bg_btn.clicked.connect(self._background)
        self.bg_label = QLabel()
        self.bg_label.setStyleSheet("color: gray")
        row = QHBoxLayout()
        row.addWidget(self.bg_btn)
        row.addWidget(self.bg_label, 1)
        lay.addLayout(row)
        self.plugin_btn = QPushButton("Plugins …")
        self.plugin_btn.setToolTip("Weitere Programme abgleichen (z. B. Prism Launcher) und Funktionen wie "
                                   "Verschlüsselung freischalten.")
        self.plugin_btn.clicked.connect(self._plugins)
        self.plugin_label = QLabel()
        self.plugin_label.setStyleSheet("color: gray")
        self.plugin_label.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.plugin_btn)
        row.addWidget(self.plugin_label, 1)
        lay.addLayout(row)
        self.enc_btn = QPushButton("Verschlüsselung …")
        self.enc_btn.setToolTip("Speicher Ende-zu-Ende verschlüsseln und Schlüssel verwalten.")
        self.enc_btn.clicked.connect(self._encryption)
        self.enc_label = QLabel()
        self.enc_label.setStyleSheet("color: gray")
        row = QHBoxLayout()
        row.addWidget(self.enc_btn)
        row.addWidget(self.enc_label, 1)
        lay.addLayout(row)

    def _plugins(self) -> None:
        from ..plugin_dialog import open_plugin_dialog
        open_plugin_dialog(self, self.state)
        self._update_plugin_label()
        self._update_enc()

    def _encryption(self) -> None:
        from ..encryption_dialog import EncryptionDialog
        if self.state.store is None:
            return
        host = sanitize_host(self.name.text() or self.state.host_name)
        EncryptionDialog(self.state.store, host, self).exec()
        self.state.reset_run()
        self._update_enc()

    def _update_enc(self) -> None:
        from ...plugins.registry import feature_enabled
        store = self.state.store
        try:
            enc = bool(store and store.encrypted)
        except Exception:
            enc = False
        show = enc or feature_enabled("encryption", self.state.profile)
        self.enc_btn.setVisible(show and store is not None)
        self.enc_label.setVisible(show and store is not None)
        self.enc_label.setText("🔐 verschlüsselt" if enc else "nicht verschlüsselt")

    def _update_plugin_label(self) -> None:
        from ..plugin_dialog import plugin_summary
        self.plugin_label.setText(plugin_summary(self.state))

    def _update_bg_label(self) -> None:
        p = self.state.profile
        self.bg_label.setText(f"aktiv, alle {p.bg_interval} min" if p.bg_enabled else "aus")

    def _background(self) -> None:
        from ... import autostart
        from ..background_dialog import BackgroundDialog
        prof = self.state.profile
        if self.name.text().strip():
            prof.backup_name = sanitize_host(self.name.text())
        dlg = BackgroundDialog(prof, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        was = prof.bg_enabled
        try:
            dlg.apply()
            prof.save()
        except OSError as exc:
            QMessageBox.warning(self, "Hintergrund-Abgleich", f"Konnte nicht gespeichert werden: {exc}")
            return
        self._update_bg_label()
        if prof.bg_enabled and not was:
            try:
                autostart.launch_background()
            except OSError as exc:
                QMessageBox.warning(self, "Hintergrund-Abgleich", f"Konnte nicht gestartet werden: {exc}")
                return
            QMessageBox.information(self, "Hintergrund-Abgleich",
                                    "Der Hintergrund-Abgleich läuft jetzt (Symbol im Infobereich). "
                                    "Du kannst den Wizard schließen.")

    def initializePage(self) -> None:
        self._update_bg_label()
        self._update_plugin_label()
        self._update_enc()
        store = self.state.store
        head = 0
        try:
            head = store.head() if store else 0
        except Exception:
            pass
        self.rb_history.setEnabled(head > 0)
        if head == 0:
            self.rb_sync.setChecked(True)
            self.store_label.setText("Der Speicher ist noch leer – der erste Abgleich legt ihn an.")
        else:
            self.store_label.setText(f"Aktueller Stand im Speicher: Version {head}")

    def validatePage(self) -> bool:
        new_mode = Mode.SYNC if self.rb_sync.isChecked() else Mode.HISTORY
        new_host = sanitize_host(self.name.text() or self.state.host_name)
        if new_mode != self.state.mode or new_host != self.state.host_name:
            self.state.reset_run()
        self.state.mode = new_mode
        self.state.host_name = new_host
        if self.state.profile.backup_name != new_host:
            self.state.profile.backup_name = new_host
            try:
                self.state.profile.save()
            except OSError:
                pass
        return True
