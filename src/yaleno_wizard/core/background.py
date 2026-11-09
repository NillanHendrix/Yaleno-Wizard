"""Abgleich ohne Benutzeroberfläche (Hintergrund, Zeitplan, ``--sync``).

Verwendet die gespeicherten Einstellungen: Kategorien, abgewählte Ordner/Dateien,
Konfliktregel und Anmeldedaten. Vor riskanten Abgleichen (viele Löschungen auf einmal)
bricht er ab – die müssen im Wizard geprüft werden.
"""

from __future__ import annotations

import socket
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from ..catalog import Catalog, PathMapper, catalog_for, current_os
from ..credentials import load_secret
from ..settings import Profile, log_dir, sync_state_dir
from ..storage.base import StorageError
from ..storage.connect import open_storage
from .entry import Entry
from .inventory import Rule
from .reporter import Reporter
from .scanner import Scanner
from .store import Store, sanitize_host
from .sync import ConflictWinner, Op, SyncPlan, SyncResult, SyncState, plan_sync, run_sync

MIN_RISKY = 25        # ab so vielen Löschungen …
RISKY_SHARE = 0.2     # … und diesem Anteil am Bestand gilt ein Abgleich als riskant


class BackgroundError(Exception):
    pass


def excluded_selection(entries: Iterable[Entry], excludes: dict[str, list[str]]) -> set[tuple[str, str]] | None:
    """Auswahl = alles außer den abgewählten Mustern (None = alles)."""
    rules = {cat: [Rule(cat, p) for p in pats] for cat, pats in excludes.items() if pats}
    if not rules:
        return None
    out = set()
    for e in entries:
        if not any(r.matches(e.logical) for r in rules.get(e.category, ())):
            out.add(e.key)
    return out


def risky_deletions(plan: SyncPlan) -> str | None:
    dels = plan.count(Op.DELETE_LOCAL) + plan.count(Op.DELETE_REMOTE)
    known = len(plan.in_sync) + len(plan.actions)
    if dels >= MIN_RISKY and dels > RISKY_SHARE * known:
        return (f"{dels} von {known} Dateien würden gelöscht. Das passiert unbeaufsichtigt nicht – "
                "bitte im Wizard prüfen und abgleichen.")
    return None


@dataclass
class BackgroundOutcome:
    result: SyncResult
    started: datetime
    device: str


def sync_once(
    profile: Profile,
    reporter: Reporter | None = None,
    mapper: PathMapper | None = None,
    catalog: Catalog | None = None,
    os_name: str | None = None,
    secret: str | None = None,
) -> BackgroundOutcome:
    rep = reporter or Reporter()
    started = datetime.now()
    os_name = os_name or current_os()
    catalog = catalog or catalog_for(os_name)  # type: ignore[arg-type]
    mapper = mapper or PathMapper.for_current_system()
    host = sanitize_host(profile.backup_name or socket.gethostname())
    cats = profile.sync_categories
    if not cats:
        raise BackgroundError("Noch keine Kategorien gewählt – bitte zuerst einmal im Wizard abgleichen.")

    storage, base = open_storage(profile, secret if secret is not None else load_secret(profile))
    try:
        store = Store(storage, base)
        rep.log(f"Hintergrund-Abgleich von {host} mit {storage.description}")
        local = Scanner(mapper, cancelled=rep.cancelled).scan(catalog, cats).entries
        remote = store.load_head()
        candidates = list(local) + (remote.entries_for_device(os_name, host) if remote else [])
        selected = excluded_selection(candidates, profile.sync_excludes)
        sid = store.ensure_initialized()
        state = SyncState.load(SyncState.file_for(sync_state_dir(), sid, host))

        def make_plan() -> SyncPlan:
            plan = plan_sync(store, local, state, catalog, mapper, os_name, host, set(cats), selected, reporter=rep)
            risk = risky_deletions(plan)
            if risk:
                raise BackgroundError(risk)
            return plan

        plan = make_plan()
        winner = ConflictWinner(profile.conflicts if profile.conflicts in ("newer", "local", "remote") else "newer")
        res = run_sync(store, plan, state, catalog, mapper, os_name, host, winner, rep, replan=make_plan)
        return BackgroundOutcome(res, started, host)
    finally:
        storage.close()


def append_log(lines: list[str], name: str = "hintergrund.log", max_bytes: int = 2 << 20) -> None:
    try:
        d = log_dir()
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        if f.exists() and f.stat().st_size > max_bytes:
            f.replace(f.with_suffix(".log.1"))
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(f"===== {datetime.now():%Y-%m-%d %H:%M:%S}\n")
            fh.write("\n".join(lines) + "\n")
    except OSError:
        pass


def summarize(res: SyncResult) -> str:
    parts = [f"{n} {w}" for n, w in (
        (res.uploaded, "hochgeladen"), (res.downloaded, "heruntergeladen"),
        (res.deleted_local + res.deleted_remote, "gelöscht"), (res.conflicts, "Konflikte"),
        (len(res.failed), "Fehler"),
    ) if n]
    return ", ".join(parts) if parts else "keine Änderungen"


def run_cli_sync() -> int:
    """``yaleno-wizard --sync``: ein Abgleich, Ausgabe auf der Konsole, Exit-Code 0/1/2."""
    rep = Reporter(on_log=print)
    try:
        out = sync_once(Profile.load(), rep)
    except (BackgroundError, StorageError, OSError) as exc:
        print(f"FEHLER: {exc}")
        append_log(rep.lines + [f"FEHLER: {exc}"])
        return 2
    append_log(rep.lines)
    return 1 if out.result.failed else 0
