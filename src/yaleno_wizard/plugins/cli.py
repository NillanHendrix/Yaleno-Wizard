"""``yaleno-wizard plugin …`` – Plugins auf der Kommandozeile verwalten.

    yaleno-wizard plugin list                     alle Plugins mit Status
    yaleno-wizard plugin show ID                  Details (Pfade, Befehle)
    yaleno-wizard plugin install DATEI|URL        installieren und aktivieren
    yaleno-wizard plugin remove ID                entfernen
    yaleno-wizard plugin enable|disable ID        (de)aktivieren
    yaleno-wizard plugin check                    nach Updates suchen
    yaleno-wizard plugin update [ID …] [--all]    Updates installieren
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable

from ..settings import Profile, set_config_file
from . import manager
from .model import FEATURES, PluginError
from .registry import discover, find


def _confirm(question: str, yes: bool, ask: Callable[[str], str]) -> bool:
    if yes:
        return True
    if ask is input and not sys.stdin.isatty():
        print("Abgebrochen – ohne Terminal bitte mit --yes bestätigen.")
        return False
    return ask(f"{question} [j/N] ").strip().lower() in ("j", "ja", "y", "yes")


def _status(lp) -> str:
    if lp.error:
        return f"FEHLER: {lp.error}"
    return "aktiv" if lp.enabled else "aus"


def cmd_list(args, profile, out, ask) -> int:
    rows = discover(profile)
    if not rows:
        out("Keine Plugins vorhanden.")
        return 0
    updates = set(manager.known_updates())
    for lp in rows:
        origin = "mitgeliefert" if lp.origin == "builtin" else "installiert"
        upd = "  ⬆ Update verfügbar" if lp.id in updates else ""
        out(f"{lp.id:<24} {lp.version:<10} {_status(lp):<8} {origin:<13} {lp.name}{upd}")
    return 0


def cmd_show(args, profile, out, ask) -> int:
    lp = find(args.id, profile)
    if lp is None:
        out(f"Plugin „{args.id}“ ist nicht installiert.")
        return 2
    out(f"{lp.name} ({lp.id}) – Version {lp.version}, {_status(lp)}")
    out(f"Datei: {lp.path}")
    p = lp.plugin
    if p is None:
        return 1
    for label, value in (("Autor", p.author), ("Quelle", p.source), ("Webseite", p.homepage),
                         ("Beschreibung", p.description)):
        if value:
            out(f"{label}: {value}")
    if p.is_feature:
        out(f"Funktion: {FEATURES.get(p.feature, p.feature)}")
        return 0
    out(f"Inhalt: {p.summary()}")
    for path in p.paths():
        out(f"  {path}")
    if p.commands():
        out("Befehle:")
        for c in p.commands():
            out(f"  ! {c}")
    return 0


def _install(pending, profile, yes, ask, out, enable=True) -> int:
    p = pending.plugin
    out(f"{p.name} ({p.id})")
    out(pending.changes.describe())
    if pending.is_downgrade:
        out(f"⚠ Installiert ist bereits die neuere Version {pending.existing.version}.")
    if not _confirm("Installieren?", yes, ask):
        return 1
    path = manager.install(pending, profile, enable=enable)
    out(f"Installiert: {path}" + (" (aktiv)" if enable else ""))
    return 0


def cmd_install(args, profile, out, ask) -> int:
    pending = manager.prepare_source(args.source, profile)
    return _install(pending, profile, args.yes, ask, out, enable=not args.disabled)


def cmd_remove(args, profile, out, ask) -> int:
    manager.remove(args.id, profile)
    out(f"Entfernt: {args.id}")
    return 0


def cmd_enable(args, profile, out, ask) -> int:
    manager.set_enabled(args.id, args.cmd == "enable", profile)
    out(f"{args.id}: {'aktiviert' if args.cmd == 'enable' else 'deaktiviert'}")
    return 0


def cmd_check(args, profile, out, ask) -> int:
    res = manager.check_updates(profile)
    for e in res.errors:
        out(f"FEHLER: {e}")
    if not res.updates:
        out(f"Alle Plugins sind aktuell ({res.checked} geprüft).")
    for u in res.updates:
        out(f"{u.current.name}: {u.current.version} → {u.pending.plugin.version}")
    return 2 if res.errors and not res.updates else 0


def cmd_update(args, profile, out, ask) -> int:
    ids = None if args.all or not args.ids else list(args.ids)
    res = manager.check_updates(profile, plugin_ids=ids)
    for e in res.errors:
        out(f"FEHLER: {e}")
    if not res.updates:
        out("Keine Updates verfügbar.")
        return 2 if res.errors else 0
    rc = 0
    for u in res.updates:
        out(f"— {u.current.name}")
        out(u.pending.changes.describe())
        if not _confirm("Aktualisieren?", args.yes, ask):
            rc = 1
            continue
        manager.apply_update(u, profile)
        out(f"Aktualisiert auf {u.pending.plugin.version}.")
    return rc


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="yaleno-wizard plugin", description="Plugins verwalten.")
    ap.add_argument("--config", metavar="DATEI", help="Einstellungsdatei (YAML)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="alle Plugins anzeigen")
    s = sub.add_parser("show", help="Details eines Plugins")
    s.add_argument("id")
    s = sub.add_parser("install", help="aus Datei oder https-URL installieren")
    s.add_argument("source")
    s.add_argument("--yes", "-y", action="store_true", help="ohne Rückfrage")
    s.add_argument("--disabled", action="store_true", help="installieren, aber nicht aktivieren")
    s = sub.add_parser("remove", help="installiertes Plugin entfernen")
    s.add_argument("id")
    for name in ("enable", "disable"):
        s = sub.add_parser(name, help=f"Plugin {'aktivieren' if name == 'enable' else 'deaktivieren'}")
        s.add_argument("id")
    sub.add_parser("check", help="nach Updates suchen")
    s = sub.add_parser("update", help="Updates installieren")
    s.add_argument("ids", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--yes", "-y", action="store_true")
    return ap


COMMANDS = {
    "list": cmd_list, "show": cmd_show, "install": cmd_install, "remove": cmd_remove,
    "enable": cmd_enable, "disable": cmd_enable, "check": cmd_check, "update": cmd_update,
}


def main(argv: list[str], out: Callable[[str], None] = print, ask: Callable[[str], str] = input) -> int:
    args = build_parser().parse_args(argv)
    if args.config:
        set_config_file(args.config)
    profile = Profile.load()
    try:
        return COMMANDS[args.cmd](args, profile, out, ask)
    except (PluginError, OSError) as exc:
        out(f"FEHLER: {exc}")
        return 2
