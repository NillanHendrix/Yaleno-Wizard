"""Wiederherstellung: Einträge aus einer beliebigen Version des Speichers auf dieses Gerät holen."""

from __future__ import annotations

import io
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ..catalog.model import Catalog
from ..catalog.placeholders import PathMapper, split_logical
from ..storage.base import ProgressCallback
from .commands import run_restore_command
from .entry import Entry, human_size
from .reporter import Reporter
from .store import sha256_file

if TYPE_CHECKING:
    from .store import Revision, Store


class ConflictPolicy(str, Enum):
    SKIP = "skip"
    OVERWRITE = "overwrite"
    KEEP_BOTH = "keep_both"


class ActionKind(str, Enum):
    FILE = "file"          # an den Originalort
    STAGING = "staging"    # in den Ablageordner
    COMMAND = "command"    # per Befehl einspielen (dconf load, reg import, winget import)
    BLOCKED = "blocked"    # nicht möglich (anderes OS, ungültiger Pfad)


@dataclass
class RestoreAction:
    entry: Entry
    kind: ActionKind
    target: Path | None = None
    reason: str = ""

    @property
    def exists(self) -> bool:
        return self.target is not None and self.target.exists()


@dataclass
class RestoreResult:
    written: int = 0
    unchanged: int = 0
    skipped: int = 0
    commands: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False


def safe_parts(rest: str) -> list[str] | None:
    """Zerlegt einen relativen Pfad und lehnt Pfad-Ausbrüche ab (Schutz vor manipulierten Manifesten)."""
    parts = [p for p in rest.split("/") if p not in ("", ".")]
    for p in parts:
        if p == "..":
            return None
        if os.name == "nt" and ("\\" in p or ":" in p):
            return None
    return parts


def _staging_target(staging: Path, entry: Entry) -> Path | None:
    rel = entry.remote_relpath().split("/")[1:]  # "files/" abschneiden → <kat>/<PH>/...
    parts = safe_parts("/".join(rel))
    return staging.joinpath(*parts) if parts else None


def plan_restore(
    revision: Revision,
    entries: list[Entry],
    mapper: PathMapper,
    catalog: Catalog,
    target_os: str,
    staging_dir: Path,
    run_commands: bool = False,
) -> list[RestoreAction]:
    actions: list[RestoreAction] = []
    for e in entries:
        meta = revision.categories.get(e.category, {})
        origin = revision.entry_os(e)
        same_os = origin is None or origin == target_os
        if not same_os and not meta.get("cross_os"):
            actions.append(RestoreAction(e, ActionKind.BLOCKED,
                                         reason=f"nur auf {origin} wiederherstellbar"))
            continue

        if e.is_command:
            cat = catalog.get(e.category) if same_os else None
            item = cat.item(e.item) if cat else None
            if run_commands and item and item.restore_cmd and shutil.which(item.restore_cmd[0]):
                actions.append(RestoreAction(e, ActionKind.COMMAND, reason=" ".join(item.restore_cmd)))
            else:
                t = _staging_target(staging_dir, e)
                actions.append(RestoreAction(e, ActionKind.STAGING, t, "Befehlsausgabe als Datei")
                               if t else RestoreAction(e, ActionKind.BLOCKED, reason="ungültiger Pfad"))
            continue

        try:
            ph, rest = split_logical(e.logical)
        except ValueError:
            actions.append(RestoreAction(e, ActionKind.BLOCKED, reason="ungültiger Pfad"))
            continue
        parts = safe_parts(rest)
        if parts is None:
            actions.append(RestoreAction(e, ActionKind.BLOCKED, reason="ungültiger Pfad"))
            continue

        base = mapper.base(ph)
        if meta.get("requires_admin") or base is None:
            t = _staging_target(staging_dir, e)
            why = "benötigt Admin-Rechte" if meta.get("requires_admin") else f"Ordner {{{ph}}} gibt es hier nicht"
            actions.append(RestoreAction(e, ActionKind.STAGING, t, why) if t
                           else RestoreAction(e, ActionKind.BLOCKED, reason="ungültiger Pfad"))
            continue
        actions.append(RestoreAction(e, ActionKind.FILE, base.joinpath(*parts)))
    return actions


def _keep_both_name(target: Path, tag: str) -> Path:
    candidate = target.with_name(f"{target.stem}.yaleno-{tag}{target.suffix}")
    n = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}.yaleno-{tag}-{n}{target.suffix}")
        n += 1
    return candidate


def write_local(
    store: Store,
    e: Entry,
    target: Path,
    apply_mode: bool,
    progress: ProgressCallback | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> None:
    """Lädt einen Inhalt aus dem Speicher und ersetzt target atomar (inkl. Rechte und Zeitstempel)."""
    if target.is_dir():
        raise RuntimeError(f"Am Ziel existiert ein Ordner: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".yaleno-part")
    try:
        with open(tmp, "wb") as fh:
            store.get_object(e.sha256, fh, progress=progress, cancelled=cancelled)
        if apply_mode:
            os.chmod(tmp, e.mode & 0o7777)
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if e.mtime:
        os.utime(target, (e.mtime, e.mtime))


def run_restore(
    store: Store,
    revision: Revision,
    actions: list[RestoreAction],
    catalog: Catalog,
    policy: ConflictPolicy,
    reporter: Reporter,
    dry_run: bool = False,
    apply_mode: bool | None = None,
) -> RestoreResult:
    res = RestoreResult()
    todo = [a for a in actions if a.kind != ActionKind.BLOCKED]
    res.skipped += len(actions) - len(todo)
    total = sum(a.entry.size for a in todo)
    done = 0
    prefix = "[Probelauf] " if dry_run else ""
    tag = f"v{revision.number}"

    for idx, a in enumerate(todo, start=1):
        if reporter.cancelled():
            res.cancelled = True
            break
        e = a.entry
        label = f"[{idx}/{len(todo)}] {e.logical}"
        reporter.progress(done, total, label)
        try:
            if a.kind == ActionKind.COMMAND:
                if dry_run:
                    reporter.log(f"{prefix}würde ausführen: {a.reason}")
                else:
                    cat = catalog.get(e.category)
                    item = cat.item(e.item) if cat else None
                    buf = io.BytesIO()
                    store.get_object(e.sha256, buf, cancelled=reporter.cancelled)
                    out = run_restore_command(item, buf.getvalue())  # type: ignore[arg-type]
                    reporter.log(f"Befehl ausgeführt: {a.reason}" + (f"\n{out}" if out else ""))
                res.commands += 1
                done += e.size
                continue

            target = a.target
            assert target is not None
            if target.exists():
                if target.is_dir():
                    raise RuntimeError(f"Am Ziel existiert ein Ordner: {target}")
                if e.sha256 and target.stat().st_size == e.size and sha256_file(target) == e.sha256:
                    res.unchanged += 1
                    done += e.size
                    continue
                if policy == ConflictPolicy.SKIP:
                    reporter.log(f"übersprungen (existiert): {target}")
                    res.skipped += 1
                    done += e.size
                    continue
                if policy == ConflictPolicy.KEEP_BOTH:
                    target = _keep_both_name(target, tag)

            if dry_run:
                reporter.log(f"{prefix}{target} ({human_size(e.size)})")
                res.written += 1
                done += e.size
                continue

            got = 0

            def on_chunk(n: int) -> None:
                nonlocal got
                got += n
                reporter.progress(done + got, total, label)

            mode_ok = apply_mode if apply_mode is not None else (os.name != "nt" and revision.entry_os(e) != "windows")
            write_local(store, e, target, mode_ok, on_chunk, reporter.cancelled)
            res.written += 1
            done += e.size
        except InterruptedError:
            res.cancelled = True
            break
        except Exception as exc:
            msg = str(exc) or exc.__class__.__name__
            res.failed.append((e.logical, msg))
            reporter.log(f"FEHLER {e.logical}: {msg}")
            done += e.size

    reporter.progress(total, total, "fertig")
    summary = (
        f"{prefix}Wiederherstellung {'abgebrochen' if res.cancelled else 'abgeschlossen'}: "
        f"{res.written} geschrieben, {res.unchanged} unverändert, {res.skipped} übersprungen"
        + (f", {res.commands} Befehle" if res.commands else "")
        + (f", {len(res.failed)} Fehler" if res.failed else "")
    )
    reporter.log(summary)
    return res
