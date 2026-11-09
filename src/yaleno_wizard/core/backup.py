"""Sicherung: ausgewählte Einträge in einen neuen Snapshot hochladen."""

from __future__ import annotations

import io
import posixpath
from dataclasses import dataclass, field, replace
from datetime import datetime

from ..catalog.model import Catalog
from ..storage.base import Storage
from .commands import run_backup_command
from .entry import Entry, human_size
from .manifest import MANIFEST, SNAPSHOT_FMT, Manifest, sanitize_host, snapshot_dir
from .reporter import Reporter


@dataclass
class BackupResult:
    snapshot_path: str
    manifest: Manifest | None = None
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def ok(self) -> bool:
        return self.manifest is not None


def run_backup(
    storage: Storage,
    base: str,
    host: str,
    os_name: str,
    catalog: Catalog,
    entries: list[Entry],
    reporter: Reporter,
    now: datetime | None = None,
) -> BackupResult:
    now = now or datetime.now()
    snapshot = now.strftime(SNAPSHOT_FMT)
    root = snapshot_dir(base, host, snapshot)
    result = BackupResult(snapshot_path=root)

    reporter.log(f"Ziel: {storage.description} → {root}")
    storage.makedirs(root)

    total = sum(e.size for e in entries)
    done = 0
    made_dirs: set[str] = {root}
    saved: list[Entry] = []

    def ensure_parent(remote: str) -> None:
        parent = posixpath.dirname(remote)
        if parent not in made_dirs:
            storage.makedirs(parent)
            # alle Vorfahren als vorhanden merken
            p = parent
            while p and p not in made_dirs:
                made_dirs.add(p)
                p = posixpath.dirname(p)

    for idx, entry in enumerate(entries, start=1):
        if reporter.cancelled():
            result.cancelled = True
            break
        remote = posixpath.join(root, entry.remote_relpath())
        reporter.progress(done, total, f"[{idx}/{len(entries)}] {entry.logical}")
        try:
            ensure_parent(remote)
            if entry.is_command:
                cat = catalog.get(entry.category)
                item = cat.item(entry.item) if cat else None
                if item is None:
                    raise RuntimeError("Unbekannter Befehls-Eintrag")
                data = run_backup_command(item)
                sha = storage.upload_stream(io.BytesIO(data), remote, cancelled=reporter.cancelled)
                saved.append(replace(entry, size=len(data), sha256=sha, mtime=now.timestamp(), source=None))
                reporter.log(f"Befehl ausgeführt: {' '.join(item.backup_cmd)} ({human_size(len(data))})")
            else:
                assert entry.source is not None
                written = 0

                def on_chunk(n: int) -> None:
                    nonlocal written
                    written += n
                    reporter.progress(done + written, total, f"[{idx}/{len(entries)}] {entry.logical}")

                with open(entry.source, "rb") as fh:
                    sha = storage.upload_stream(fh, remote, progress=on_chunk, cancelled=reporter.cancelled)
                saved.append(replace(entry, size=written, sha256=sha, source=None))
            done += entry.size
        except InterruptedError:
            result.cancelled = True
            break
        except Exception as exc:  # Datei gesperrt, keine Rechte, Netzwerk …
            msg = str(exc) or exc.__class__.__name__
            result.failed.append((entry.logical, msg))
            reporter.log(f"FEHLER {entry.logical}: {msg}")
            done += entry.size

    if result.cancelled:
        reporter.log("Abgebrochen – der unvollständige Snapshot wird nicht als gültig markiert.")
        return result

    used_cats = {e.category for e in saved}
    manifest = Manifest(
        host=sanitize_host(host),
        os=os_name,
        snapshot=snapshot,
        created=now.isoformat(timespec="seconds"),
        categories={c.id: c.meta() for c in catalog.categories if c.id in used_cats},
        entries=saved,
        errors=[f"{p}: {m}" for p, m in result.failed],
    )
    storage.write_bytes_atomic(posixpath.join(root, MANIFEST), manifest.to_json().encode("utf-8"))
    result.manifest = manifest
    reporter.progress(total, total, "fertig")
    reporter.log(
        f"Sicherung abgeschlossen: {len(saved)} Dateien, {human_size(manifest.total_size)}"
        + (f", {len(result.failed)} Fehler" if result.failed else "")
    )
    return result
