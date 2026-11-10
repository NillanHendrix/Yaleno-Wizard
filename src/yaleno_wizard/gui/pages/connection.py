"""Seite 1: Verbindung zum Speicher (SFTP mit SSH-Key, Nextcloud/WebDAV oder lokaler Ordner)."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFrame, QScrollArea, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QVBoxLayout, QWidget, QWizardPage,
)

from ...core.store import Store
from ...credentials import keyring_available, load_secret, save_secret
from ...settings import ConfigError, Profile, config_file
from ...storage.base import StorageError
from ...storage.connect import open_storage
from ...storage.sftp import KeyPassphraseRequired
from ..state import WizardState


class ConnectionPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Speicher verbinden")
        self.setSubTitle("Der Speicher ist die zentrale Ablage, mit der sich alle deine Geräte abgleichen. "
                         "Möglich sind ein SFTP-Server (SSH-Key), eine Nextcloud bzw. jeder WebDAV-Server "
                         "oder ein Ordner.")

        p = state.profile
        self.rb_sftp = QRadioButton("SFTP-Server (SSH-Key)")
        self.rb_local = QRadioButton("Lokaler Ordner (z. B. Netzlaufwerk, gemeinsamer Cloud-Ordner, USB-Festplatte)")
        self.rb_dav = QRadioButton("Nextcloud / WebDAV")
        grp = QButtonGroup(self)
        grp.addButton(self.rb_sftp)
        grp.addButton(self.rb_dav)
        grp.addButton(self.rb_local)
        {"local": self.rb_local, "webdav": self.rb_dav}.get(p.storage_type, self.rb_sftp).setChecked(True)

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
        self.passphrase.setPlaceholderText("nur falls der Key geschützt ist")
        self.sftp_remember = QCheckBox()
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
        form.addRow("", self.sftp_remember)
        form.addRow("Ordner auf dem Server:", self.remote_base)

        # --- Nextcloud / WebDAV
        self.dav_url = QLineEdit(p.webdav_url)
        self.dav_url.setPlaceholderText("https://cloud.example.org  (Nextcloud) oder vollständige WebDAV-Adresse")
        self.dav_user = QLineEdit(p.webdav_user)
        self.dav_pw = QLineEdit()
        self.dav_pw.setEchoMode(QLineEdit.EchoMode.Password)
        self.dav_pw.setPlaceholderText("App-Passwort aus Nextcloud")
        self.dav_remember = QCheckBox()
        self.dav_folder = QLineEdit(p.webdav_folder or "Yaleno")
        self.dav_folder.setPlaceholderText("Ordner in deinen Dateien, wird bei Bedarf angelegt")
        dav_hint = QLabel("App-Passwort in Nextcloud erstellen: Einstellungen → Sicherheit → "
                          "„Neues App-Passwort erstellen“. Bei Zwei-Faktor-Anmeldung ist das nötig.")
        dav_hint.setWordWrap(True)
        dav_hint.setStyleSheet("color: gray")
        self.dav_hint = dav_hint
        self.dav_auth = QComboBox()
        self.dav_auth.addItem("App-Passwort", "app_password")
        self.dav_auth.addItem("OpenID Connect (OIDC)", "oidc")
        self.dav_auth.setCurrentIndex(max(0, self.dav_auth.findData(p.webdav_auth)))
        self.browser_btn = QPushButton("Im Browser anmelden …")
        self.browser_btn.setToolTip("Anmeldung im Nextcloud-Fenster des Browsers (auch per Passkey oder "
                                    "Zwei-Faktor). Dabei wird automatisch ein App-Passwort angelegt.")
        self.browser_btn.clicked.connect(self._browser_login)
        pw_row = QHBoxLayout()
        pw_row.setContentsMargins(0, 0, 0, 0)
        pw_row.addWidget(self.dav_pw, 1)
        pw_row.addWidget(self.browser_btn)
        self.pw_widget = QWidget()
        self.pw_widget.setLayout(pw_row)
        self.oidc_issuer = QLineEdit(p.oidc_issuer)
        self.oidc_issuer.setPlaceholderText("https://id.example.org/realms/home")
        self.oidc_client = QLineEdit(p.oidc_client_id or "yaleno-wizard")
        self.oidc_btn = QPushButton("Mit OIDC anmelden …")
        self.oidc_btn.clicked.connect(self._oidc_login)
        self.oidc_status = QLabel()
        self.oidc_status.setStyleSheet("color: gray")
        oidc_row = QHBoxLayout()
        oidc_row.setContentsMargins(0, 0, 0, 0)
        oidc_row.addWidget(self.oidc_btn)
        oidc_row.addWidget(self.oidc_status, 1)
        self.oidc_widget = QWidget()
        self.oidc_widget.setLayout(oidc_row)
        self._oidc_tokens = None
        self.dav_box = QWidget()
        dform = QFormLayout(self.dav_box)
        self.dav_form = dform
        dform.addRow("Server:", self.dav_url)
        dform.addRow("Anmeldung:", self.dav_auth)
        dform.addRow("Benutzer:", self.dav_user)
        dform.addRow("App-Passwort:", self.pw_widget)
        dform.addRow("", self.dav_remember)
        dform.addRow("OIDC-Anbieter:", self.oidc_issuer)
        dform.addRow("Client-ID:", self.oidc_client)
        dform.addRow("", self.oidc_widget)
        dform.addRow("Ordner:", self.dav_folder)
        dform.addRow("", dav_hint)
        self.dav_auth.currentIndexChanged.connect(self._update_dav_auth)

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
        self.load_btn = QPushButton("Einstellungen laden …")
        self.load_btn.setToolTip("Verbindung und Anmeldung aus einer YAML-Datei übernehmen "
                                 "(z. B. von einem anderen Gerät).")
        self.load_btn.clicked.connect(self._load_file)
        self.save_btn = QPushButton("Einstellungen exportieren …")
        self.save_btn.setToolTip("Verbindung und Anmeldung als YAML-Datei speichern.")
        self.save_btn.clicked.connect(self._export_file)
        self.cfg_label = QLabel()
        self.cfg_label.setStyleSheet("color: gray")
        self.cfg_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        content = QWidget()
        lay = QVBoxLayout(content)
        lay.setContentsMargins(0, 0, 8, 0)
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        lay.addWidget(self.rb_sftp)
        lay.addWidget(self.sftp_box)
        lay.addWidget(self.rb_dav)
        lay.addWidget(self.dav_box)
        lay.addWidget(self.rb_local)
        lay.addWidget(self.local_box)
        lay.addStretch(1)
        row = QHBoxLayout()
        row.addWidget(self.test_btn)
        self.lock_btn = QPushButton("App-Sperre …")
        self.lock_btn.setToolTip("Wizard nur nach Passwort oder Security-Key/Passkey öffnen.")
        self.lock_btn.clicked.connect(self._app_lock)
        row.addWidget(self.lock_btn)
        row.addStretch(1)
        row.addWidget(self.load_btn)
        row.addWidget(self.save_btn)
        outer.addLayout(row)
        outer.addWidget(self.status)
        outer.addWidget(self.cfg_label)

        for w in (self.host, self.user, self.key, self.local_dir, self.dav_url, self.dav_user, self.dav_pw,
                  self.oidc_issuer, self.oidc_client):
            w.textChanged.connect(self.completeChanged)
        self.key.textChanged.connect(self._update_pub)
        self.rb_sftp.toggled.connect(self._update_mode)
        self.rb_dav.toggled.connect(self._update_mode)
        self._update_mode()
        self._update_pub()
        self._update_remember_labels()
        self._fill_secrets(p)
        self._ready = True
        self._update_dav_auth()

    # ------------------------------------------------------------------ Anmeldedaten / Datei
    def _update_remember_labels(self) -> None:
        where = "im Schlüsselbund des Systems" if keyring_available() else "in der Einstellungsdatei"
        if self.state.profile.password_store == "file":
            where = "in der Einstellungsdatei"
        self.dav_remember.setText(f"App-Passwort dauerhaft speichern ({where})")
        self.sftp_remember.setText(f"Passphrase dauerhaft speichern ({where})")
        self.cfg_label.setText(f"Einstellungen: {config_file()}")

    def _fill_secrets(self, p: Profile) -> None:
        remember = p.password_store != "none"
        self.dav_remember.setChecked(remember)
        self.sftp_remember.setChecked(remember)
        for typ, field in (("webdav", self.dav_pw), ("sftp", self.passphrase)):
            secret = load_secret(dataclasses.replace(p, storage_type=typ))
            if secret:
                field.setText(secret)

    def _fill_fields(self, p: Profile) -> None:
        {"local": self.rb_local, "webdav": self.rb_dav}.get(p.storage_type, self.rb_sftp).setChecked(True)
        self.host.setText(p.host)
        self.port.setValue(p.port or 22)
        self.user.setText(p.username)
        self.key.setText(p.key_path or self._default_key())
        self.remote_base.setText(p.base_path or ".")
        self.dav_url.setText(p.webdav_url)
        self.dav_user.setText(p.webdav_user)
        self.dav_folder.setText(p.webdav_folder or "Yaleno")
        self.dav_auth.setCurrentIndex(max(0, self.dav_auth.findData(p.webdav_auth)))
        self.oidc_issuer.setText(p.oidc_issuer)
        self.oidc_client.setText(p.oidc_client_id or "yaleno-wizard")
        self._oidc_tokens = None
        self.local_dir.setText(p.local_dir)
        self.dav_pw.clear()
        self.passphrase.clear()
        self._fill_secrets(p)

    def _load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Einstellungen laden", str(Path.home()),
                                              "YAML-Dateien (*.yml *.yaml);;Alle Dateien (*)")
        if not path:
            return
        try:
            loaded = Profile.read(Path(path))
        except ConfigError as exc:
            QMessageBox.warning(self, "Einstellungen laden", f"Die Datei ist ungültig:\n{exc}")
            return
        # Geräteeigene Werte (Name, Kategorien …) nur übernehmen, wenn hier noch nichts gesetzt ist
        cur = self.state.profile
        if cur.backup_name:
            loaded.backup_name = cur.backup_name
        if cur.sync_categories is not None:
            loaded.sync_categories, loaded.sync_excludes = cur.sync_categories, cur.sync_excludes
        self.state.profile = loaded
        self.state.close_storage()
        self._fill_fields(loaded)
        self._update_dav_auth()
        self._update_remember_labels()
        self.status.setText(f"Einstellungen aus {path} übernommen – mit „Weiter“ verbinden und speichern.")

    def _export_file(self) -> None:
        prof = self._profile_from_fields()
        secret = self._secret()
        with_pw = False
        if secret:
            with_pw = QMessageBox.question(
                self, "Einstellungen exportieren",
                "Passwort bzw. Passphrase im Klartext mit in die Datei schreiben?\n\n"
                "Praktisch zum Einrichten weiterer Geräte – die Datei dann aber wie ein Passwort behandeln.",
            ) == QMessageBox.StandardButton.Yes
        if with_pw:
            prof.password_store = "file"
            if prof.storage_type == "webdav":
                prof.webdav_password = secret
            else:
                prof.sftp_passphrase = secret
        path, _ = QFileDialog.getSaveFileName(self, "Einstellungen exportieren", str(Path.home() / "yaleno.yml"),
                                              "YAML-Dateien (*.yml *.yaml)")
        if not path:
            return
        try:
            prof.write(Path(path), include_secrets=with_pw)
        except OSError as exc:
            QMessageBox.warning(self, "Fehler", f"Konnte nicht speichern: {exc}")
            return
        self.status.setText(f"Einstellungen gespeichert: {path}")

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
        self.dav_box.setEnabled(self.rb_dav.isChecked())
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
        path = QFileDialog.getExistingDirectory(self, "Speicherordner wählen", self.local_dir.text())
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
        if self.rb_dav.isChecked():
            if self._oidc_mode():
                return all(w.text().strip() for w in (self.dav_url, self.oidc_issuer, self.oidc_client))
            return all(w.text().strip() for w in (self.dav_url, self.dav_user)) and bool(self.dav_pw.text())
        return all(w.text().strip() for w in (self.host, self.user, self.key))

    # ------------------------------------------------------------------ verbinden
    def _key(self) -> tuple:
        if self.rb_local.isChecked():
            return ("local", self.local_dir.text().strip())
        if self.rb_dav.isChecked():
            return ("webdav", self.dav_url.text().strip(), self.dav_user.text().strip(),
                    self.dav_folder.text().strip(), self.dav_auth.currentData(),
                    self.oidc_issuer.text().strip(), self.oidc_client.text().strip())
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

    def _profile_from_fields(self) -> Profile:
        p = dataclasses.replace(self.state.profile)
        key = self._key()
        if key[0] == "local":
            p.storage_type, p.local_dir = "local", key[1]
        elif key[0] == "webdav":
            p.storage_type = "webdav"
            p.webdav_url, p.webdav_user, p.webdav_folder, p.webdav_auth, p.oidc_issuer, p.oidc_client_id = key[1:]
        else:
            p.storage_type = "sftp"
            p.host, p.port, p.username, p.key_path, p.base_path = key[1:]
        return p

    def _secret(self) -> str:
        if self.rb_dav.isChecked():
            return self.dav_pw.text()
        if self.rb_sftp.isChecked():
            return self.passphrase.text()
        return ""

    def _remember(self) -> bool:
        return (self.dav_remember if self.rb_dav.isChecked() else self.sftp_remember).isChecked()

    def _connect(self) -> bool:
        key = self._key()
        if self.state.storage is not None and self.state.storage_key == key:
            return True
        self.state.close_storage()
        prof = self._profile_from_fields()
        secret = self._secret()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            auth = None
            if prof.storage_type == "webdav" and prof.webdav_auth == "oidc" and self._oidc_tokens is not None:
                from ...storage.connect import oidc_auth
                auth = oidc_auth(prof, self._oidc_tokens)
            storage, base = open_storage(prof, secret, self._confirm_host_key, auth=auth)
            store = Store(storage, base)
            try:
                head = store.head()
                if store.initialized:
                    _ = store.id  # prüft Format/Version
            except (StorageError, OSError, ValueError) as exc:
                storage.close()
                raise StorageError(f"Speicher konnte nicht gelesen werden: {exc}") from exc
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

        if store.encrypted:
            from ..unlock_dialog import unlock_store
            try:
                ok = unlock_store(self, store)
            except (StorageError, OSError) as exc:
                self.status.setText(f"⚠ {exc}")
                ok = False
            if not ok:
                storage.close()
                if not self.status.text().startswith("⚠"):
                    self.status.setText("⚠ Der Speicher ist verschlüsselt und wurde nicht entsperrt.")
                return False

        self.state.storage = storage
        self.state.storage_key = key
        self.state.base_path = base
        self.state.store = store
        self.state.reset_run()
        msg = f"✔ Verbunden mit {storage.description}. " + (
            f"Aktueller Stand: Version {head}" if head else "Noch leer – der erste Abgleich legt den Speicher an.")
        if store.encrypted:
            msg += " 🔐 verschlüsselt."

        # Einstellungen + Anmeldedaten dauerhaft speichern
        if prof.storage_type != "local" and not (prof.storage_type == "webdav" and prof.webdav_auth == "oidc"):
            want = ("keyring" if keyring_available() and prof.password_store != "file" else "file") \
                if self._remember() else "none"
            where = save_secret(prof, secret, want)
            if secret and where == "keyring":
                msg += "<br>Passwort im Schlüsselbund gespeichert."
            elif secret and where == "file":
                msg += f"<br>Passwort in {config_file()} gespeichert (nur für dich lesbar)."
        self.state.profile = prof
        try:
            prof.save()
        except OSError as exc:
            msg += f"<br>⚠ Einstellungen konnten nicht gespeichert werden: {exc}"
        self.status.setText(msg)
        self._update_remember_labels()
        return True

    def _app_lock(self) -> None:
        from ..app_lock_dialog import AppLockSettingsDialog
        AppLockSettingsDialog(self.state.profile, self).exec()

    def _oidc_mode(self) -> bool:
        return self.dav_auth.currentData() == "oidc"

    def _update_dav_auth(self) -> None:
        if not getattr(self, "_ready", False):
            return
        oidc = self._oidc_mode()
        f = self.dav_form
        f.setRowVisible(self.pw_widget, not oidc)
        f.setRowVisible(self.dav_remember, not oidc)
        f.setRowVisible(self.dav_hint, not oidc)
        for w in (self.oidc_issuer, self.oidc_client, self.oidc_widget):
            f.setRowVisible(w, oidc)
        self.browser_btn.setVisible(not oidc)
        self.dav_user.setPlaceholderText("optional – wird bei Nextcloud ermittelt" if oidc else "")
        if oidc:
            from ...credentials import load_oidc_token
            has = self._oidc_tokens is not None or bool(load_oidc_token(self._profile_from_fields().oidc_config().account))
            self.oidc_status.setText("✔ angemeldet" if has else "noch nicht angemeldet")
        self.completeChanged.emit()

    def _browser_login(self) -> None:
        from ...storage.auth import AuthError, login_flow_poll, login_flow_start
        from ..browser_login import Cancelled, run_waiting
        url = self.dav_url.text().strip()
        if not url:
            self.status.setText("⚠ Bitte zuerst die Adresse der Nextcloud eintragen.")
            return
        try:
            flow = login_flow_start(url)
        except AuthError as exc:
            self.status.setText(f"⚠ {exc}")
            return
        QDesktopServices.openUrl(QUrl(flow.login_url))
        try:
            res = run_waiting(self, "Nextcloud-Anmeldung", "Bitte im Browser bei Nextcloud anmelden und den "
                              "Zugriff erlauben …", lambda rep: login_flow_poll(flow, cancelled=rep.cancelled))
        except Cancelled:
            self.status.setText("Anmeldung im Browser abgebrochen.")
            return
        except RuntimeError as exc:
            self.status.setText(f"⚠ {exc}")
            return
        self.dav_url.setText(res.server)
        self.dav_user.setText(res.login_name)
        self.dav_pw.setText(res.app_password)
        self.dav_remember.setChecked(True)
        self.status.setText(f"✔ Angemeldet als {res.login_name} – App-Passwort übernommen. "
                            "Mit „Weiter“ verbinden.")

    def _oidc_login(self) -> None:
        from ...credentials import save_oidc_token
        from ...storage.auth import authorize
        from ..browser_login import Cancelled, run_waiting
        cfg = self._profile_from_fields().oidc_config()
        if not (cfg.issuer and cfg.client_id):
            self.status.setText("⚠ Bitte OIDC-Anbieter und Client-ID eintragen.")
            return
        try:
            tokens = run_waiting(self, "OIDC-Anmeldung", "Bitte im Browser anmelden …",
                                 lambda rep: authorize(cfg, cancelled=rep.cancelled))
        except Cancelled:
            self.status.setText("Anmeldung abgebrochen.")
            return
        except RuntimeError as exc:
            self.status.setText(f"⚠ {exc}")
            return
        self._oidc_tokens = tokens
        who = tokens.id_claims.get("preferred_username") or tokens.id_claims.get("email") or ""
        if who and not self.dav_user.text().strip():
            self.dav_user.setText(str(who))
        msg = f"✔ Per OIDC angemeldet{' als ' + str(who) if who else ''}."
        if tokens.refresh_token:
            try:
                save_oidc_token(cfg.account, tokens.refresh_token)
            except OSError as exc:
                msg += f" ⚠ Token nicht gemerkt: {exc}"
        else:
            msg += (" ⚠ Kein Refresh-Token erhalten (Scope „offline_access“ erlaubt?) – der "
                    "Hintergrund-Abgleich kann sich so nicht selbst anmelden.")
        self.status.setText(msg)
        self.state.close_storage()
        self._update_dav_auth()

    def _test(self) -> None:
        self._connect()

    def validatePage(self) -> bool:
        return self._connect()
