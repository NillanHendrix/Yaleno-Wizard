"""Löst Kategorien in konkrete Dateien auf."""

from __future__ import annotations

import glob
import os
import stat
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Callable, Iterable

from ..catalog.model import GLOBAL_EXCLUDES, Catalog, Category, Item
from ..catalog.placeholders import PathMapper, split_logical
from .entry import Entry


@dataclass
class ScanResult:
    entries: list[Entry] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (pfad, grund)

    def for_category(self, cat_id: str) -> list[Entry]:
        return [e for e in self.entries if e.category == cat_id]

    def totals(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for e in self.entries:
            n, s = out.get(e.category, (0, 0))
            out[e.category] = (n + 1, s + e.size)
        return out


def _excluded(name: str, rel: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if "/" in pat:
            if fnmatchcase(rel, pat) or fnmatchcase(rel, "*/" + pat):
                return True
        elif fnmatchcase(name, pat):
            return True
    return False


class Scanner:
    def __init__(
        self,
        mapper: PathMapper,
        progress: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ):
        self.mapper = mapper
        self.progress = progress or (lambda _msg: None)
        self.cancelled = cancelled or (lambda: False)

    def scan(self, catalog: Catalog, category_ids: Iterable[str] | None = None) -> ScanResult:
        wanted = set(category_ids) if category_ids is not None else None
        result = ScanResult()
        seen: set[str] = set()
        cats = [c for c in catalog.categories if wanted is None or c.id in wanted]
        # Dateien zuerst den spezifischen Kategorien zuordnen.
        for cat in sorted(cats, key=lambda c: c.claim_priority):
            if self.cancelled():
                break
            self.progress(f"Durchsuche: {cat.name}")
            for item in cat.items:
                if self.cancelled():
                    break
                if item.kind == "command":
                    if item.command_available:
                        result.entries.append(
                            Entry(category=cat.id, logical=item.command_logical, item=item.id, mode=0o600)
                        )
                    continue
                self._scan_item(cat, item, result, seen)
        order = {c.id: i for i, c in enumerate(catalog.categories)}
        result.entries.sort(key=lambda e: (order.get(e.category, 999), e.logical.lower()))
        return result

    # ------------------------------------------------------------------
    def _scan_item(self, cat: Category, item: Item, result: ScanResult, seen: set[str]) -> None:
        excludes = GLOBAL_EXCLUDES + item.excludes
        for logical_pattern in item.paths:
            ph, rest = split_logical(logical_pattern)
            base = self.mapper.base(ph)
            if base is None:
                continue
            if any(ch in rest for ch in "*?["):
                pattern = os.path.join(glob.escape(str(base)), *rest.split("/"))
                matches = sorted(Path(p) for p in glob.glob(pattern, include_hidden=True))
            else:
                p = base / rest if rest else base
                matches = [p] if os.path.lexists(p) else []
            for path in matches:
                rel = path.relative_to(base).as_posix() if path != base else ""
                if rel and _excluded(path.name, rel, excludes):
                    continue
                self._add_path(cat, item, ph, base, path, excludes, result, seen)

    def _add_path(self, cat, item, ph, base: Path, path: Path, excludes, result: ScanResult, seen) -> None:
        try:
            st = path.lstat()
        except OSError as exc:
            result.skipped.append((str(path), exc.strerror or str(exc)))
            return
        if stat.S_ISLNK(st.st_mode):
            result.skipped.append((str(path), "symbolischer Link (nicht gesichert)"))
            return
        if stat.S_ISREG(st.st_mode):
            self._add_file(cat, item, ph, base, path, st, result, seen)
            return
        if not stat.S_ISDIR(st.st_mode):
            return
        for dirpath, dirnames, filenames in os.walk(path, onerror=lambda e: result.skipped.append(
            (getattr(e, "filename", "?") or "?", e.strerror or str(e))
        )):
            if self.cancelled():
                return
            dp = Path(dirpath)
            rel_dir = dp.relative_to(base).as_posix() if dp != base else ""
            dirnames[:] = sorted(
                d for d in dirnames
                if not _excluded(d, f"{rel_dir}/{d}".lstrip("/"), excludes)
                and not (dp / d).is_symlink()
            )
            for fn in sorted(filenames):
                if _excluded(fn, f"{rel_dir}/{fn}".lstrip("/"), excludes):
                    continue
                fp = dp / fn
                try:
                    fst = fp.lstat()
                except OSError as exc:
                    result.skipped.append((str(fp), exc.strerror or str(exc)))
                    continue
                if stat.S_ISREG(fst.st_mode):
                    self._add_file(cat, item, ph, base, fp, fst, result, seen)
                elif stat.S_ISLNK(fst.st_mode):
                    result.skipped.append((str(fp), "symbolischer Link (nicht gesichert)"))

    def _add_file(self, cat, item, ph, base: Path, path: Path, st, result: ScanResult, seen) -> None:
        key = os.path.normcase(str(path))
        if key in seen:
            return
        seen.add(key)
        if not os.access(path, os.R_OK):
            result.skipped.append((str(path), "keine Leserechte"))
            return
        rel = path.relative_to(base).as_posix()
        logical = f"{{{ph}}}/{rel}" if rel != "." else f"{{{ph}}}"
        result.entries.append(Entry(
            category=cat.id,
            logical=logical,
            item=item.id,
            size=st.st_size,
            mtime=st.st_mtime,
            mode=stat.S_IMODE(st.st_mode),
            source=path,
        ))
