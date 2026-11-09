"""Baum-Modell mit Tristate-Checkboxen für die Dateiauswahl."""

from __future__ import annotations

from datetime import datetime
from typing import Callable, Iterable

from PySide6.QtCore import QAbstractItemModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QStyle

from ..catalog.placeholders import DISPLAY_NAMES, PLACEHOLDER_RE
from ..core.entry import Entry, human_size

COLUMNS = ("Name", "Größe", "Geändert")


class Node:
    __slots__ = ("name", "parent", "children", "index_of", "entry", "row",
                 "n_total", "n_sel", "size_total", "size_sel")

    def __init__(self, name: str, parent: "Node | None", entry: Entry | None = None):
        self.name = name
        self.parent = parent
        self.children: list[Node] = []
        self.index_of: dict[str, Node] = {}
        self.entry = entry
        self.row = 0
        self.n_total = 1 if entry else 0
        self.n_sel = 0
        self.size_total = entry.size if entry else 0
        self.size_sel = 0

    @property
    def is_leaf(self) -> bool:
        return self.entry is not None

    def child(self, name: str) -> "Node":
        n = self.index_of.get(name)
        if n is None:
            n = Node(name, self)
            self.index_of[name] = n
            self.children.append(n)
        return n

    def finalize(self) -> None:
        """Sortiert (Ordner zuerst), vergibt Zeilennummern, summiert Größen.

        Die oberste Ebene (Kategorien) behält die Katalog-Reihenfolge."""
        if self.parent is not None:
            self.children.sort(key=lambda n: (n.is_leaf, n.name.lower()))
        for i, c in enumerate(self.children):
            c.row = i
            if not c.is_leaf:
                c.finalize()
        if not self.is_leaf:
            self.n_total = sum(c.n_total for c in self.children)
            self.size_total = sum(c.size_total for c in self.children)


class FileTreeModel(QAbstractItemModel):
    statsChanged = Signal(object, object)  # anzahl, bytes

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Node("", None)
        self.leaves: dict[tuple[str, str], Node] = {}
        style = QApplication.style()
        self._dir_icon = style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        self._file_icon = style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        self._cat_icon = style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon)
        self._note: Callable[[Entry], str] | None = None

    # ------------------------------------------------------------- aufbauen
    def set_entries(
        self,
        entries: Iterable[Entry],
        selected: set[tuple[str, str]] | None,
        category_names: dict[str, str],
        command_label: Callable[[Entry], str] | None = None,
        note: Callable[[Entry], str] | None = None,
    ) -> None:
        """``note`` liefert einen Hinweis je Datei (z. B. „nur im Speicher“), angezeigt kursiv + Tooltip."""
        self.beginResetModel()
        self._note = note
        self.root = Node("", None)
        self.leaves = {}
        for e in entries:
            cat = self.root.child(category_names.get(e.category, e.category))
            if e.is_command:
                parent = cat.child("Befehlsausgaben")
                name = command_label(e) if command_label else e.logical[len("@cmd/"):]
            else:
                m = PLACEHOLDER_RE.match(e.logical)
                if not m:
                    continue
                parent = cat.child(DISPLAY_NAMES.get(m.group(1), m.group(1)))
                parts = [p for p in (m.group(2) or "").split("/") if p]
                if not parts:
                    continue
                for p in parts[:-1]:
                    parent = parent.child(p)
                name = parts[-1]
            leaf = Node(name, parent, e)
            leaf.n_sel = 1 if (selected is None or e.key in selected) else 0
            leaf.size_sel = e.size if leaf.n_sel else 0
            parent.children.append(leaf)
            self.leaves[e.key] = leaf
        self.root.finalize()
        self._recount(self.root)
        self.endResetModel()
        self._emit_stats()

    def _recount(self, node: Node) -> None:
        if node.is_leaf:
            return
        node.n_sel = 0
        node.size_sel = 0
        for c in node.children:
            self._recount(c)
            node.n_sel += c.n_sel
            node.size_sel += c.size_sel

    # ------------------------------------------------------------- auswahl
    def selected_keys(self) -> set[tuple[str, str]]:
        return {k for k, n in self.leaves.items() if n.n_sel}

    def selected_entries(self) -> list[Entry]:
        return [n.entry for n in self.leaves.values() if n.n_sel]  # type: ignore[misc]

    def excluded_patterns(self) -> dict[str, list[str]]:
        """Abgewählte Teilbäume als möglichst kurze Muster je Kategorie (Ordner enden auf „/“)."""
        out: dict[str, list[str]] = {}

        def first_leaf(n: Node) -> Entry | None:
            while not n.is_leaf:
                if not n.children:
                    return None
                n = n.children[0]
            return n.entry

        def walk(n: Node, depth: int) -> None:
            for c in n.children:
                if c.n_total and c.n_sel == 0:
                    leaf = first_leaf(c)
                    if leaf is None:
                        continue
                    if c.is_leaf:
                        pat = leaf.logical
                    elif depth == 0:
                        pat = "*"  # ganze Kategorie abgewählt
                    else:
                        pat = "/".join(leaf.logical.split("/")[:depth]) + "/"
                    out.setdefault(leaf.category, []).append(pat)
                elif not c.is_leaf and c.n_sel < c.n_total:
                    walk(c, depth + 1)

        walk(self.root, 0)
        return {c: sorted(v) for c, v in out.items()}

    def set_selection(self, keys: set[tuple[str, str]]) -> None:
        for k, n in self.leaves.items():
            n.n_sel = 1 if k in keys else 0
            n.size_sel = n.size_total if n.n_sel else 0
        self._recount(self.root)
        self._emit_subtree(self.root)
        self._emit_stats()

    def set_all(self, checked: bool) -> None:
        self.set_selection(set(self.leaves) if checked else set())

    def stats(self) -> tuple[int, int]:
        return self.root.n_sel, self.root.size_sel

    def _emit_stats(self) -> None:
        self.statsChanged.emit(self.root.n_sel, self.root.size_sel)

    def _set_subtree(self, node: Node, checked: bool) -> tuple[int, int]:
        if node.is_leaf:
            new = 1 if checked else 0
            dn, ds = new - node.n_sel, (node.size_total if new else 0) - node.size_sel
            node.n_sel = new
            node.size_sel = node.size_total if new else 0
            return dn, ds
        dn = ds = 0
        for c in node.children:
            a, b = self._set_subtree(c, checked)
            dn += a
            ds += b
        node.n_sel += dn
        node.size_sel += ds
        return dn, ds

    def _emit_subtree(self, node: Node) -> None:
        if node.children:
            parent_idx = self._index_for(node)
            self.dataChanged.emit(
                self.index(0, 0, parent_idx),
                self.index(len(node.children) - 1, len(COLUMNS) - 1, parent_idx),
                [Qt.ItemDataRole.CheckStateRole, Qt.ItemDataRole.DisplayRole],
            )
            for c in node.children:
                if c.children:
                    self._emit_subtree(c)

    def _index_for(self, node: Node) -> QModelIndex:
        if node is self.root or node.parent is None:
            return QModelIndex()
        return self.createIndex(node.row, 0, node)

    # ------------------------------------------------------------- Qt-API
    def index(self, row, column, parent=QModelIndex()):
        pnode = parent.internalPointer() if parent.isValid() else self.root
        if 0 <= row < len(pnode.children) and 0 <= column < len(COLUMNS):
            return self.createIndex(row, column, pnode.children[row])
        return QModelIndex()

    def parent(self, index=QModelIndex()):  # type: ignore[override]
        if not index.isValid():
            return QModelIndex()
        node: Node = index.internalPointer()
        p = node.parent
        if p is None or p is self.root:
            return QModelIndex()
        return self.createIndex(p.row, 0, p)

    def rowCount(self, parent=QModelIndex()):
        if parent.isValid() and parent.column() != 0:
            return 0
        node = parent.internalPointer() if parent.isValid() else self.root
        return len(node.children)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        f = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            f |= Qt.ItemFlag.ItemIsUserCheckable
        return f

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        node: Node = index.internalPointer()
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return node.name
            if col == 1:
                if node.is_leaf and node.entry.is_command and not node.entry.size:
                    return "beim Abgleich"
                if node.is_leaf or node.n_sel in (0, node.n_total):
                    return human_size(node.size_total)
                return f"{human_size(node.size_sel)} von {human_size(node.size_total)}"
            if col == 2 and node.is_leaf and node.entry and node.entry.mtime:
                return datetime.fromtimestamp(node.entry.mtime).strftime("%d.%m.%Y %H:%M")
            if col == 2 and not node.is_leaf:
                return f"{node.n_sel}/{node.n_total} Dateien"
            return None
        if role == Qt.ItemDataRole.CheckStateRole and col == 0:
            if node.n_sel == 0:
                return Qt.CheckState.Unchecked
            if node.n_sel == node.n_total:
                return Qt.CheckState.Checked
            return Qt.CheckState.PartiallyChecked
        if role == Qt.ItemDataRole.DecorationRole and col == 0:
            if node.parent is self.root:
                return self._cat_icon
            return self._file_icon if node.is_leaf else self._dir_icon
        if role == Qt.ItemDataRole.ToolTipRole and node.entry:
            note = self._note(node.entry) if self._note else ""
            return node.entry.logical + (f"\n{note}" if note else "")
        if role == Qt.ItemDataRole.FontRole and node.entry and self._note and self._note(node.entry):
            f = QFont()
            f.setItalic(True)
            return f
        if role == Qt.ItemDataRole.TextAlignmentRole and col == 1:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role != Qt.ItemDataRole.CheckStateRole or not index.isValid():
            return False
        node: Node = index.internalPointer()
        checked = Qt.CheckState(value) != Qt.CheckState.Unchecked
        dn, ds = self._set_subtree(node, checked)
        p = node.parent
        while p is not None:
            p.n_sel += dn
            p.size_sel += ds
            p = p.parent
        # betroffene Zeilen neu zeichnen: Teilbaum + Vorfahren
        self._emit_subtree(node)
        a = node
        while a is not None and a is not self.root:
            idx = self._index_for(a)
            self.dataChanged.emit(idx, idx.siblingAtColumn(len(COLUMNS) - 1))
            a = a.parent
        self._emit_stats()
        return True
