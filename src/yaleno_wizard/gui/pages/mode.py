"""Seite 2: Sichern oder Wiederherstellen."""

from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout, QWizardPage

from ...core.manifest import sanitize_host
from ..state import Mode, WizardState


class ModePage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Was möchtest du tun?")
        self.setSubTitle("Daten dieses Rechners sichern oder aus einer vorhandenen Sicherung wiederherstellen.")

        self.rb_backup = QRadioButton("Sichern – Dateien und Einstellungen auf den Speicher hochladen")
        self.rb_restore = QRadioButton("Wiederherstellen – Dateien und Einstellungen aus einer Sicherung holen")
        self.rb_backup.setChecked(state.mode == Mode.BACKUP)
        self.rb_restore.setChecked(state.mode == Mode.RESTORE)

        self.name = QLineEdit(state.profile.backup_name or state.host_name)
        self.name.setToolTip("Unter diesem Namen landet die Sicherung auf dem Speicher.")
        form = QFormLayout()
        form.addRow("Name dieses Rechners:", self.name)

        os_label = QLabel(f"Betriebssystem: {'Windows' if state.os_name == 'windows' else 'Linux'}")
        os_label.setStyleSheet("color: gray")

        lay = QVBoxLayout(self)
        lay.addWidget(self.rb_backup)
        lay.addWidget(self.rb_restore)
        lay.addSpacing(12)
        lay.addLayout(form)
        lay.addWidget(os_label)
        lay.addStretch(1)

        self.rb_backup.toggled.connect(lambda on: self.name.setEnabled(on))
        self.name.setEnabled(self.rb_backup.isChecked())

    def validatePage(self) -> bool:
        new_mode = Mode.BACKUP if self.rb_backup.isChecked() else Mode.RESTORE
        if new_mode != self.state.mode:
            self.state.categories = []
            self.state.selected = None
        self.state.mode = new_mode
        self.state.host_name = sanitize_host(self.name.text() or self.state.host_name)
        if self.state.profile.backup_name != self.state.host_name:
            self.state.profile.backup_name = self.state.host_name
            try:
                self.state.profile.save()
            except OSError:
                pass
        return True
