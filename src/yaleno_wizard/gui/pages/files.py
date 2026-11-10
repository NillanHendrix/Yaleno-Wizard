"""Seite 5: Einzelne Dateien auswählen, ansehen/bearbeiten, Bestand exportieren/importieren."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QItemSelectionModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QSplitter,
    QTreeView, QVBoxLayout, QWidget, QWizardPage,
)

from ...core.entry import Entry, human_size
from ...core.inventory import apply_inventory, export_inventory, parse_inventory
from ..file_editor import FileEditor
from ..file_tree_model import FileTreeModel
from ..state import Mode, WizardState


class FilesPage(QWizardPage):
    def __init__(self, state: WizardState):
        super().__init__()
        self.state = state
        self.setTitle("Dateien auswählen")
        self.setSubTitle("Einzelne Ordner oder Dateien ab- oder anwählen. Abgewählte Dateien bleiben bei "
                         "diesem Vorgang unberührt. Kursiv = liegt nur im Speicher und wird geholt. "
                         "Eine Datei anklicken, um sie rechts anzusehen und zu bearbeiten.")

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
        self.tree.selectionModel().currentChanged.connect(self._current_changed)

        self.editor = FileEditor()
        self.editor.saved.connect(self._saved)
        self._shown_index = QModelIndex()

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

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(top)
        ll.addWidget(self.tree, 1)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.addWidget(left)
        self.splitter.addWidget(self.editor)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setChildrenCollapsible(False)

        lay = QVBoxLayout(self)
        lay.addWidget(self.splitter, 1)
        lay.addLayout(bottom)

    # ------------------------------------------------------------------
    def _command_label(self, e: Entry) -> str:
        cat = self.state.catalog.get(e.category)
        item = cat.item(e.item) if cat else None
        name = e.logical[len("@cmd/"):]
        return f"{item.label} ({name})" if item else name

    def initializePage(self) -> None:
        entries = self.state.entries_in_categories()
        selected = self.state.selected
        if selected is None and self.state.mode == Mode.SYNC and self.state.profile.sync_excludes:
            # gemerkte Abwahl vom letzten Mal (gilt auch für den Hintergrund-Abgleich)
            from ...core.background import excluded_selection
            selected = excluded_selection(self.state.available_entries(), self.state.profile.sync_excludes)
        self.model.set_entries(entries, selected, self.state.category_names(), self._command_label,
                               note=self._note)
        self.tree.expandToDepth(0)
        self._shown_index = QModelIndex()
        self.editor.show_message("Eine Datei im Baum anklicken, um sie anzusehen und zu bearbeiten.")
        for col in (1, 2):
            self.tree.resizeColumnToContents(col)
            self.tree.setColumnWidth(col, max(self.tree.columnWidth(col), 110))

    # ------------------------------------------------------------------ Ansicht/Bearbeiten
    def _current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        cur0 = current.siblingAtColumn(0) if current.isValid() else current
        if cur0 == self._shown_index:
            return
        if not self.editor.confirm_leave():
            # Auswahl auf die bearbeitete Datei zurücksetzen
            sm = self.tree.selectionModel()
            sm.blockSignals(True)
            sm.setCurrentIndex(self._shown_index, QItemSelectionModel.SelectionFlag.ClearAndSelect
                               | QItemSelectionModel.SelectionFlag.Rows)
            sm.blockSignals(False)
            return
        self._shown_index = cur0
        node = self.model.node_at(self.proxy.mapToSource(cur0))
        if node is None or node.entry is None:
            self.editor.show_message("Eine Datei im Baum anklicken, um sie anzusehen und zu bearbeiten.")
            return
        e = node.entry
        if self.state.mode != Mode.SYNC:
            self.editor.show_message("Dateien aus einer früheren Version lassen sich nur ansehen, wenn sie "
                                     "auf dieses Gerät geholt wurden. Zum Bearbeiten „Abgleichen“ wählen.")
            return
        name = e.logical if e.is_command else node.name
        self.editor.open_entry(e, name)
        if self.editor.path is not None:
            self.editor.setToolTip(e.logical)

    def _saved(self, e: Entry) -> None:
        self.model.refresh_entry(e.key)
        self.state.plan = None  # Abgleich neu planen (geänderte Datei)

    def _note(self, e: Entry) -> str:
        return "nur im Speicher – wird auf dieses Gerät geholt" if self.state.remote_only(e) else ""

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
        if not self.editor.confirm_leave():
            return False
        # Auswahl für alle bekannten Einträge merken (auch nicht angezeigte Kategorien behalten)
        prev = self.state.selected
        shown = set(self.model.leaves)
        keep = {k for k in prev if k not in shown} if prev is not None else {
            e.key for e in self.state.available_entries() if e.key not in shown
        }
        new = keep | self.model.selected_keys()
        if new != self.state.selected:
            self.state.plan = None
        self.state.selected = new
        if self.state.mode == Mode.SYNC:
            excl = self.model.excluded_patterns()
            prof = self.state.profile
            # Abwahl in nicht angezeigten Kategorien beibehalten
            shown_cats = {e.category for e in (n.entry for n in self.model.leaves.values())}
            merged = {c: v for c, v in prof.sync_excludes.items() if c not in shown_cats}
            merged.update(excl)
            if merged != prof.sync_excludes:
                prof.sync_excludes = merged
                try:
                    prof.save()
                except OSError:
                    pass
        return True

    def cleanupPage(self) -> None:
        if self.editor.dirty and not self.editor.confirm_leave():
            self.editor.revert()  # Zurück lässt sich nicht abbrechen – Änderungen verwerfen
        self.validatePage()

    # ------------------------------------------------------------------ Bestand
    def _meta(self) -> dict[str, str]:
        s = self.state
        if s.mode == Mode.HISTORY and s.revision:
            return {"host": s.source_host, "os": s.source_os, "version": str(s.revision.number)}
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
