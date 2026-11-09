"""Abgleich zwischen diesem Gerät und dem zentralen Speicher.

Für jede Datei werden drei Stände verglichen:

* **lokal**  – was jetzt auf diesem Gerät liegt
* **Speicher** – die aktuelle Version im zentralen Speicher
* **Basis**  – der Stand beim letzten erfolgreichen Abgleich dieses Geräts (lokal gemerkt)

Daraus folgt, wer etwas geändert hat: nur das Gerät → hochladen, nur der Speicher →
herunterladen, beide → Konflikt. Gelöschte Dateien werden ebenso weitergegeben. Nichts
geht verloren: alte Stände bleiben im Versionsverlauf, bei Konflikten wird die
unterlegene Fassung als Konfliktkopie neben der Datei abgelegt (und ebenfalls abgeglichen).
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from pathlib import Path

from ..catalog.model import Catalog
from ..catalog.placeholders import PathMapper, split_logical
from .commands import run_backup_command
from .entry import Entry, human_size
from .reporter import Reporter
from .restore import safe_parts, write_local
from .store import (
    Revision, Store, TreeKey, device_scopes, diff_trees, host_scope, is_push_only, sanitize_host,
    scope_for, sha256_file, tree_key,
)


class Op(str, Enum):
    UPLOAD = "upload"              # lokal neu/geändert → Speicher
    DOWNLOAD = "download"          # im Speicher neu/geändert → Gerät
    DELETE_REMOTE = "delete_remote"  # auf dem Gerät gelöscht → aus aktuellem Stand entfernen
    DELETE_LOCAL = "delete_local"  # im Speicher gelöscht → auf dem Gerät löschen
    CONFLICT = "conflict"          # auf beiden Seiten unterschiedlich geändert
    COMMAND = "command"            # Befehl ausführen und Ausgabe sichern


OP_LABELS = {
    Op.UPLOAD: "Hochladen",
    Op.DOWNLOAD: "Herunterladen",
    Op.DELETE_REMOTE: "Im Speicher löschen",
    Op.DELETE_LOCAL: "Auf diesem Gerät löschen",
    Op.CONFLICT: "Konflikt",
    Op.COMMAND: "Befehl sichern",
}


class ConflictWinner(str, Enum):
    NEWER = "newer"    # jüngere Änderung gewinnt
    LOCAL = "local"    # dieses Gerät gewinnt
    REMOTE = "remote"  # Speicher gewinnt


# ---------------------------------------------------------------------- Basis
@dataclass
class BaseRecord:
    sha256: str
    size: int
    mtime: float


class SyncState:
    """Merkt pro Speicher und Gerät, welcher Stand zuletzt abgeglichen wurde."""

    def __init__(self, path: Path, records: dict[TreeKey, BaseRecord] | None = None, revision: int = 0):
        self.path = path
        self.records = records or {}
        self.revision = revision

    @staticmethod
    def file_for(state_dir: Path, store_id: str, host: str) -> Path:
        return state_dir / f"{store_id}-{sanitize_host(host)}.json"

    @classmethod
    def load(cls, path: Path) -> "SyncState":
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            recs = {
                (r[0], r[1]): BaseRecord(r[2], int(r[3]), float(r[4])) for r in d.get("records", [])
            }
            return cls(path, recs, int(d.get("revision", 0)))
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return cls(path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "revision": self.revision,
            "records": [[k[0], k[1], r.sha256, r.size, r.mtime] for k, r in sorted(self.records.items())],
        }
        tmp = self.path.with_name(self.path.name + ".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)


# ---------------------------------------------------------------------- Plan
@dataclass
class SyncAction:
    op: Op
    key: TreeKey
    category: str
    local: Entry | None = None
    remote: Entry | None = None
    target: Path | None = None
    reason: str = ""

    @property
    def logical(self) -> str:
        return self.key[1]

    @property
    def size(self) -> int:
        e = self.local if self.op in (Op.UPLOAD, Op.COMMAND) else (self.remote or self.local)
        if self.op == Op.CONFLICT:
            return max(self.local.size if self.local else 0, self.remote.size if self.remote else 0)
        return e.size if e else 0


@dataclass
class SyncPlan:
    head: int
    remote: Revision | None
    actions: list[SyncAction] = field(default_factory=list)
    in_sync: dict[TreeKey, Entry] = field(default_factory=dict)  # lokal == Speicher (Basis aktualisieren)
    forget: set[TreeKey] = field(default_factory=set)            # Basis-Einträge ohne Gegenstück
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def count(self, op: Op) -> int:
        return sum(1 for a in self.actions if a.op == op)

    def by_op(self, op: Op) -> list[SyncAction]:
        return [a for a in self.actions if a.op == op]


def _target(mapper: PathMapper, logical: str) -> Path | None:
    try:
        ph, rest = split_logical(logical)
    except ValueError:
        return None
    parts = safe_parts(rest)
    base = mapper.base(ph)
    if parts is None or base is None or not parts:
        return None
    return base.joinpath(*parts)


def _base_missing(mapper: PathMapper, logical: str) -> bool:
    """Fehlt der Grundordner (z. B. Laufwerk nicht eingehängt)? Dann nichts als „gelöscht“ werten."""
    try:
        ph, _ = split_logical(logical)
    except ValueError:
        return False
    base = mapper.base(ph)
    return base is not None and not base.is_dir()


def plan_sync(
    store: Store,
    local_entries: list[Entry],
    state: SyncState,
    catalog: Catalog,
    mapper: PathMapper,
    os_name: str,
    host: str,
    categories: set[str],
    selected: set[tuple[str, str]] | None,
    remote: Revision | None = None,
    reporter: Reporter | None = None,
) -> SyncPlan:
    """Ermittelt, was zu tun ist. Liest den Speicher, schreibt nichts.

    ``categories``/``selected`` begrenzen den Abgleich; alles außerhalb bleibt unverändert.
    """
    rep = reporter or Reporter()
    if remote is None:
        remote = store.load_head()
    plan = SyncPlan(head=remote.number if remote else 0, remote=remote)
    scopes = device_scopes(os_name, host)

    def wanted(e: Entry) -> bool:
        return e.category in categories and (selected is None or e.key in selected)

    # Lokale Einträge mit Bereich versehen
    local: dict[TreeKey, Entry] = {}
    for e in local_entries:
        if not wanted(e):
            continue
        e = replace(e, scope=scope_for(e, catalog.get(e.category), os_name, host))
        local[tree_key(e)] = e

    remote_tree = remote.tree() if remote else {}
    remote_mine = {k: e for k, e in remote_tree.items() if e.scope in scopes and wanted(e)}

    # Basis-Einträge, die zur aktuellen Auswahl gehören (Kategorie aus lokal/Speicher ableiten)
    known_cat = {k: e.category for k, e in remote_tree.items()}
    known_cat.update({k: e.category for k, e in local.items()})

    keys = set(local) | set(remote_mine)
    for k in state.records:
        if k[0] in scopes and k not in keys:
            cat = known_cat.get(k)
            if cat is None or (cat in categories and (selected is None or (cat, k[1]) in selected)):
                keys.add(k)

    files_to_hash = [k for k in keys if k in local and not local[k].is_command]
    total = sum(local[k].size for k in files_to_hash)
    done = 0

    for idx, k in enumerate(sorted(keys), start=1):
        if rep.cancelled():
            raise InterruptedError("abgebrochen")
        L, R, B = local.get(k), remote_mine.get(k), state.records.get(k)
        push_only = is_push_only(k[0])
        cat = (L or R).category if (L or R) else known_cat.get(k, "")

        # --- Befehle: immer neu ausführen, Ergebnis entscheidet beim Ausführen
        if L is not None and L.is_command:
            plan.actions.append(SyncAction(Op.COMMAND, k, cat, local=L, remote=R))
            continue

        # --- lokale Prüfsumme (nur neu berechnen, wenn Größe/Zeit sich geändert haben)
        if L is not None:
            if B and L.size == B.size and abs(L.mtime - B.mtime) < 1e-3:
                L = replace(L, sha256=B.sha256)
            else:
                rep.progress(done, total, f"Vergleiche {L.logical}")
                try:
                    L = replace(L, sha256=sha256_file(L.source))
                except OSError as exc:
                    plan.skipped.append((L.logical, exc.strerror or str(exc)))
                    continue
            local[k] = L
            done += L.size

        target = _target(mapper, k[1])

        if L is not None and R is not None:
            if L.sha256 == R.sha256:
                plan.in_sync[k] = L
            elif push_only or (B is not None and R.sha256 == B.sha256):
                plan.actions.append(SyncAction(Op.UPLOAD, k, cat, L, R, target))
            elif B is not None and L.sha256 == B.sha256:
                plan.actions.append(SyncAction(Op.DOWNLOAD, k, cat, L, R, target))
            else:
                why = "auf beiden Seiten geändert" if B else "auf beiden Seiten neu, Inhalt verschieden"
                plan.actions.append(SyncAction(Op.CONFLICT, k, cat, L, R, target, why))
        elif L is not None:  # nur lokal
            if B is None or push_only:
                plan.actions.append(SyncAction(Op.UPLOAD, k, cat, L, None, target, "neu"))
            elif L.sha256 == B.sha256:
                plan.actions.append(SyncAction(Op.DELETE_LOCAL, k, cat, L, None, target,
                                               "wurde auf einem anderen Gerät gelöscht"))
            else:
                plan.actions.append(SyncAction(Op.UPLOAD, k, cat, L, None, target,
                                               "anderswo gelöscht, hier aber geändert – bleibt erhalten"))
        elif R is not None:  # nur im Speicher
            if target is not None and os.path.lexists(target) and not push_only:
                # existiert, wurde aber nicht erfasst (Link, keine Rechte, ausgeschlossen) → nicht anfassen
                plan.skipped.append((k[1], "lokal vorhanden, aber nicht abgleichbar"))
                continue
            if B is None:
                if push_only:
                    continue  # Gerätedaten nie automatisch zurückschreiben
                if target is None:
                    plan.skipped.append((k[1], "Ordner gibt es auf diesem Gerät nicht"))
                    continue
                plan.actions.append(SyncAction(Op.DOWNLOAD, k, cat, None, R, target, "neu"))
            elif _base_missing(mapper, k[1]):
                plan.skipped.append((k[1], "Grundordner fehlt auf diesem Gerät (nicht eingehängt?)"))
            elif R.sha256 == B.sha256:
                plan.actions.append(SyncAction(Op.DELETE_REMOTE, k, cat, None, R, target, "hier gelöscht"))
            elif not push_only and target is not None:
                plan.actions.append(SyncAction(Op.DOWNLOAD, k, cat, None, R, target,
                                               "hier gelöscht, anderswo aber geändert – kommt zurück"))
        else:
            plan.forget.add(k)

    rep.progress(total, total, "Vergleich abgeschlossen")
    return plan


# ---------------------------------------------------------------------- Ausführen
@dataclass
class SyncResult:
    uploaded: int = 0
    downloaded: int = 0
    deleted_remote: int = 0
    deleted_local: int = 0
    conflicts: int = 0
    unchanged_commands: int = 0
    revision: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def changes(self) -> int:
        return self.uploaded + self.downloaded + self.deleted_remote + self.deleted_local + self.conflicts


def conflict_name(target: Path, who: str, when: datetime) -> Path:
    stamp = when.strftime("%Y-%m-%d %H%M")
    candidate = target.with_name(f"{target.stem} (Konflikt {who} {stamp}){target.suffix}")
    n = 2
    while candidate.exists():
        candidate = target.with_name(f"{target.stem} (Konflikt {who} {stamp} {n}){target.suffix}")
        n += 1
    return candidate


def _unchanged_since_plan(path: Path, e: Entry) -> bool:
    try:
        st = path.stat()
    except OSError:
        return False
    return st.st_size == e.size and abs(st.st_mtime - e.mtime) < 1e-3


def run_sync(
    store: Store,
    plan: SyncPlan,
    state: SyncState,
    catalog: Catalog,
    mapper: PathMapper,
    os_name: str,
    host: str,
    winner: ConflictWinner,
    reporter: Reporter,
    dry_run: bool = False,
    replan=None,
    now: datetime | None = None,
) -> SyncResult:
    """Führt den Plan aus und schreibt eine neue Version, falls sich der Speicher ändert.

    ``replan`` (optional) wird aufgerufen, wenn sich der Speicher seit der Planung geändert hat.
    """
    now = now or datetime.now()
    res = SyncResult()
    prefix = "[Probelauf] " if dry_run else ""
    host = sanitize_host(host)

    if dry_run:
        for a in plan.actions:
            reporter.log(f"{prefix}{OP_LABELS[a.op]}: {a.logical}" + (f" ({a.reason})" if a.reason else ""))
        reporter.log(f"{prefix}{len(plan.actions)} Aktionen – nichts wurde verändert.")
        res.revision = plan.head
        return res

    with store.locked(host):
        store.ensure_initialized()
        if store.head() != plan.head:
            if replan is None:
                raise RuntimeError("Der Speicher wurde inzwischen geändert – bitte erneut abgleichen.")
            reporter.log("Speicher wurde inzwischen von einem anderen Gerät geändert – vergleiche neu …")
            plan = replan()

        remote = plan.remote
        tree: dict[TreeKey, Entry] = dict(remote.tree()) if remote else {}
        records = state.records
        apply_mode = os.name != "nt"
        total = sum(a.size for a in plan.actions)
        done = 0
        reporter.log(f"Speicher: {store.storage.description} · Version {plan.head or '–'}")

        def upload(e: Entry, label: str) -> Entry:
            nonlocal done
            if e.sha256 and store.has_object(e.sha256):
                if e.source is not None and not _unchanged_since_plan(e.source, e):
                    e = replace(e, sha256="")  # während des Abgleichs geändert → neu einlesen
                else:
                    return e
            got = 0

            def on_chunk(n: int) -> None:
                nonlocal got
                got += n
                reporter.progress(done + got, total, label)

            assert e.source is not None
            with open(e.source, "rb") as fh:
                sha = store.put_object(fh, progress=on_chunk, cancelled=reporter.cancelled)
            st = e.source.stat()
            return replace(e, sha256=sha, size=st.st_size, mtime=st.st_mtime)

        def download(r: Entry, target: Path, label: str) -> BaseRecord:
            got = 0

            def on_chunk(n: int) -> None:
                nonlocal got
                got += n
                reporter.progress(done + got, total, label)

            write_local(store, r, target, apply_mode, on_chunk, reporter.cancelled)
            st = target.stat()
            return BaseRecord(r.sha256, st.st_size, st.st_mtime)

        def remember(e: Entry) -> None:
            records[tree_key(e)] = BaseRecord(e.sha256, e.size, e.mtime)

        for idx, a in enumerate(plan.actions, start=1):
            if reporter.cancelled():
                res.cancelled = True
                break
            label = f"[{idx}/{len(plan.actions)}] {a.logical}"
            reporter.progress(done, total, label)
            try:
                store.refresh_lock()
                if a.op == Op.COMMAND:
                    cat = catalog.get(a.category)
                    item = cat.item(a.local.item) if cat else None
                    if item is None:
                        raise RuntimeError("Unbekannter Befehls-Eintrag")
                    data = run_backup_command(item)
                    sha = store.put_object(io.BytesIO(data), cancelled=reporter.cancelled)
                    if a.remote is not None and a.remote.sha256 == sha:
                        res.unchanged_commands += 1
                    else:
                        e = replace(a.local, sha256=sha, size=len(data), mtime=now.timestamp(), source=None)
                        tree[a.key] = e
                        res.uploaded += 1
                        reporter.log(f"Befehl gesichert: {' '.join(item.backup_cmd)} ({human_size(len(data))})")

                elif a.op == Op.UPLOAD:
                    e = upload(a.local, label)
                    tree[a.key] = replace(e, source=None)
                    remember(e)
                    res.uploaded += 1
                    reporter.log(f"↑ {a.logical}" + (f" ({a.reason})" if a.reason else ""))

                elif a.op == Op.DOWNLOAD:
                    assert a.target is not None and a.remote is not None
                    if a.local is not None and not _unchanged_since_plan(a.target, a.local):
                        raise RuntimeError("wurde während des Abgleichs geändert – beim nächsten Mal")
                    records[a.key] = download(a.remote, a.target, label)
                    res.downloaded += 1
                    reporter.log(f"↓ {a.logical}" + (f" ({a.reason})" if a.reason else ""))

                elif a.op == Op.DELETE_REMOTE:
                    tree.pop(a.key, None)
                    records.pop(a.key, None)
                    res.deleted_remote += 1
                    reporter.log(f"✕ im Speicher: {a.logical} (bleibt im Verlauf)")

                elif a.op == Op.DELETE_LOCAL:
                    assert a.target is not None and a.local is not None
                    if not _unchanged_since_plan(a.target, a.local):
                        raise RuntimeError("wurde während des Abgleichs geändert – bleibt erhalten")
                    a.target.unlink()
                    records.pop(a.key, None)
                    res.deleted_local += 1
                    reporter.log(f"✕ lokal: {a.target} (im Verlauf noch vorhanden)")

                elif a.op == Op.CONFLICT:
                    _resolve_conflict(a, winner, host, now, tree, records, upload, download, label, reporter)
                    res.conflicts += 1
                done += a.size
            except InterruptedError:
                res.cancelled = True
                break
            except Exception as exc:
                msg = str(exc) or exc.__class__.__name__
                res.failed.append((a.logical, msg))
                reporter.log(f"FEHLER {a.logical}: {msg}")
                done += a.size

        for k, e in plan.in_sync.items():
            remember(e)
        for k in plan.forget:
            records.pop(k, None)

        # --- neue Version schreiben, falls sich der Stand im Speicher ändert
        old_tree = remote.tree() if remote else {}
        added, changed, deleted = diff_trees(old_tree, tree)
        devices = dict(remote.devices) if remote else {}
        categories = dict(remote.categories) if remote else {}
        new_device = devices.get(host) != os_name
        devices[host] = os_name
        used = {e.category for e in tree.values()}
        for c in catalog.categories:
            if c.id in used and c.id not in categories:
                categories[c.id] = c.meta()
        if added or changed or deleted or new_device or not remote:
            parts = [f"{n} {w}" for n, w in ((added, "neu"), (changed, "geändert"), (deleted, "gelöscht")) if n]
            msg = f"Abgleich von {host}" + (": " + ", ".join(parts) if parts else "")
            if res.cancelled:
                msg += " (abgebrochen)"
            rev = store.commit(list(tree.values()), categories, devices, host, os_name, msg, now=now)
            res.revision = rev.number
            reporter.log(f"Neue Version {rev.number} geschrieben.")
        else:
            res.revision = plan.head

        if catalog.plugins:
            from ..plugins.distribute import publish
            try:
                for name in publish(store, catalog.plugins):
                    reporter.log(f"Plugin „{name}“ im Speicher abgelegt (für andere Geräte).")
            except Exception as exc:  # Plugins dürfen den Abgleich nie scheitern lassen
                reporter.log(f"Plugins konnten nicht im Speicher abgelegt werden: {exc}")

    state.revision = res.revision
    state.save()
    reporter.progress(total, total, "fertig")
    reporter.log(
        f"Abgleich {'abgebrochen' if res.cancelled else 'abgeschlossen'}: "
        f"{res.uploaded} hochgeladen, {res.downloaded} heruntergeladen, "
        f"{res.deleted_remote + res.deleted_local} gelöscht, {res.conflicts} Konflikte"
        + (f", {len(res.failed)} Fehler" if res.failed else "")
    )
    return res


def _resolve_conflict(a, winner, host, now, tree, records, upload, download, label, reporter) -> None:
    L, R, target = a.local, a.remote, a.target
    assert L is not None and R is not None and target is not None
    if winner == ConflictWinner.NEWER:
        local_wins = L.mtime >= R.mtime
    else:
        local_wins = winner == ConflictWinner.LOCAL
    scope, logical = a.key
    parent = logical.rsplit("/", 1)[0]

    if local_wins:
        # Speicher-Fassung als Konfliktkopie herunterladen, lokale Fassung hochladen
        copy = conflict_name(target, "Speicher", now)
        rec = download(R, copy, label)
        copy_e = replace(R, logical=f"{parent}/{copy.name}", mtime=rec.mtime, size=rec.size)
        tree[tree_key(copy_e)] = copy_e
        records[tree_key(copy_e)] = rec
        e = upload(L, label)
        tree[a.key] = replace(e, source=None)
        records[a.key] = BaseRecord(e.sha256, e.size, e.mtime)
        reporter.log(f"⚡ Konflikt {logical}: dieses Gerät gewinnt, Speicher-Fassung → {copy.name}")
    else:
        # lokale Fassung als Konfliktkopie behalten (und hochladen), Speicher-Fassung übernehmen
        copy = conflict_name(target, host, now)
        os.replace(target, copy)
        copy_local = replace(L, logical=f"{parent}/{copy.name}", source=copy)
        e = upload(copy_local, label)
        tree[tree_key(e)] = replace(e, source=None)
        records[tree_key(e)] = BaseRecord(e.sha256, e.size, e.mtime)
        records[a.key] = download(R, target, label)
        reporter.log(f"⚡ Konflikt {logical}: Speicher gewinnt, lokale Fassung → {copy.name}")
