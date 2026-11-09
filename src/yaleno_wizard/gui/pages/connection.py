"""Seite 1: Verbindung zum Basis-Storage (SFTP mit SSH-Key oder lokaler Ordner)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget, QWizardPage,
)

from ...core.manifest import list_snapshots
from ...settings import known_hosts_file
from ...storage.base import StorageError
from ...storage.local import LocalStorage
from ...storage.sftp import ConnectionSettings, KeyPassphraseRequired, SFTPStorage
from ..state import WizardState


class ConnectionPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Basis-Speicher verbinden")
        self.setSubTitle("Wohin wird gesichert bzw. woher wird wiederhergestellt? "
                         "Empfohlen: ein SFTP-Server mit Anmeldung per SSH-Key.")

        p = state.profile
        self.rb_sftp = QRadioButton("SFTP-Server (SSH-Key)")
        self.rb_local = QRadioButton("Lokaler Ordner (z. B. USB-Festplatte, Netzlaufwerk)")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_sftp)
        grp.addButton(self.rb_local)
        is_local = p.storage_type == "local"
        (self.rb_local if is_local else self.rb_sftp).setChecked(True)

        # --- SFTP
        self.host = QLineEdit(p.host)
        self.host.setPlaceholderText("backup.example.org oder 192.168.1.10")
        self.port = QSpinBox()
        self.port.setRange(1, 65535)
        self.port.setValue(p.port or 22)
        self.user = QLineEdit(p.username)
        self.key = QLineEdit(p.key_path or self._default_key())
        key_btn = QPushButton("Durchsuchen…")
        key_btn.clicked.connect(self._pick_key)
        self.pub_btn = QPushButton("Öffentlichen Schlüssel kopieren")
        self.pub_btn.setToolTip("Kopiert den Inhalt der .pub-Datei, um ihn auf dem Server in "
                                "~/.ssh/authorized_keys einzutragen.")
        self.pub_btn.clicked.connect(self._copy_pub)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key, 1)
        key_row.addWidget(key_btn)
        self.passphrase = QLineEdit()
        self.passphrase.setEchoMode(QLineEdit.EchoMode.Password)
        self.passphrase.setPlaceholderText("nur falls der Key geschützt ist – wird nicht gespeichert")
        self.remote_base = QLineEdit(p.base_path or ".")
        self.remote_base.setPlaceholderText(". (Home-Verzeichnis auf dem Server) oder /srv/backup")

        self.sftp_box = QWidget()
        form = QFormLayout(self.sftp_box)
        form.addRow("Server:", self.host)
        form.addRow("Port:", self.port)
        form.addRow("Benutzer:", self.user)
        form.addRow("SSH-Key (privat):", key_row)
        form.addRow("", self.pub_btn)
        form.addRow("Passphrase:", self.passphrase)
        form.addRow("Ordner auf dem Server:", self.remote_base)

        # --- Lokal
        self.local_dir = QLineEdit(p.local_dir)
        dir_btn = QPushButton("Durchsuchen…")
        dir_btn.clicked.connect(self._pick_dir)
        self.local_box = QWidget()
        lrow = QHBoxLayout(self.local_box)
        lrow.setContentsMargins(0, 0, 0, 0)
        lrow.addWidget(QLabel("Ordner:"))
        lrow.addWidget(self.local_dir, 1)
        lrow.addWidget(dir_btn)

        self.test_btn = QPushButton("Verbindung testen")
        self.test_btn.clicked.connect(self._test)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        lay = QVBoxLayout(self)
        lay.addWidget(self.rb_sftp)
        lay.addWidget(self.sftp_box)
        lay.addWidget(self.rb_local)
        lay.addWidget(self.local_box)
        row = QHBoxLayout()
        row.addWidget(self.test_btn)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.status)
        lay.addStretch(1)

        for w in (self.host, self.user, self.key, self.local_dir):
            w.textChanged.connect(self.completeChanged)
        self.key.textChanged.connect(self._update_pub)
        self.rb_sftp.toggled.connect(self._update_mode)
        self._update_mode()
        self._update_pub()

    # ------------------------------------------------------------------ ui
    @staticmethod
    def _default_key() -> str:
        for name in ("id_ed25519", "id_ecdsa", "id_rsa"):
            p = Path.home() / ".ssh" / name
            if p.exists():
                return str(p)
        return ""

    def _update_mode(self) -> None:
        self.sftp_box.setEnabled(self.rb_sftp.isChecked())
        self.local_box.setEnabled(self.rb_local.isChecked())
        self.completeChanged.emit()

    def _update_pub(self) -> None:
        self.pub_btn.setEnabled(Path(self.key.text().strip() + ".pub").expanduser().is_file())

    def _pick_key(self) -> None:
        start = self.key.text() or str(Path.home() / ".ssh")
        path, _ = QFileDialog.getOpenFileName(self, "Privaten SSH-Key wählen", start)
        if path:
            self.key.setText(path)

    def _pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Sicherungsordner wählen", self.local_dir.text())
        if path:
            self.local_dir.setText(path)

    def _copy_pub(self) -> None:
        pub = Path(self.key.text().strip() + ".pub").expanduser()
        QGuiApplication.clipboard().setText(pub.read_text().strip())
        self.status.setText(f"Öffentlicher Schlüssel aus {pub} kopiert. Auf dem Server an "
                            "~/.ssh/authorized_keys anhängen.")

    def isComplete(self) -> bool:
        if self.rb_local.isChecked():
            return bool(self.local_dir.text().strip())
        return all(w.text().strip() for w in (self.host, self.user, self.key))

    # ------------------------------------------------------------------ verbinden
    def _key(self) -> tuple:
        if self.rb_local.isChecked():
            return ("local", self.local_dir.text().strip())
        return ("sftp", self.host.text().strip(), self.port.value(), self.user.text().strip(),
                self.key.text().strip(), self.remote_base.text().strip() or ".")

    def _confirm_host_key(self, host: str, key_type: str, fp: str) -> bool:
        return QMessageBox.question(
            self, "Unbekannter Server",
            f"Der Server {host} ist noch nicht bekannt.\n\nSchlüsseltyp: {key_type}\n"
            f"Fingerprint: {fp}\n\nStimmt dieser Fingerprint mit dem des Servers überein? "
            "(Auf dem Server prüfen mit: ssh-keygen -lf /etc/ssh/ssh_host_*_key.pub)\n\n"
            "Server vertrauen und fortfahren?",
        ) == QMessageBox.StandardButton.Yes

    def _connect(self) -> bool:
        key = self._key()
        if self.state.storage is not None and self.state.storage_key == key:
            return True
        self.state.close_storage()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if key[0] == "local":
                storage = LocalStorage(key[1])
                base = "."
            else:
                _, host, port, user, key_path, base = key
                settings = ConnectionSettings(host, port, user, key_path, base)
                storage = SFTPStorage.connect(
                    settings, known_hosts_file(), self._confirm_host_key,
                    passphrase=self.passphrase.text() or None,
                )
                if not storage.is_dir(base):
                    storage.close()
                    raise StorageError(f"Der Ordner '{base}' existiert auf dem Server nicht.")
            n = len(list_snapshots(storage, base))
        except KeyPassphraseRequired as exc:
            QApplication.restoreOverrideCursor()
            self.status.setText(f"⚠ {exc} Bitte Passphrase eingeben.")
            self.passphrase.setFocus()
            return False
        except (StorageError, OSError) as exc:
            QApplication.restoreOverrideCursor()
            self.status.setText(f"⚠ {exc}")
            return False
        QApplication.restoreOverrideCursor()

        self.state.storage = storage
        self.state.storage_key = key
        self.state.base_path = base
        self.status.setText(f"✔ Verbunden mit {storage.description}. Vorhandene Sicherungen: {n}")

        prof = self.state.profile
        if key[0] == "local":
            prof.storage_type, prof.local_dir = "local", key[1]
        else:
            prof.storage_type = "sftp"
            prof.host, prof.port, prof.username, prof.key_path, prof.base_path = key[1:]
        try:
            prof.save()
        except OSError:
            pass
        return True

    def _test(self) -> None:
        self._connect()

    def validatePage(self) -> bool:
        return self._connect()
