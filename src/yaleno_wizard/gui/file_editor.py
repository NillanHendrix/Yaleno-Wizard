"""Ansicht einer Datei mit Bearbeitung als Formular (INI/JSON/YAML …) oder als Text."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget, QTabWidget, QToolButton, QVBoxLayout,
    QWidget,
)

from ..core.entry import Entry
from ..core.formats import (
    Field, IniDocument, TreeDocument, detect_format, parse_document, read_text, toggle_bool,
)

FORMAT_LABELS = {"ini": "Konfiguration (Abschnitte und Schlüssel)", "json": "JSON", "yaml": "YAML",
                 "text": "Text"}
TAB_FORM, TAB_TEXT = 0, 1


def write_atomic(path: Path, text: str) -> None:
    """Schreibt über eine temporäre Datei im selben Ordner und behält die Rechte bei."""
    mode = path.stat().st_mode & 0o7777 if path.exists() else 0o644
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".yaleno-tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class FileEditor(QWidget):
    """Zeigt eine lokale Datei an; strukturierte Formate zusätzlich als Formular."""

    saved = Signal(object)   # Entry

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entry: Entry | None = None
        self.path: Path | None = None
        self.fmt = "text"
        self.doc: IniDocument | TreeDocument | None = None
        self._original = ""
        self._text_stale = False   # Formular geändert, Textreiter noch alt
        self._form_stale = False   # Text geändert, Formular noch alt
        self._errors: dict[int, str] = {}
        self._rows: list[tuple[QFormLayout, int, Field]] = []
        self._groups: list[tuple[QGroupBox, QFormLayout, str]] = []

        self.title = QLabel()
        f = self.title.font()
        f.setBold(True)
        self.title.setFont(f)
        self.title.setWordWrap(True)
        self.subtitle = QLabel()
        self.subtitle.setWordWrap(True)
        self.subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        # --- Formular
        self.form_filter = QLineEdit()
        self.form_filter.setPlaceholderText("Schlüssel oder Wert suchen …")
        self.form_filter.setClearButtonEnabled(True)
        self.form_filter.textChanged.connect(self._apply_filter)
        self.form_host = QWidget()
        self.form_lay = QVBoxLayout(self.form_host)
        self.form_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.form_host)

        self.add_section = QComboBox()
        self.add_section.setEditable(True)
        self.add_section.setToolTip("Abschnitt (leer = ohne Abschnitt; neuer Name legt ihn an)")
        self.add_key = QLineEdit()
        self.add_key.setPlaceholderText("Schlüssel")
        self.add_value = QLineEdit()
        self.add_value.setPlaceholderText("Wert")
        self.add_btn = QPushButton("Hinzufügen")
        self.add_btn.clicked.connect(self._add_field)
        self.add_value.returnPressed.connect(self._add_field)
        self.add_row = QWidget()
        ar = QHBoxLayout(self.add_row)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.addWidget(self.add_section, 2)
        ar.addWidget(self.add_key, 2)
        ar.addWidget(self.add_value, 3)
        ar.addWidget(self.add_btn)

        self.form_note = QLabel()
        self.form_note.setWordWrap(True)
        form_page = QWidget()
        fl = QVBoxLayout(form_page)
        fl.setContentsMargins(0, 4, 0, 0)
        fl.addWidget(self.form_filter)
        fl.addWidget(scroll, 1)
        fl.addWidget(self.add_row)
        fl.addWidget(self.form_note)

        # --- Text
        self.text = QPlainTextEdit()
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.text.textChanged.connect(self._text_edited)

        self.tabs = QTabWidget()
        self.tabs.addTab(form_page, "Formular")
        self.tabs.addTab(self.text, "Text")
        self.tabs.currentChanged.connect(self._tab_changed)

        # --- Knöpfe
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.b_revert = QPushButton("Verwerfen")
        self.b_revert.clicked.connect(self.revert)
        self.b_save = QPushButton("Speichern")
        self.b_save.clicked.connect(self.save)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.b_revert)
        buttons.addWidget(self.b_save)

        editor = QWidget()
        el = QVBoxLayout(editor)
        el.setContentsMargins(0, 0, 0, 0)
        el.addWidget(self.title)
        el.addWidget(self.subtitle)
        el.addWidget(self.tabs, 1)
        el.addLayout(buttons)

        self.placeholder = QLabel("Eine Datei im Baum anklicken, um sie anzusehen und zu bearbeiten.")
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.placeholder)
        self.stack.addWidget(editor)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)
        self._update_buttons()

    # ------------------------------------------------------------------ öffnen
    def show_message(self, text: str) -> None:
        self.entry = self.path = self.doc = None
        self.placeholder.setText(text)
        self.stack.setCurrentIndex(0)

    def open_entry(self, entry: Entry, display_name: str) -> None:
        if entry.is_command:
            self.show_message("Befehlsausgaben werden beim Abgleich neu erzeugt und lassen sich nicht bearbeiten.")
            return
        if entry.source is None:
            self.show_message("Diese Datei liegt nicht auf diesem Gerät (nur im Speicher bzw. in einer Version) "
                              "und lässt sich hier nicht bearbeiten.")
            return
        text = read_text(entry.source)
        if text is None:
            self.show_message(f"„{display_name}“ ist keine Textdatei, zu groß oder nicht lesbar – "
                              "kann nicht angezeigt werden.")
            return
        self.entry, self.path = entry, entry.source
        self.title.setText(display_name)
        self.fmt = detect_format(entry.source.name, text)
        self._load(text)
        self.stack.setCurrentIndex(1)

    def _load(self, text: str) -> None:
        self._original = text
        self.doc = parse_document(self.fmt, text)
        self.text.blockSignals(True)
        self.text.setPlainText(text)
        self.text.blockSignals(False)
        self._text_stale = self._form_stale = False
        self._errors.clear()
        self.form_filter.clear()
        self._build_form()
        assert self.path is not None
        label = FORMAT_LABELS.get(self.fmt, self.fmt)
        if self.fmt != "text" and self.doc is None:
            label += " – Inhalt fehlerhaft, nur als Text bearbeitbar"
        self.subtitle.setText(f"{self.path}\nFormat: {label}")
        self.tabs.setTabEnabled(TAB_FORM, self.doc is not None)
        self.tabs.setCurrentIndex(TAB_FORM if self.doc is not None else TAB_TEXT)
        self.status.clear()
        self._update_buttons()

    # ------------------------------------------------------------------ Formular
    def _build_form(self) -> None:
        while self.form_lay.count():
            it = self.form_lay.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self._rows.clear()
        self._groups.clear()
        doc = self.doc
        is_ini = isinstance(doc, IniDocument)
        self.add_row.setVisible(is_ini)
        self.form_note.setVisible(isinstance(doc, TreeDocument))
        if isinstance(doc, TreeDocument):
            note = "Bearbeitet werden einfache Werte; Listen und verschachtelte Einträge bleiben erhalten."
            if doc.fmt == "yaml":
                note += " Achtung: Kommentare in der YAML-Datei gehen beim Speichern über das Formular verloren."
            self.form_note.setText(note)
        if doc is None:
            return

        sections = doc.sections()
        self.add_section.clear()
        self.add_section.addItems(sections if "" in sections else [""] + sections)
        if "" not in sections and sections:
            self.add_section.setCurrentIndex(1)
        by_section: dict[str, list[Field]] = {}
        for f in doc.fields:
            by_section.setdefault(f.section, []).append(f)
        if not by_section:
            empty = QLabel("Noch keine Einträge – unten einen hinzufügen." if is_ini else "Keine einfachen Werte.")
            self.form_lay.addWidget(empty)
        for section in sections:
            fields = by_section.get(section)
            if not fields:
                if is_ini and section:
                    box = QGroupBox(f"[{section}]" if is_ini else section)
                    QVBoxLayout(box).addWidget(QLabel("(leer)"))
                    self.form_lay.addWidget(box)
                continue
            title = (f"[{section}]" if section else "Ohne Abschnitt") if is_ini else (section or "Oberste Ebene")
            box = QGroupBox(title)
            form = QFormLayout(box)
            form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            for f in fields:
                form.addRow(self._label(f), self._field_widget(f, is_ini))
                self._rows.append((form, form.rowCount() - 1, f))
            self.form_lay.addWidget(box)
            self._groups.append((box, form, section))
        self.form_lay.addStretch(1)
        self._apply_filter(self.form_filter.text())

    def _label(self, f: Field) -> QLabel:
        lab = QLabel(f.key)
        lab.setToolTip(f"{f.section}.{f.key}" if f.section else f.key)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        return lab

    def _field_widget(self, f: Field, removable: bool) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        if f.kind == "bool":
            cb = QCheckBox(f.value.strip().strip('"'))
            cb.setChecked(f.value.strip().strip('"').lower() in ("true", "yes", "on"))
            cb.toggled.connect(lambda on, f=f, cb=cb: self._bool_changed(f, cb, on))
            h.addWidget(cb, 1)
        else:
            le = QLineEdit(f.value)
            if f.kind == "null":
                le.setPlaceholderText("(leer)")
            le.textEdited.connect(lambda v, f=f, le=le: self._value_changed(f, le, v))
            h.addWidget(le, 1)
        if removable:
            rm = QToolButton()
            rm.setText("✕")
            rm.setToolTip("Eintrag entfernen")
            rm.clicked.connect(lambda _=False, f=f: self._remove_field(f))
            h.addWidget(rm)
        return w

    def _bool_changed(self, f: Field, cb: QCheckBox, on: bool) -> None:
        new = toggle_bool(f.value, on) if isinstance(self.doc, IniDocument) else ("true" if on else "false")
        cb.setText(new.strip('"'))
        self._value_changed(f, None, new)

    def _value_changed(self, f: Field, le: QLineEdit | None, value: str) -> None:
        assert self.doc is not None
        try:
            self.doc.set_value(f.id, value)
        except ValueError as exc:
            self._errors[f.id] = str(exc)
            if le is not None:
                le.setStyleSheet("border: 1px solid #c0392b;")
        else:
            self._errors.pop(f.id, None)
            if le is not None:
                le.setStyleSheet("")
        self._text_stale = True
        self._changed()

    def _remove_field(self, f: Field) -> None:
        assert isinstance(self.doc, IniDocument)
        self.doc.remove(f.id)
        self._errors.pop(f.id, None)
        self._text_stale = True
        self._build_form()
        self._changed()

    def _add_field(self) -> None:
        if not isinstance(self.doc, IniDocument):
            return
        try:
            self.doc.add(self.add_section.currentText().strip(), self.add_key.text(), self.add_value.text())
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.add_key.clear()
        self.add_value.clear()
        self._text_stale = True
        keep = self.add_section.currentText()
        self._build_form()
        self.add_section.setCurrentText(keep)
        self.add_key.setFocus()
        self._changed()

    def _apply_filter(self, text: str) -> None:
        t = text.strip().lower()
        visible: dict[int, int] = {}
        for form, row, f in self._rows:
            on = not t or t in f.key.lower() or t in f.value.lower() or t in f.section.lower()
            form.setRowVisible(row, on)
            visible[id(form)] = visible.get(id(form), 0) + on
        for box, form, _section in self._groups:
            box.setVisible(visible.get(id(form), 0) > 0)

    # ------------------------------------------------------------------ Text
    def _text_edited(self) -> None:
        self._form_stale = True
        self._changed()

    def _tab_changed(self, idx: int) -> None:
        if idx == TAB_TEXT and self._text_stale and self.doc is not None:
            self.text.blockSignals(True)
            self.text.setPlainText(self.doc.render())
            self.text.blockSignals(False)
            self._text_stale = False
        elif idx == TAB_FORM and self._form_stale:
            self.doc = parse_document(self.fmt, self.text.toPlainText())
            self._errors.clear()
            self._form_stale = False
            self._build_form()
            if self.doc is None:
                self.status.setText("Der Text lässt sich gerade nicht als Formular lesen – bitte im Text korrigieren.")
                self.tabs.setCurrentIndex(TAB_TEXT)

    def current_text(self) -> str:
        if self._text_stale and self.doc is not None:
            return self.doc.render()
        return self.text.toPlainText()

    # ------------------------------------------------------------------ Speichern
    @property
    def dirty(self) -> bool:
        return self.path is not None and self.current_text() != self._original

    def _changed(self) -> None:
        if self._errors:
            self.status.setText(next(iter(self._errors.values())))
        elif self.dirty:
            self.status.setText("Ungespeicherte Änderungen")
        else:
            self.status.clear()
        self._update_buttons()

    def _update_buttons(self) -> None:
        d = self.dirty
        self.b_save.setEnabled(d and not self._errors)
        self.b_revert.setEnabled(d)
        bold = QFont(self.b_save.font())
        bold.setBold(d)
        self.b_save.setFont(bold)

    def revert(self) -> None:
        if self.path is not None:
            self._load(self._original)

    def save(self) -> bool:
        if self.path is None or self.entry is None:
            return True
        if self._errors:
            QMessageBox.warning(self, "Nicht gespeichert", "Bitte zuerst die markierten Felder korrigieren.")
            return False
        text = self.current_text()
        try:
            write_atomic(self.path, text)
            st = self.path.stat()
        except OSError as exc:
            QMessageBox.warning(self, "Fehler", f"Konnte nicht speichern: {exc}")
            return False
        self.entry.size = st.st_size
        self.entry.mtime = st.st_mtime
        self.entry.sha256 = ""
        tab = self.tabs.currentIndex()
        self._load(text)
        if self.tabs.isTabEnabled(tab):
            self.tabs.setCurrentIndex(tab)
        self.status.setText("Gespeichert.")
        self.saved.emit(self.entry)
        return True

    def confirm_leave(self) -> bool:
        """Vor dem Wechsel zu einer anderen Datei: speichern, verwerfen oder abbrechen."""
        if not self.dirty:
            return True
        name = self.title.text()
        ans = QMessageBox.question(
            self, "Ungespeicherte Änderungen", f"Änderungen an „{name}“ speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if ans == QMessageBox.StandardButton.Save:
            return self.save()
        if ans == QMessageBox.StandardButton.Discard:
            self.revert()
            return True
        return False
