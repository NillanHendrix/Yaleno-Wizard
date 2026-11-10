"""Konfigurationsdateien lesen und als Formularfelder bearbeiten.

Zwei Arten von Dokumenten:

* :class:`IniDocument` – zeilenbasiert für INI, KDE-rc, gitconfig, TOML (einfache Schlüssel)
  und ``schlüssel=wert``-Dateien. Beim Zurückschreiben bleiben Kommentare, Reihenfolge,
  Einrückung und Leerzeichen um das Trennzeichen erhalten; nur geänderte Zeilen werden neu
  geschrieben.
* :class:`TreeDocument` – JSON und YAML. Bearbeitet werden die einfachen Werte (Text, Zahl,
  Wahrheitswert, leer); verschachtelte Strukturen bleiben unverändert. YAML-Kommentare gehen
  beim Speichern verloren (PyYAML kennt sie nicht).

Die Felder werden über :class:`Field` beschrieben; die Oberfläche baut daraus ein Formular.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_EDIT_SIZE = 2 * 1024 * 1024  # größere Dateien werden nicht im Editor geöffnet

INI_SUFFIXES = {".ini", ".conf", ".cfg", ".desktop", ".toml", ".properties", ".env", ".service"}
INI_NAMES = {".gitconfig", "gitconfig", ".editorconfig", ".npmrc", ".pypirc", ".wgetrc",
             ".curlrc", "user-dirs.dirs", "mimeapps.list", ".gtkrc-2.0"}
JSON_SUFFIXES = {".json", ".jsonc"}
YAML_SUFFIXES = {".yml", ".yaml"}

TRUE_WORDS = {"true", "yes", "on"}
FALSE_WORDS = {"false", "no", "off"}


@dataclass
class Field:
    """Ein Formularfeld: Abschnitt (Gruppe), Schlüssel und Wert als Text."""

    id: int
    section: str
    key: str
    value: str
    kind: str = "text"   # text | bool | number | null


# ---------------------------------------------------------------- Erkennung
def read_text(path: Path) -> str | None:
    """Liest eine Textdatei oder ``None``, wenn sie binär, zu groß oder nicht lesbar ist."""
    try:
        if path.stat().st_size > MAX_EDIT_SIZE:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" in data[:8192]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def detect_format(name: str, text: str) -> str:
    """``ini`` | ``json`` | ``yaml`` | ``text`` anhand von Dateiname und Inhalt."""
    lower = name.lower()
    suffix = Path(lower).suffix
    if suffix in JSON_SUFFIXES:
        return "json"
    if suffix in YAML_SUFFIXES:
        return "yaml"
    if suffix in INI_SUFFIXES or lower in INI_NAMES or _looks_ini(text):
        return "ini"
    return "text"


def _looks_ini(text: str) -> bool:
    """Mindestens drei Viertel der inhaltlichen Zeilen sind ``[abschnitt]`` oder ``schlüssel=wert``."""
    total = hits = 0
    for line in text.splitlines()[:400]:
        s = line.strip()
        if not s or s[0] in "#;":
            continue
        total += 1
        if _SECTION_RE.match(line) or _KV_RE.match(line):
            hits += 1
    return total >= 1 and hits * 4 >= total * 3


def value_kind(value: str) -> str:
    v = value.strip().strip('"').lower()
    if v in TRUE_WORDS or v in FALSE_WORDS:
        return "bool"
    if re.fullmatch(r"[+-]?\d+(\.\d+)?", v):
        return "number"
    return "text"


def toggle_bool(old: str, checked: bool) -> str:
    """Neuer Wahrheitswert im Stil des alten (``true``/``yes``/``on``, Groß-/Kleinschreibung, Anführungszeichen)."""
    raw = old.strip()
    quoted = len(raw) >= 2 and raw[0] == raw[-1] == '"'
    word = raw.strip('"')
    pairs = {"true": "false", "yes": "no", "on": "off"}
    pairs.update({v: k for k, v in pairs.items()})
    base = word.lower()
    if (base in TRUE_WORDS) == checked:
        new = word
    else:
        new = pairs.get(base, "true" if checked else "false")
        if word.isupper():
            new = new.upper()
        elif word[:1].isupper():
            new = new.capitalize()
    return f'"{new}"' if quoted else new


# ---------------------------------------------------------------- INI
_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*(?:[#;].*)?$")
_KV_RE = re.compile(r"^(\s*)([^=:\s#;\[][^=:]*?)(\s*[=:]\s*|\s+=\s*)(.*)$")


@dataclass
class _Line:
    text: str
    section: str = ""
    field: Field | None = None
    prefix: str = ""      # Einrückung + Schlüssel + Trennzeichen


@dataclass
class IniDocument:
    lines: list[_Line] = field(default_factory=list)
    newline: str = "\n"
    trailing_newline: bool = True
    _next_id: int = 0

    @classmethod
    def parse(cls, text: str) -> "IniDocument":
        doc = cls()
        doc.newline = "\r\n" if "\r\n" in text else "\n"
        doc.trailing_newline = text.endswith(("\n", "\r"))
        section = ""
        for raw in text.splitlines():
            m = _SECTION_RE.match(raw)
            if m:
                section = m.group(1).strip()
                doc.lines.append(_Line(raw, section))
                continue
            s = raw.strip()
            km = _KV_RE.match(raw) if s and s[0] not in "#;" else None
            if km:
                indent, key, sep, value = km.groups()
                f = Field(doc._new_id(), section, key.strip(), value, value_kind(value))
                doc.lines.append(_Line(raw, section, f, indent + key + sep))
            else:
                doc.lines.append(_Line(raw, section))
        return doc

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    @property
    def fields(self) -> list[Field]:
        return [ln.field for ln in self.lines if ln.field is not None]

    def sections(self) -> list[str]:
        out: list[str] = []
        for ln in self.lines:
            if ln.section not in out:
                out.append(ln.section)
        if "" in out and not any(ln.field and ln.section == "" for ln in self.lines):
            out.remove("")
        return out

    def _line_of(self, fid: int) -> _Line:
        for ln in self.lines:
            if ln.field is not None and ln.field.id == fid:
                return ln
        raise KeyError(fid)

    def set_value(self, fid: int, value: str) -> None:
        if "\n" in value or "\r" in value:
            raise ValueError("Ein Wert darf keinen Zeilenumbruch enthalten.")
        ln = self._line_of(fid)
        assert ln.field is not None
        ln.field.value = value
        ln.text = ln.prefix + value

    def remove(self, fid: int) -> None:
        self.lines.remove(self._line_of(fid))

    def add(self, section: str, key: str, value: str) -> Field:
        key = key.strip()
        if not key or any(c in key for c in "=[]\n\r") or key[0] in "#;":
            raise ValueError("Ungültiger Schlüssel.")
        if "\n" in value or "\r" in value:
            raise ValueError("Ein Wert darf keinen Zeilenumbruch enthalten.")
        # Stil der vorhandenen Zeilen übernehmen (Einrückung, Trennzeichen)
        sample = next((ln for ln in self.lines if ln.field and ln.section == section), None)
        sample = sample or next((ln for ln in self.lines if ln.field), None)
        if sample is not None:
            m = _KV_RE.match(sample.text)
            indent, sep = (m.group(1), m.group(3)) if m else ("", "=")
        else:
            indent, sep = "", "="
        prefix = indent + key + sep
        f = Field(self._new_id(), section, key, value, value_kind(value))
        new = _Line(prefix + value, section, f, prefix)

        idx = None
        for i, ln in enumerate(self.lines):
            if ln.section == section:
                if ln.field is not None or _SECTION_RE.match(ln.text):
                    idx = i + 1
        if idx is None:
            if section:
                if self.lines and self.lines[-1].text.strip():
                    self.lines.append(_Line("", self.lines[-1].section))
                self.lines.append(_Line(f"[{section}]", section))
            idx = len(self.lines) if section else 0
        self.lines.insert(idx, new)
        return f

    def render(self) -> str:
        text = self.newline.join(ln.text for ln in self.lines)
        if self.trailing_newline and self.lines:
            text += self.newline
        return text


# ---------------------------------------------------------------- JSON / YAML
@dataclass
class TreeDocument:
    data: Any
    fmt: str                     # json | yaml
    indent: int = 2
    fields: list[Field] = field(default_factory=list)
    _paths: dict[int, tuple] = field(default_factory=dict)

    @classmethod
    def parse(cls, text: str, fmt: str) -> "TreeDocument":
        if fmt == "json":
            data = json.loads(text) if text.strip() else {}
            m = re.search(r"\n([ \t]+)\S", text)
            indent = len(m.group(1).expandtabs(4)) if m else 2
        else:
            import yaml
            data = yaml.safe_load(text) if text.strip() else {}
            indent = 2
        doc = cls(data, fmt, indent or 2)
        doc._collect(data, ())
        return doc

    def _collect(self, node: Any, path: tuple) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                self._collect(v, path + (k,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                self._collect(v, path + (i,))
        else:
            fid = len(self.fields) + 1
            section = ".".join(str(p) for p in path[:-1])
            key = f"[{path[-1]}]" if path and isinstance(path[-1], int) else str(path[-1]) if path else "(Wert)"
            if isinstance(node, bool):
                kind, value = "bool", "true" if node else "false"
            elif isinstance(node, (int, float)):
                kind, value = "number", repr(node)
            elif node is None:
                kind, value = "null", ""
            else:
                kind, value = "text", str(node)
            self.fields.append(Field(fid, section, key, value, kind))
            self._paths[fid] = path

    def sections(self) -> list[str]:
        out: list[str] = []
        for f in self.fields:
            if f.section not in out:
                out.append(f.section)
        return out

    def set_value(self, fid: int, value: str) -> None:
        f = next(x for x in self.fields if x.id == fid)
        if f.kind == "bool":
            new: Any = value.strip().lower() in TRUE_WORDS
        elif f.kind == "number":
            try:
                new = int(value)
            except ValueError:
                try:
                    new = float(value)
                except ValueError:
                    raise ValueError(f"„{f.key}“ muss eine Zahl sein.") from None
        elif f.kind == "null":
            new = None if value == "" else value
        else:
            new = value
        path = self._paths[fid]
        if not path:
            self.data = new
        else:
            node = self.data
            for p in path[:-1]:
                node = node[p]
            node[path[-1]] = new
        f.value = value

    def render(self) -> str:
        if self.fmt == "json":
            return json.dumps(self.data, indent=self.indent, ensure_ascii=False) + "\n"
        import yaml
        return yaml.safe_dump(self.data, allow_unicode=True, sort_keys=False, default_flow_style=False)


def parse_document(fmt: str, text: str) -> IniDocument | TreeDocument | None:
    """Formular-Dokument zum Format oder ``None`` (reiner Text / nicht lesbar)."""
    try:
        if fmt == "ini":
            return IniDocument.parse(text)
        if fmt in ("json", "yaml"):
            return TreeDocument.parse(text, fmt)
    except Exception:
        return None
    return None
