"""Seite 6: Zusammenfassung und Optionen (Abgleich-Vorschau, Wiederherstellung, Zurücksetzen)."""

from __future__ import annotations

import html
from collections import Counter

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QLabel, QProgressBar, QTextBrowser, QVBoxLayout, QWidget, QWizard,
    QWizardPage,
)

from ...core.entry import human_size
from ...core.restore import ActionKind, ConflictPolicy, RestoreAction, plan_restore
from ...core.store import diff_trees
from ...core.sync import OP_LABELS, ConflictWinner, Op, SyncState, plan_sync
from ...settings import default_staging_dir, sync_state_dir
from ..state import HistoryAction, Mode, WizardState
from ..worker import Worker

MAX_LIST = 300


class SummaryPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Zusammenfassung")
        self.setCommitPage(True)
        self.actions: list[RestoreAction] = []
        self._worker: Worker | None = None
        self._ready = False

        self.busy = QProgressBar()
        self.busy.setRange(0, 0)
        self.text = QTextBrowser()

        # --- Optionen Abgleich
        self.sync_opts = QWidget()
        sf = QFormLayout(self.sync_opts)
        sf.setContentsMargins(0, 0, 0, 0)
        self.winner = QComboBox()
        self.winner.addItem("Neuere Änderung gewinnt", ConflictWinner.NEWER)
        self.winner.addItem("Dieses Gerät gewinnt", ConflictWinner.LOCAL)
        self.winner.addItem("Speicher gewinnt", ConflictWinner.REMOTE)
        self.winner.setToolTip("Die andere Fassung geht nicht verloren: sie wird als "
                               "„name (Konflikt …).ext“ daneben abgelegt und ebenfalls abgeglichen.")
        self.sync_dry = QCheckBox("Probelauf – nur anzeigen, nichts verändern")
        sf.addRow("Bei Konflikten:", self.winner)
        sf.addRow("", self.sync_dry)

        # --- Optionen Wiederherstellen
        self.opts = QWidget()
        form = QFormLayout(self.opts)
        form.setContentsMargins(0, 0, 0, 0)
        self.conflict = QComboBox()
        self.conflict.addItem("Vorhandene Dateien behalten (überspringen)", ConflictPolicy.SKIP)
        self.conflict.addItem("Beide behalten (Version als „name.yaleno-vNR.ext“)", ConflictPolicy.KEEP_BOTH)
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
        lay.addWidget(self.busy)
        lay.addWidget(self.text, 1)
        lay.addWidget(self.sync_opts)
        lay.addWidget(self.opts)

    # ------------------------------------------------------------------
    @property
    def kind(self) -> str:
        s = self.state
        if s.mode == Mode.SYNC:
            return "sync"
        return "reset" if s.history_action == HistoryAction.RESET else "restore"

    def initializePage(self) -> None:
        self._ready = False
        kind = self.kind
        self.sync_opts.setVisible(kind == "sync")
        self.opts.setVisible(kind == "restore")
        self.busy.hide()
        self.setButtonText(QWizard.WizardButton.CommitButton, {
            "sync": "Jetzt abgleichen", "restore": "Wiederherstellung starten",
            "reset": "Speicher zurücksetzen",
        }[kind])
        self.setSubTitle({
            "sync": "Vorschau des Abgleichs. Nach dem Start ist kein Zurück mehr möglich (Abbrechen schon).",
            "restore": "Bitte prüfen. Nach dem Start ist kein Zurück mehr möglich (Abbrechen schon).",
            "reset": "Der Speicher springt auf eine andere Version. Nichts wird gelöscht – der bisherige "
                     "Stand bleibt im Verlauf.",
        }[kind])
        if kind == "sync":
            if self.state.plan is None:
                self._start_plan()
            else:
                self._show_plan()
        else:
            self._refresh()

    # ------------------------------------------------------------------ Abgleich
    def _start_plan(self) -> None:
        self._ready = False
        self.completeChanged.emit()
        self.busy.show()
        self.text.setHtml("<p>Vergleiche dieses Gerät mit dem Speicher …</p>")
        s = self.state
        store = s.store
        assert store is not None and s.scan is not None
        entries = s.scan.entries
        cats, selected = set(s.categories), s.selected

        def job(rep):
            sid = store.ensure_initialized()
            st = SyncState.load(SyncState.file_for(sync_state_dir(), sid, s.host_name))
            plan = plan_sync(store, entries, st, s.catalog, s.mapper, s.os_name, s.host_name, cats, selected,
                             reporter=rep)
            return plan, st

        self._worker = Worker(job, self)
        self._worker.progress.connect(lambda d, t, cur: self.busy.setFormat(cur))
        self._worker.succeeded.connect(self._plan_done)
        self._worker.failed.connect(self._plan_failed)
        self._worker.start()

    def _plan_done(self, result) -> None:
        self.state.plan, self.state.sync_state = result
        self.busy.hide()
        self._show_plan()

    def _plan_failed(self, msg: str) -> None:
        self.busy.hide()
        self.text.setHtml(f"<p>⚠ Vergleich fehlgeschlagen: {html.escape(msg)}</p>")

    def _show_plan(self) -> None:
        plan = self.state.plan
        assert plan is not None
        rows = []
        for op in (Op.UPLOAD, Op.DOWNLOAD, Op.DELETE_REMOTE, Op.DELETE_LOCAL, Op.CONFLICT, Op.COMMAND):
            acts = plan.by_op(op)
            if acts:
                size = sum(a.size for a in acts)
                rows.append(f"<tr><td>{OP_LABELS[op]}</td><td align=right><b>{len(acts)}</b></td>"
                            f"<td align=right>{human_size(size) if op not in (Op.DELETE_LOCAL, Op.DELETE_REMOTE) else ''}"
                            "</td></tr>")
        head = (f"Version {plan.head}" if plan.head else "noch leer")
        intro = (f"<p>Speicher: <code>{html.escape(self.state.storage.description if self.state.storage else '')}"
                 f"</code> · aktueller Stand: {head}<br>Gerät: <b>{html.escape(self.state.host_name)}</b> · "
                 f"{len(plan.in_sync)} Dateien sind bereits auf beiden Seiten gleich.</p>")
        if not plan.actions:
            body = "<p><b>✔ Alles ist bereits auf dem gleichen Stand.</b></p>"
        else:
            body = f"<table cellspacing=6>{''.join(rows)}</table>"
            lines = []
            for a in plan.actions[:MAX_LIST]:
                why = f" – {html.escape(a.reason)}" if a.reason else ""
                lines.append(f"{OP_LABELS[a.op]}: {html.escape(a.logical)}{why}")
            more = f"<br>… und {len(plan.actions) - MAX_LIST} weitere" if len(plan.actions) > MAX_LIST else ""
            body += "<p style='font-size:small'>" + "<br>".join(lines) + more + "</p>"
        warn = ""
        dels = plan.count(Op.DELETE_LOCAL)
        if dels:
            warn += (f"<p><b>⚠ {dels} Dateien werden auf diesem Gerät gelöscht</b>, weil sie auf einem anderen "
                     "Gerät gelöscht wurden. Sie bleiben im Verlauf und lassen sich zurückholen.</p>")
        if plan.count(Op.CONFLICT):
            warn += ("<p>Bei Konflikten bleibt die unterlegene Fassung als „(Konflikt …)“-Kopie erhalten.</p>")
        if plan.skipped:
            warn += f"<p style='color:gray'>{len(plan.skipped)} Dateien übersprungen (z. B. Ordner fehlt hier).</p>"
        sens = {c.name for c in self.state.catalog.categories if c.sensitive and c.id in self.state.categories}
        if sens:
            warn += (f"<p>⚠ Enthält sensible Daten ({html.escape(', '.join(sorted(sens)))}) – nur mit einem "
                     "vertrauenswürdigen Speicher abgleichen.</p>")
        self.text.setHtml(intro + body + warn)
        self._ready = True
        self.completeChanged.emit()

    # ------------------------------------------------------------------ Verlauf
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
        kind = self.kind
        if kind == "sync":
            return
        rev = s.revision
        assert rev is not None
        if kind == "reset":
            store = s.store
            head_rev = store.load_head() if store else None
            a, c, d = diff_trees(head_rev.tree() if head_rev else {}, rev.tree())
            date = rev.info.date.strftime("%d.%m.%Y %H:%M") if rev.info.date else rev.info.created
            self.text.setHtml(
                f"<p>Der Speicher wird auf <b>Version {rev.number}</b> vom {date} gesetzt "
                f"({rev.info.files} Dateien, {human_size(rev.info.size)}).</p>"
                f"<p>Gegenüber dem aktuellen Stand (Version {head_rev.number if head_rev else '–'}): "
                f"{a} Dateien kommen zurück, {c} werden auf den alten Inhalt gesetzt, {d} fallen weg.</p>"
                "<p>Das wird als neue Version gespeichert – der bisherige Stand bleibt im Verlauf, du kannst "
                "jederzeit wieder vorspringen.</p><p><b>Alle Geräte übernehmen den Stand beim nächsten "
                "Abgleich</b> – auch dieses: danach „Neue Aktion“ → Abgleichen.</p>"
            )
            self._ready = True
            self.completeChanged.emit()
            return

        entries = s.selected_entries()
        staging = default_staging_dir(f"v{rev.number}")
        self.staging.setText(str(staging))
        self.actions = plan_restore(rev, entries, s.mapper, s.catalog, s.os_name, staging,
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
        date = rev.info.date.strftime("%d.%m.%Y %H:%M") if rev.info.date else rev.info.created
        self.text.setHtml(
            f"<p>Quelle: <b>Version {rev.number}</b> vom {date}, Daten von "
            f"<b>{html.escape(s.source_host)}</b></p>{self._cat_table(entries)}<p>" + "<br>".join(lines) + "</p>"
            "<p style='color:gray'>Hinweis: Wiederhergestellte Dateien gelten beim nächsten Abgleich als "
            "Änderung dieses Geräts und werden in den Speicher übernommen.</p>"
        )
        self._ready = True
        self.completeChanged.emit()

    # ------------------------------------------------------------------ wizard
    def isComplete(self) -> bool:
        return self._ready

    def validatePage(self) -> bool:
        if self.kind == "restore":
            self._refresh()
        return self._ready

    def cleanupPage(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait()

    def options(self) -> tuple[ConflictPolicy, bool]:
        return self.conflict.currentData(), self.dry_run.isChecked()

    def sync_options(self) -> tuple[ConflictWinner, bool]:
        return self.winner.currentData(), self.sync_dry.isChecked()
