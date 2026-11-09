"""Seite 6: Zusammenfassung und Optionen."""

from __future__ import annotations

import html
from collections import Counter

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLabel, QTextBrowser, QVBoxLayout, QWidget, QWizard, QWizardPage,
)

from ...core.entry import human_size
from ...core.manifest import snapshot_dir
from ...core.restore import ActionKind, ConflictPolicy, RestoreAction, plan_restore
from ...settings import default_staging_dir
from ..state import Mode, WizardState


class SummaryPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Zusammenfassung")
        self.setSubTitle("Bitte prüfen. Nach dem Start ist kein Zurück mehr möglich (Abbrechen schon).")
        self.setCommitPage(True)
        self.actions: list[RestoreAction] = []

        self.text = QTextBrowser()
        self.opts = QWidget()
        form = QFormLayout(self.opts)
        form.setContentsMargins(0, 0, 0, 0)
        self.conflict = QComboBox()
        self.conflict.addItem("Vorhandene Dateien behalten (überspringen)", ConflictPolicy.SKIP)
        self.conflict.addItem("Beide behalten (Sicherung als „name.yaleno-DATUM.ext“)", ConflictPolicy.KEEP_BOTH)
        self.conflict.addItem("Vorhandene Dateien überschreiben", ConflictPolicy.OVERWRITE)
        self.run_cmds = QCheckBox("Einstellungen per Befehl einspielen (dconf load / reg import / winget import)")
        self.run_cmds.setToolTip("Sonst werden Befehlsausgaben nur als Dateien in den Ablageordner gelegt.")
        self.run_cmds.toggled.connect(self._refresh)
        self.dry_run = QCheckBox("Probelauf – nur anzeigen, was passieren würde")
        self.staging = QLabel()
        self.staging.setWordWrap(True)
        form.addRow("Bei vorhandenen Dateien:", self.conflict)
        form.addRow("", self.run_cmds)
        form.addRow("", self.dry_run)
        form.addRow("Ablageordner:", self.staging)

        lay = QVBoxLayout(self)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.opts)

    def initializePage(self) -> None:
        backup = self.state.mode == Mode.BACKUP
        self.opts.setVisible(not backup)
        self.setButtonText(QWizard.WizardButton.CommitButton,
                           "Sicherung starten" if backup else "Wiederherstellung starten")
        self._refresh()

    def _cat_table(self, entries) -> str:
        names = self.state.category_names()
        counts: Counter = Counter()
        sizes: Counter = Counter()
        for e in entries:
            counts[e.category] += 1
            sizes[e.category] += e.size
        rows = "".join(
            f"<tr><td>{html.escape(names.get(c, c))}</td><td align=right>{counts[c]}</td>"
            f"<td align=right>{human_size(sizes[c])}</td></tr>" for c in counts
        )
        return (f"<table cellspacing=6><tr><th align=left>Kategorie</th><th>Dateien</th><th>Größe</th></tr>"
                f"{rows}<tr><td><b>Gesamt</b></td><td align=right><b>{sum(counts.values())}</b></td>"
                f"<td align=right><b>{human_size(sum(sizes.values()))}</b></td></tr></table>")

    def _refresh(self) -> None:
        s = self.state
        entries = s.selected_entries()
        if s.mode == Mode.BACKUP:
            target = snapshot_dir(s.base_path, s.host_name, "<Datum_Uhrzeit>")
            used = {e.category for e in entries}
            sens = [c.name for c in s.catalog.categories if c.sensitive and c.id in used]
            warn = (f"<p><b>⚠ Enthält sensible Daten</b> ({html.escape(', '.join(sens))}). Nur auf einen "
                    "vertrauenswürdigen Speicher sichern.</p>" if sens else "")
            cmds = sum(1 for e in entries if e.is_command)
            cmd_note = f"<p>{cmds} Befehle werden ausgeführt (z. B. Paketlisten).</p>" if cmds else ""
            self.text.setHtml(
                f"<p>Ziel: <code>{html.escape(s.storage.description if s.storage else '')}</code><br>"
                f"Ordner: <code>{html.escape(target)}</code></p>{self._cat_table(entries)}{cmd_note}{warn}"
            )
            return

        m = s.manifest
        assert m is not None and s.snapshot is not None
        staging = default_staging_dir(m.snapshot)
        self.staging.setText(str(staging))
        self.actions = plan_restore(m, entries, s.mapper, s.catalog, s.os_name, staging,
                                    run_commands=self.run_cmds.isChecked())
        kinds = Counter(a.kind for a in self.actions)
        existing = sum(1 for a in self.actions if a.kind == ActionKind.FILE and a.exists)
        lines = [
            f"An den Originalort: <b>{kinds[ActionKind.FILE]}</b> Dateien "
            f"(davon existieren bereits {existing})",
            f"In den Ablageordner: <b>{kinds[ActionKind.STAGING]}</b>",
        ]
        if kinds[ActionKind.COMMAND]:
            lines.append(f"Per Befehl einspielen: <b>{kinds[ActionKind.COMMAND]}</b>")
        if kinds[ActionKind.BLOCKED]:
            lines.append(f"Nicht möglich: <b>{kinds[ActionKind.BLOCKED]}</b>")
        self.text.setHtml(
            f"<p>Quelle: <b>{html.escape(m.host)}</b>, Sicherung vom {html.escape(m.created.replace('T', ' '))}</p>"
            f"{self._cat_table(entries)}<p>" + "<br>".join(lines) + "</p>"
        )

    def validatePage(self) -> bool:
        if self.state.mode == Mode.RESTORE:
            self._refresh()
        return True

    def options(self) -> tuple[ConflictPolicy, bool]:
        return self.conflict.currentData(), self.dry_run.isChecked()
