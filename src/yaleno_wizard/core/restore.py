"""Wiederherstellung: Einträge aus einem Snapshot auf den lokalen Rechner holen."""

from __future__ import annotations

import hashlib
import io
import os
import posixpath
import shutil
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from ..catalog.model import Catalog
from ..catalog.placeholders import PathMapper, split_logical
from ..storage.base import Storage
from .commands import run_restore_command
from .entry import Entry, human_size
from .manifest import Manifest
from .reporter import Reporter


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


def _safe_parts(rest: str) -> list[str] | None:
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
    parts = _safe_parts("/".join(rel))
    return staging.joinpath(*parts) if parts else None


def plan_restore(
    manifest: Manifest,
    entries: list[Entry],
    mapper: PathMapper,
    catalog: Catalog,
    target_os: str,
    staging_dir: Path,
    run_commands: bool = False,
) -> list[RestoreAction]:
    actions: list[RestoreAction] = []
    same_os = manifest.os == target_os
    for e in entries:
        meta = manifest.categories.get(e.category, {})
        if not same_os and not meta.get("cross_os"):
            actions.append(RestoreAction(e, ActionKind.BLOCKED,
                                         reason=f"nur auf {manifest.os} wiederherstellbar"))
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
        parts = _safe_parts(rest)
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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _keep_both_name(target: Path, snapshot: str) -> Path:
    candidate = target.with_name(f"{target.stem}.yaleno-{snapshot}{target.suffix}")
    n = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem}.yaleno-{snapshot}-{n}{target.suffix}")
        n += 1
    return candidate


def run_restore(
    storage: Storage,
    snapshot_path: str,
    manifest: Manifest,
    actions: list[RestoreAction],
    catalog: Catalog,
    policy: ConflictPolicy,
    reporter: Reporter,
    dry_run: bool = False,
    apply_mode: bool | None = None,
) -> RestoreResult:
    if apply_mode is None:
        apply_mode = os.name != "nt" and manifest.os == "linux"
    res = RestoreResult()
    todo = [a for a in actions if a.kind != ActionKind.BLOCKED]
    res.skipped += len(actions) - len(todo)
    total = sum(a.entry.size for a in todo)
    done = 0
    prefix = "[Probelauf] " if dry_run else ""

    for idx, a in enumerate(todo, start=1):
        if reporter.cancelled():
            res.cancelled = True
            break
        e = a.entry
        remote = posixpath.join(snapshot_path, e.remote_relpath())
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
                    sha = storage.download_stream(remote, buf, cancelled=reporter.cancelled)
                    if e.sha256 and sha != e.sha256:
                        raise RuntimeError("Prüfsumme stimmt nicht")
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
                if e.sha256 and target.stat().st_size == e.size and _sha256_file(target) == e.sha256:
                    res.unchanged += 1
                    done += e.size
                    continue
                if policy == ConflictPolicy.SKIP:
                    reporter.log(f"übersprungen (existiert): {target}")
                    res.skipped += 1
                    done += e.size
                    continue
                if policy == ConflictPolicy.KEEP_BOTH:
                    target = _keep_both_name(target, manifest.snapshot)

            if dry_run:
                reporter.log(f"{prefix}{target} ({human_size(e.size)})")
                res.written += 1
                done += e.size
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".yaleno-part")
            got = 0

            def on_chunk(n: int) -> None:
                nonlocal got
                got += n
                reporter.progress(done + got, total, label)

            try:
                with open(tmp, "wb") as fh:
                    sha = storage.download_stream(remote, fh, progress=on_chunk, cancelled=reporter.cancelled)
                if e.sha256 and sha != e.sha256:
                    raise RuntimeError("Prüfsumme stimmt nicht – Datei auf dem Server beschädigt?")
                if apply_mode:
                    os.chmod(tmp, e.mode & 0o7777)
                os.replace(tmp, target)
            except BaseException:
                tmp.unlink(missing_ok=True)
                raise
            if e.mtime:
                os.utime(target, (e.mtime, e.mtime))
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
