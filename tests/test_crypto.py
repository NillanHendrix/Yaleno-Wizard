"""Ende-zu-Ende-Verschlüsselung: Blöcke, Schlüsselplätze, Umstellung, Abgleich, Hintergrund."""

from __future__ import annotations

import io

import pytest

from yaleno_wizard.core import crypto, encryption
from yaleno_wizard.core.crypto import CryptoError, KeySlot, StoreKeys, WrongKey
from yaleno_wizard.core.store import Store, StoreEncrypted
from yaleno_wizard.storage.base import StorageError
from yaleno_wizard.storage.local import LocalStorage

from .test_sync import CATS, Device

PW = "richtig-gutes-passwort"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    monkeypatch.setattr(crypto, "SCRYPT_N", 2 ** 10)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "server")


def all_bytes(root) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


# ---------------------------------------------------------------------- Blöcke
@pytest.mark.parametrize("size", [0, 1, crypto.BLOCK - 1, crypto.BLOCK, 2 * crypto.BLOCK + 7])
def test_stream_roundtrip(size):
    keys = StoreKeys(crypto.new_master_key())
    data = (b"abcdefgh" * (size // 8 + 1))[:size]
    enc = io.BytesIO()
    sha = keys.encrypt_stream(io.BytesIO(data), enc, b"ctx")
    out = io.BytesIO()
    assert keys.decrypt_stream(io.BytesIO(enc.getvalue()), out, b"ctx") == sha
    assert out.getvalue() == data
    if size >= 16:  # kürzere Klartexte können zufällig im Chiffrat vorkommen
        assert data[:16] not in enc.getvalue()


def test_tampering_detected():
    keys = StoreKeys(crypto.new_master_key())
    data = b"x" * (crypto.BLOCK + 100)
    enc = keys.encrypt_bytes(data, b"ctx")
    with pytest.raises(CryptoError):
        keys.decrypt_bytes(enc, b"anderer-ort")  # an anderen Ort verschoben
    bad = bytearray(enc)
    bad[50] ^= 1
    with pytest.raises(CryptoError):
        keys.decrypt_bytes(bytes(bad), b"ctx")
    with pytest.raises(CryptoError):
        keys.decrypt_bytes(enc[: 12 + crypto.BLOCK + crypto.TAG], b"ctx")  # letzter Block fehlt
    with pytest.raises(CryptoError):
        StoreKeys(crypto.new_master_key()).decrypt_bytes(enc, b"ctx")


def test_slots_password_and_recovery():
    master = crypto.new_master_key()
    info = crypto.EncryptionInfo(StoreKeys(master).check_value(), [KeySlot.for_password(master, PW)])
    slot, code = KeySlot.for_recovery(master)
    info.slots.append(slot)
    assert info.unlock_password(PW).master == master
    assert info.unlock_recovery(code.lower().replace("-", " ")).master == master
    with pytest.raises(WrongKey):
        info.unlock_password("falsch-falsch")
    with pytest.raises(WrongKey):
        info.unlock_recovery("AAAA-BBBB")
    with pytest.raises(CryptoError, match="8 Zeichen"):
        KeySlot.for_password(master, "kurz")
    again = crypto.EncryptionInfo.from_dict(info.to_dict())
    assert again.unlock_password(PW).master == master


# ---------------------------------------------------------------------- Speicher
def test_enable_on_existing_store_and_sync(tmp_path, storage):
    a = Device(tmp_path, storage, "laptop")
    a.sync()
    rev_before = a.store.load_head()
    root = tmp_path / "server"
    assert b"pdf-inhalt" in all_bytes(root)

    keys, code = encryption.enable_encryption(a.store, "laptop", PW)
    assert a.store.encrypted and a.store.unlocked
    data = root / "daten" / "yaleno"
    assert not (data / "objects").exists() and not (data / "revisions").exists()
    blob = all_bytes(root)
    assert b"pdf-inhalt" not in blob and b"Rechnungen" not in blob and b"laptop" not in blob
    head = a.store.load_head()
    assert head.number == rev_before.number and len(head.entries) == len(rev_before.entries)
    assert a.store.list_revisions()[0].host == "laptop"

    # zweites Gerät: gesperrt, bis es entsperrt wird
    b = Device(tmp_path, storage, "desktop", files=False)
    assert b.store.encrypted and not b.store.unlocked
    with pytest.raises(StoreEncrypted):
        b.store.load_head()
    with pytest.raises(WrongKey):
        b.store.unlock_password("falsch-falsch")
    b.store.unlock_recovery(code)
    b.sync()
    assert b.p("DOCUMENTS", "Rechnungen", "2026.pdf").read_text() == "pdf-inhalt"

    # Änderungen laufen verschlüsselt weiter
    b.p("DOCUMENTS", "neu.txt").write_text("vom desktop")
    b.sync()
    a.sync()
    assert a.p("DOCUMENTS", "neu.txt").read_text() == "vom desktop"
    assert b"vom desktop" not in all_bytes(root)


def test_new_empty_store_encrypted_then_first_sync(tmp_path, storage):
    store = Store(storage, "daten")
    encryption.enable_encryption(store, "pc", PW)
    assert store.encrypted and store.head() == 0
    a = Device(tmp_path, storage, "laptop")
    a.store.unlock_password(PW)
    a.sync()
    assert a.store.head() == 1
    assert b"alias ll" not in all_bytes(tmp_path / "server")


def test_conversion_aborted_keeps_plain_store(tmp_path, storage):
    a = Device(tmp_path, storage, "laptop")
    a.sync()
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 3

    with pytest.raises(InterruptedError):
        encryption.enable_encryption(a.store, "laptop", PW, cancelled=cancelled)
    fresh = Store(storage, "daten")
    assert not fresh.encrypted and fresh.load_head() is not None
    assert not (tmp_path / "server" / "daten" / "yaleno" / "lock").exists()
    # zweiter Versuch klappt und nutzt die Reste
    encryption.enable_encryption(a.store, "laptop", PW)
    assert Store(storage, "daten").encrypted


def test_slot_management(tmp_path, storage):
    store = Store(storage, "daten")
    keys, code = encryption.enable_encryption(store, "pc", PW)
    encryption.add_password(store, "pc", "zweites-passwort", "Laptop")
    other = Store(storage, "daten")
    other.unlock_password("zweites-passwort")
    info = store.encryption
    pw_ids = [s.id for s in info.slots if s.type == "password"]
    encryption.remove_slot(store, "pc", pw_ids[0])
    with pytest.raises(WrongKey):
        Store(storage, "daten").unlock_password(PW)
    rec = [s.id for s in store.encryption.slots if s.type == "recovery"][0]
    encryption.remove_slot(store, "pc", rec)
    last = [s.id for s in store.encryption.slots][0]
    with pytest.raises(StorageError, match="mindestens ein Passwort"):
        encryption.remove_slot(store, "pc", last)
    new_code = encryption.add_recovery(store, "pc")
    Store(storage, "daten").unlock_recovery(new_code)
    assert "Wiederherstellungsschlüssel" in "\n".join(encryption.describe_slots(store.encryption))


def test_plugins_encrypted_in_store(tmp_path, storage):
    store = Store(storage, "daten")
    store.ensure_initialized()
    store.put_plugin("demo", "yaleno_plugin: 1\nid: demo\n")
    encryption.enable_encryption(store, "pc", PW)
    assert store.list_plugins() == ["demo"]
    store.put_plugin("zwei", "geheim: ja")
    assert store.get_plugin("zwei") == "geheim: ja"
    assert b"geheim" not in all_bytes(tmp_path / "server")
    other = Store(storage, "daten")
    other.unlock_password(PW)
    assert other.list_plugins() == ["demo", "zwei"]


def test_old_client_format_check(storage):
    store = Store(storage, "daten")
    encryption.enable_encryption(store, "pc", PW)
    assert store.meta()["version"] == 2


def test_background_needs_cached_key(tmp_path, storage, monkeypatch, fake_home):
    from yaleno_wizard.catalog.placeholders import PathMapper
    from yaleno_wizard.core.background import BackgroundError, sync_once
    from yaleno_wizard.credentials import load_store_key, save_store_key
    from yaleno_wizard.settings import Profile

    store = Store(storage, ".")
    keys, _ = encryption.enable_encryption(store, "pc", PW)
    prof = Profile(storage_type="local", local_dir=str(tmp_path / "server"), backup_name="pc",
                   sync_categories=["personal"])
    with pytest.raises(BackgroundError, match="nicht entsperrt"):
        sync_once(prof, mapper=PathMapper(fake_home), os_name="linux")
    assert save_store_key(store.id, keys.master) == "keyring"
    assert load_store_key(store.id) == keys.master
    out = sync_once(prof, mapper=PathMapper(fake_home), os_name="linux")
    assert out.result.uploaded > 0 and not out.result.failed
    save_store_key(store.id, crypto.new_master_key())
    with pytest.raises(BackgroundError, match="passt nicht"):
        sync_once(prof, mapper=PathMapper(fake_home), os_name="linux")


def test_encryption_cli(tmp_path, storage):
    from yaleno_wizard.encryption_cli import main
    from yaleno_wizard.credentials import delete_store_key

    def run(args, answers=()):
        out = []
        it = iter(answers)
        rc = main(args, out=out.append, ask_pw=lambda q: next(it), store=Store(storage, "daten"))
        return rc, "\n".join(out)

    assert "nicht verschlüsselt" in run(["status"])[1]
    rc, out = run(["enable"], [PW, "anders-anders"])
    assert rc == 2 and "stimmen nicht" in out
    rc, out = run(["enable"], [PW, PW])
    assert rc == 0 and "WIEDERHERSTELLUNGSSCHLÜSSEL" in out
    code = out.split("aufbewahren:")[1].split()[0]
    assert "gemerkt" in run(["status"])[1]
    delete_store_key(Store(storage, "daten").id)
    rc, out = run(["add-password"], ["falsch-falsch"])
    assert rc == 2 and "Falsches Passwort" in out
    assert run(["unlock", "--recovery"], [code])[0] == 0
    assert run(["add-password"], ["zweites-pw-123", "zweites-pw-123"])[0] == 0
    rc, out = run(["status"])
    assert out.count("Passwort") >= 2
