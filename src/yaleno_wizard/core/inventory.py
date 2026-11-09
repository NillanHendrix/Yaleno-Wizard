"""Bestand-Textdatei: Export und Import der Dateiauswahl.

Format (UTF-8, eine Angabe pro Zeile)::

    # Yaleno Wizard Bestand v1
    # host: niko-pc  os: linux  ...
    [personal]
    {DOCUMENTS}/Rechnungen/          ← Ordner (alles darunter)
    {PICTURES}/Urlaub/IMG_0001.jpg   ← einzelne Datei
    {DOWNLOADS}/*.iso                ← Muster (* ? [])
    !{DOCUMENTS}/Rechnungen/alt/     ← ausschließen

Zeilen mit ``#`` sind Kommentare, ``[id]`` beginnt eine Kategorie.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from fnmatch import fnmatchcase
from typing import Iterable

from .entry import Entry, human_size

HEADER = "# Yaleno Wizard Bestand v1"


@dataclass
class Rule:
    category: str
    pattern: str
    exclude: bool = False
    line: int = 0

    @property
    def is_dir(self) -> bool:
        return self.pattern.endswith("/")

    @property
    def is_glob(self) -> bool:
        return any(c in self.pattern for c in "*?[")

    def matches(self, logical: str) -> bool:
        if self.is_dir:
            return logical.startswith(self.pattern)
        if self.is_glob:
            return fnmatchcase(logical, self.pattern)
        return logical == self.pattern

    def __str__(self) -> str:
        return f"{'!' if self.exclude else ''}{self.pattern}"


@dataclass
class Inventory:
    rules: list[Rule] = field(default_factory=list)
    meta: dict[str, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        seen: list[str] = []
        for r in self.rules:
            if r.category not in seen:
                seen.append(r.category)
        return seen


# --------------------------------------------------------------------- export
def export_inventory(
    entries: Iterable[Entry],
    category_names: dict[str, str] | None = None,
    meta: dict[str, str] | None = None,
) -> str:
    entries = list(entries)
    category_names = category_names or {}
    lines = [HEADER]
    info = {"erstellt": datetime.now().isoformat(timespec="seconds"), **(meta or {})}
    lines.append("# " + "  ".join(f"{k}: {v}" for k, v in info.items() if v))
    lines.append("# Format: [kategorie] | Pfad = Datei | Pfad/ = ganzer Ordner | * ? = Muster | !Pfad = ausschließen")
    by_cat: dict[str, list[Entry]] = {}
    for e in entries:
        by_cat.setdefault(e.category, []).append(e)
    for cat, items in by_cat.items():
        total = sum(e.size for e in items)
        lines.append("")
        lines.append(f"# {category_names.get(cat, cat)} – {len(items)} Dateien, {human_size(total)}")
        lines.append(f"[{cat}]")
        for e in sorted(items, key=lambda x: x.logical.lower()):
            lines.append(e.logical)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- import
def parse_inventory(text: str) -> Inventory:
    inv = Inventory()
    current: str | None = None
    for no, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if no <= 3 and ":" in stripped:
                for part in stripped.lstrip("# ").split("  "):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        inv.meta[k.strip()] = v.strip()
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            current = stripped[1:-1].strip()
            continue
        if current is None:
            inv.errors.append(f"Zeile {no}: Eintrag ohne vorherige [kategorie]: {stripped}")
            continue
        exclude = stripped.startswith("!")
        pattern = stripped[1:].lstrip() if exclude else line.lstrip()
        if not (pattern.startswith("{") or pattern.startswith("@cmd/") or pattern.startswith("*")):
            inv.errors.append(f"Zeile {no}: Pfad muss mit einem Platzhalter wie {{HOME}} beginnen: {pattern}")
            continue
        inv.rules.append(Rule(category=current, pattern=pattern, exclude=exclude, line=no))
    return inv


@dataclass
class ApplyResult:
    selected: set[tuple[str, str]]
    unmatched: list[Rule]
    missing_categories: list[str]


def apply_inventory(inv: Inventory, entries: Iterable[Entry]) -> ApplyResult:
    """Ermittelt, welche der verfügbaren Einträge laut Bestand ausgewählt sind."""
    entries = list(entries)
    available_cats = {e.category for e in entries}
    by_cat: dict[str, list[Rule]] = {}
    for r in inv.rules:
        by_cat.setdefault(r.category, []).append(r)

    selected: set[tuple[str, str]] = set()
    used: set[int] = set()
    for e in entries:
        rules = by_cat.get(e.category)
        if not rules:
            continue
        included = False
        for r in rules:
            if r.matches(e.logical):
                used.add(id(r))
                if r.exclude:
                    included = False
                    break
                included = True
        if included:
            selected.add(e.key)

    unmatched = [r for r in inv.rules if id(r) not in used and not r.exclude]
    missing = [c for c in inv.categories if c not in available_cats]
    return ApplyResult(selected=selected, unmatched=unmatched, missing_categories=missing)
