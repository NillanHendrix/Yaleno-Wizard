"""Verschlüsselung einschalten und Schlüsselplätze verwalten (für Wizard und Kommandozeile)."""

from __future__ import annotations

from typing import Callable

from .crypto import EncryptionInfo, KeySlot, StoreKeys, new_master_key
from .store import Store, StoreEncrypted
from ..storage.base import StorageError

SLOT_LABELS = {"password": "Passwort", "recovery": "Wiederherstellungsschlüssel", "fido2": "Security-Key / Passkey"}


def enable_encryption(
    store: Store,
    host: str,
    password: str,
    log: Callable[[str], None] | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[StoreKeys, str]:
    """Verschlüsselt den Speicher. Gibt (Schlüssel, Wiederherstellungsschlüssel zum Aufschreiben) zurück."""
    master = new_master_key()
    keys = StoreKeys(master)
    pw = KeySlot.for_password(master, password)
    rec, code = KeySlot.for_recovery(master)
    info = EncryptionInfo(check=keys.check_value(), slots=[pw, rec])
    with store.locked(host):
        store.convert_to_encrypted(keys, info, log, progress, cancelled)
    return keys, code


def _modify(store: Store, host: str, change: Callable[[EncryptionInfo, bytes], None]) -> EncryptionInfo:
    if store.keys is None:
        raise StoreEncrypted()
    master = store.keys.master
    with store.locked(host):
        store._meta = None  # aktuellen Stand lesen (anderes Gerät könnte Plätze geändert haben)
        info = store.encryption
        if info is None:
            raise StorageError("Der Speicher ist nicht verschlüsselt.")
        change(info, master)
        store.save_encryption(info)
    return info


def add_password(store: Store, host: str, password: str, label: str = "Passwort") -> KeySlot:
    if store.keys is None:
        raise StoreEncrypted()
    slot = KeySlot.for_password(store.keys.master, password, label)
    _modify(store, host, lambda info, _m: info.slots.append(slot))
    return slot


def add_recovery(store: Store, host: str) -> str:
    """Legt einen neuen Wiederherstellungsschlüssel an (alte bleiben gültig, bis sie entfernt werden)."""
    if store.keys is None:
        raise StoreEncrypted()
    slot, code = KeySlot.for_recovery(store.keys.master)
    _modify(store, host, lambda info, _m: info.slots.append(slot))
    return code


def add_secret_slot(store: Store, host: str, secret: bytes, type_: str, label: str, params: dict) -> KeySlot:
    if store.keys is None:
        raise StoreEncrypted()
    slot = KeySlot.for_secret(store.keys.master, secret, type_, label, params)
    _modify(store, host, lambda info, _m: info.slots.append(slot))
    return slot


def remove_slot(store: Store, host: str, slot_id: str) -> None:
    def change(info: EncryptionInfo, _m: bytes) -> None:
        rest = [s for s in info.slots if s.id != slot_id]
        if len(rest) == len(info.slots):
            raise StorageError(f"Schlüsselplatz {slot_id} gibt es nicht.")
        if not any(s.type in ("password", "recovery") for s in rest):
            raise StorageError("Es muss mindestens ein Passwort oder Wiederherstellungsschlüssel bleiben – "
                               "sonst ist der Speicher ohne Security-Key nicht mehr zu öffnen.")
        info.slots[:] = rest
    _modify(store, host, change)


def describe_slot(s: KeySlot) -> str:
    kind = SLOT_LABELS.get(s.type, s.type)
    return f"{kind} – {s.label}" if s.label and s.label != kind else kind


def describe_slots(info: EncryptionInfo) -> list[str]:
    return [describe_slot(s) for s in info.slots]
