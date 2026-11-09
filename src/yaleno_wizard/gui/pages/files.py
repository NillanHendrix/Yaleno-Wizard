"""Seite 5: Einzelne Dateien auswählen, Bestand exportieren/importieren."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTreeView,
    QVBoxLayout, QWizardPage,
)

from ...core.entry import Entry, human_size
from ...core.inventory import apply_inventory, export_inventory, parse_inventory
from ..file_tree_model import FileTreeModel
from ..state import Mode, WizardState


class FilesPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Dateien auswählen")
        self.setSubTitle("Einzelne Ordner oder Dateien ab- oder anwählen. Die Auswahl lässt sich als "
                         "Bestand-Textdatei exportieren und später wieder importieren.")

        self.model = FileTreeModel(self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setRecursiveFilteringEnabled(True)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(0)

        self.tree = QTreeView()
        self.tree.setModel(self.proxy)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)

        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filtern nach Name …")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)

        b_all = QPushButton("Alle")
        b_all.clicked.connect(lambda: self.model.set_all(True))
        b_none = QPushButton("Keine")
        b_none.clicked.connect(lambda: self.model.set_all(False))
        b_exp = QPushButton("Bestand exportieren …")
        b_exp.clicked.connect(self._export)
        b_imp = QPushButton("Bestand importieren …")
        b_imp.clicked.connect(self._import)

        self.stats = QLabel()
        self.model.statsChanged.connect(self._stats)

        top = QHBoxLayout()
        top.addWidget(self.filter, 1)
        top.addWidget(b_all)
        top.addWidget(b_none)
        bottom = QHBoxLayout()
        bottom.addWidget(self.stats, 1)
        bottom.addWidget(b_imp)
        bottom.addWidget(b_exp)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.tree, 1)
        lay.addLayout(bottom)

    # ------------------------------------------------------------------
    def _command_label(self, e: Entry) -> str:
        cat = self.state.catalog.get(e.category)
        item = cat.item(e.item) if cat else None
        name = e.logical[len("@cmd/"):]
        return f"{item.label} ({name})" if item else name

    def initializePage(self) -> None:
        entries = self.state.entries_in_categories()
        self.model.set_entries(entries, self.state.selected, self.state.category_names(), self._command_label)
        self.tree.expandToDepth(0)
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
            self.tree.setColumnWidth(col, max(self.tree.columnWidth(col), 110))

    def _filter(self, text: str) -> None:
        self.proxy.setFilterFixedString(text)
        if text:
            self.tree.expandAll()

    def _stats(self, n: int, size: int) -> None:
        self.stats.setText(f"Ausgewählt: {n} Dateien · {human_size(size)}")
        self.completeChanged.emit()

    def isComplete(self) -> bool:
        return self.model.stats()[0] > 0

    def validatePage(self) -> bool:
        # Auswahl für alle bekannten Einträge merken (auch nicht angezeigte Kategorien behalten)
        prev = self.state.selected
        shown = set(self.model.leaves)
        keep = {k for k in prev if k not in shown} if prev is not None else {
            e.key for e in self.state.available_entries() if e.key not in shown
        }
        self.state.selected = keep | self.model.selected_keys()
        return True

    def cleanupPage(self) -> None:
        self.validatePage()

    # ------------------------------------------------------------------ Bestand
    def _meta(self) -> dict[str, str]:
        s = self.state
        if s.mode == Mode.RESTORE and s.manifest:
            return {"host": s.manifest.host, "os": s.manifest.os, "snapshot": s.manifest.snapshot}
        return {"host": s.host_name, "os": s.os_name}

    def _export(self) -> None:
        box = QMessageBox(self)
        box.setWindowTitle("Bestand exportieren")
        box.setText("Was soll in die Bestand-Datei?")
        b_sel = box.addButton("Nur die Auswahl", QMessageBox.ButtonRole.AcceptRole)
        b_all = box.addButton("Gesamter Bestand", QMessageBox.ButtonRole.AcceptRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked is b_sel:
            entries = self.model.selected_entries()
        elif clicked is b_all:
            entries = [n.entry for n in self.model.leaves.values()]
        else:
            return
        meta = self._meta()
        default = Path.home() / f"yaleno-bestand-{meta['host']}-{datetime.now():%Y-%m-%d}.txt"
        path, _ = QFileDialog.getSaveFileName(self, "Bestand speichern", str(default), "Textdateien (*.txt)")
        if not path:
            return
        text = export_inventory(entries, self.state.category_names(), meta)
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Fehler", f"Konnte nicht speichern: {exc}")
            return
        self.stats.setText(f"Bestand mit {len(entries)} Einträgen gespeichert: {path}")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Bestand laden", str(Path.home()),
                                              "Textdateien (*.txt);;Alle Dateien (*)")
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Fehler", f"Konnte nicht lesen: {exc}")
            return
        inv = parse_inventory(text)
        shown = [n.entry for n in self.model.leaves.values()]
        res = apply_inventory(inv, shown)
        self.model.set_selection(res.selected)

        notes: list[str] = []
        names = self.state.category_names()
        if res.missing_categories:
            notes.append("Kategorien, die auf der vorherigen Seite nicht gewählt oder hier nicht vorhanden sind:\n  "
                         + "\n  ".join(names.get(c, c) for c in res.missing_categories))
        unmatched = [r for r in res.unmatched if r.category not in res.missing_categories]
        if unmatched:
            lst = "\n  ".join(f"[{r.category}] {r}" for r in unmatched[:25])
            more = f"\n  … und {len(unmatched) - 25} weitere" if len(unmatched) > 25 else ""
            notes.append(f"Nicht gefundene Einträge ({len(unmatched)}):\n  {lst}{more}")
        if inv.errors:
            notes.append("Fehlerhafte Zeilen:\n  " + "\n  ".join(inv.errors[:15]))
        msg = f"{len(res.selected)} Dateien gemäß Bestand ausgewählt."
        if notes:
            QMessageBox.information(self, "Bestand importiert", msg + "\n\n" + "\n\n".join(notes))
        else:
            self.stats.setText(msg)
