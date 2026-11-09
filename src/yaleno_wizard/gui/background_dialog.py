"""Einstellungen für den Hintergrund-Abgleich."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout,
)

from .. import autostart
from ..credentials import load_secret
from ..settings import Profile


class BackgroundDialog(QDialog):
    def __init__(self, profile: Profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle("Hintergrund-Abgleich")

        intro = QLabel("Gleicht dieses Gerät regelmäßig mit dem Speicher ab – ohne Wizard, mit einem Symbol "
                       "im Infobereich. Es gelten die zuletzt im Wizard gewählten Kategorien und Dateien.")
        intro.setWordWrap(True)
        self.enabled = QCheckBox("Hintergrund-Abgleich aktivieren")
        self.enabled.setChecked(profile.bg_enabled)
        self.interval = QSpinBox()
        self.interval.setRange(1, 24 * 60)
        self.interval.setSuffix(" min")
        self.interval.setValue(profile.bg_interval)
        self.autostart = QCheckBox("Beim Anmelden automatisch starten")
        self.autostart.setChecked(profile.bg_autostart or autostart.is_enabled())
        self.conflicts = QComboBox()
        self.conflicts.addItem("Neuere Änderung gewinnt", "newer")
        self.conflicts.addItem("Dieses Gerät gewinnt", "local")
        self.conflicts.addItem("Speicher gewinnt", "remote")
        self.conflicts.setCurrentIndex(max(0, self.conflicts.findData(profile.conflicts)))
        self.conflicts.setToolTip("Die unterlegene Fassung bleibt immer als „(Konflikt …)“-Kopie erhalten.")

        form = QFormLayout()
        form.addRow("Abstand:", self.interval)
        form.addRow("Bei Konflikten:", self.conflicts)
        form.addRow("", self.autostart)

        self.warn = QLabel()
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet("color: #b35c00")
        problems = self.problems()
        if problems:
            self.warn.setText("⚠ " + "\n⚠ ".join(problems))

        note = QLabel("Viele Löschungen auf einmal werden im Hintergrund nie ausgeführt – dann erscheint ein "
                      "Hinweis, und der Abgleich muss im Wizard bestätigt werden.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(intro)
        lay.addWidget(self.enabled)
        lay.addLayout(form)
        lay.addWidget(self.warn)
        lay.addWidget(note)
        lay.addWidget(buttons)
        self.enabled.toggled.connect(self._update)
        self._update()

    def problems(self) -> list[str]:
        p = self.profile
        out = []
        if not p.sync_categories:
            out.append("Noch keine Kategorien gewählt – bitte zuerst einmal im Wizard abgleichen.")
        if p.storage_type == "webdav" and not load_secret(p):
            out.append("Das App-Passwort ist nicht gespeichert – beim Verbinden „dauerhaft speichern“ anhaken.")
        return out

    def _update(self) -> None:
        on = self.enabled.isChecked()
        for w in (self.interval, self.autostart, self.conflicts):
            w.setEnabled(on)

    def apply(self) -> None:
        """Übernimmt die Einstellungen ins Profil und richtet den Autostart ein (Profil danach speichern)."""
        p = self.profile
        p.bg_enabled = self.enabled.isChecked()
        p.bg_interval = self.interval.value()
        p.conflicts = self.conflicts.currentData()
        p.bg_autostart = p.bg_enabled and self.autostart.isChecked()
        autostart.set_enabled(p.bg_autostart)
