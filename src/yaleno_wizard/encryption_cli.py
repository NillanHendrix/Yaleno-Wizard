"""``yaleno-wizard encryption …`` – Verschlüsselung auf der Kommandozeile.

    yaleno-wizard encryption status            verschlüsselt? Schlüsselplätze, gemerkt?
    yaleno-wizard encryption enable            Speicher verschlüsseln (fragt Passwort, zeigt Wiederherstellungsschlüssel)
    yaleno-wizard encryption unlock [--recovery]   entsperren und auf diesem Gerät merken
    yaleno-wizard encryption forget            gemerkten Schlüssel löschen
    yaleno-wizard encryption add-password      weiteres Passwort
    yaleno-wizard encryption add-recovery      neuer Wiederherstellungsschlüssel
    yaleno-wizard encryption remove-slot ID    Schlüsselplatz entfernen
"""

from __future__ import annotations

import argparse
import getpass
import socket
from typing import Callable

from .core import encryption
from .core.crypto import CryptoError
from .core.store import Store, sanitize_host
from .credentials import delete_store_key, load_secret, load_store_key, save_store_key
from .settings import Profile, set_config_file
from .storage.base import StorageError
from .storage.connect import open_storage


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="yaleno-wizard encryption", description="Verschlüsselung des Speichers.")
    ap.add_argument("--config", metavar="DATEI", help="Einstellungsdatei (YAML)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Zustand anzeigen")
    sub.add_parser("enable", help="Speicher verschlüsseln")
    s = sub.add_parser("unlock", help="entsperren und auf diesem Gerät merken")
    s.add_argument("--recovery", action="store_true", help="mit Wiederherstellungsschlüssel")
    sub.add_parser("forget", help="gemerkten Schlüssel löschen")
    sub.add_parser("add-password", help="weiteres Passwort hinzufügen")
    sub.add_parser("add-recovery", help="neuen Wiederherstellungsschlüssel anlegen")
    s = sub.add_parser("remove-slot", help="Schlüsselplatz entfernen")
    s.add_argument("slot_id")
    return ap


def _new_password(ask_pw: Callable[[str], str]) -> str:
    pw = ask_pw("Neues Passwort (mind. 8 Zeichen): ")
    if pw != ask_pw("Wiederholen: "):
        raise CryptoError("Die Passwörter stimmen nicht überein.")
    return pw


def _unlock(store: Store, ask_pw, recovery: bool = False) -> None:
    if store.unlocked:
        return
    key = None if recovery else load_store_key(store.id)
    if key is not None:
        try:
            store.unlock(key)
            return
        except CryptoError:
            pass
    if recovery:
        store.unlock_recovery(ask_pw("Wiederherstellungsschlüssel: "))
    else:
        store.unlock_password(ask_pw("Passwort: "))


def main(argv: list[str], out: Callable[[str], None] = print,
         ask_pw: Callable[[str], str] = getpass.getpass, store: Store | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.config:
        set_config_file(args.config)
    profile = Profile.load()
    host = sanitize_host(profile.backup_name or socket.gethostname())
    storage = None
    try:
        if store is None:
            storage, base = open_storage(profile, load_secret(profile))
            store = Store(storage, base)
        if args.cmd == "status":
            if not store.initialized or not store.encrypted:
                out("Der Speicher ist nicht verschlüsselt.")
                return 0
            out("Der Speicher ist verschlüsselt (AES-256-GCM).")
            for s in store.encryption.slots:  # type: ignore[union-attr]
                out(f"  {s.id}  {encryption.describe_slot(s)}")
            out("Schlüssel auf diesem Gerät gemerkt." if load_store_key(store.id) else
                "Schlüssel auf diesem Gerät nicht gemerkt (Hintergrund-Abgleich kann nicht öffnen).")
            return 0
        if args.cmd == "enable":
            if store.initialized and store.encrypted:
                out("Der Speicher ist bereits verschlüsselt.")
                return 0
            pw = _new_password(ask_pw)
            keys, code = encryption.enable_encryption(store, host, pw, log=out)
            where = save_store_key(store.id, keys.master)
            out("")
            out("WIEDERHERSTELLUNGSSCHLÜSSEL – aufschreiben und sicher aufbewahren:")
            out(f"    {code}")
            out("Ohne Passwort und ohne diesen Schlüssel sind die Daten verloren.")
            out(f"Schlüssel auf diesem Gerät gemerkt ({'Schlüsselbund' if where == 'keyring' else 'Datei'}).")
            return 0
        if not store.encrypted:
            out("Der Speicher ist nicht verschlüsselt.")
            return 2
        if args.cmd == "forget":
            delete_store_key(store.id)
            out("Gemerkter Schlüssel gelöscht.")
            return 0
        _unlock(store, ask_pw, getattr(args, "recovery", False))
        if args.cmd == "unlock":
            where = save_store_key(store.id, store.keys.master)  # type: ignore[union-attr]
            out(f"Entsperrt und gemerkt ({'Schlüsselbund' if where == 'keyring' else 'Datei'}).")
        elif args.cmd == "add-password":
            encryption.add_password(store, host, _new_password(ask_pw))
            out("Passwort hinzugefügt.")
        elif args.cmd == "add-recovery":
            code = encryption.add_recovery(store, host)
            out(f"Neuer Wiederherstellungsschlüssel:\n    {code}")
        elif args.cmd == "remove-slot":
            encryption.remove_slot(store, host, args.slot_id)
            out(f"Schlüsselplatz {args.slot_id} entfernt.")
        return 0
    except (CryptoError, StorageError, OSError) as exc:
        out(f"FEHLER: {exc}")
        return 2
    finally:
        if storage is not None:
            storage.close()
