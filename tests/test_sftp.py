from __future__ import annotations

from pathlib import Path

import paramiko
import pytest

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.core.reporter import Reporter
from yaleno_wizard.core.scanner import Scanner
from yaleno_wizard.core.store import Store, StoreLocked
from yaleno_wizard.core.sync import ConflictWinner, SyncState, plan_sync, run_sync
from yaleno_wizard.storage.base import StorageError
from yaleno_wizard.storage.sftp import (
    ConnectionSettings, HostKeyMismatch, HostKeyRejected, KeyPassphraseRequired, SFTPStorage,
)

from .sftp_stub import StubServer

LINUX = catalog_for("linux")


def _make_key(path: Path, passphrase: str | None = None) -> paramiko.PKey:
    key = paramiko.RSAKey.generate(2048)
    key.write_private_key_file(str(path), password=passphrase)
    return key


@pytest.fixture
def server(tmp_path):
    key_file = tmp_path / "id_test"
    key = _make_key(key_file)
    remote_root = tmp_path / "remote"
    remote_root.mkdir()
    srv = StubServer(remote_root, key)
    yield srv, key_file, remote_root
    srv.close()


def _settings(srv, key_file, user="tester"):
    return ConnectionSettings(host="127.0.0.1", port=srv.port, username=user, key_path=str(key_file),
                              base_path="/backups")


def test_hostkey_tofu_and_mismatch(server, tmp_path):
    srv, key_file, _ = server
    kh = tmp_path / "known_hosts"
    asked = []

    with pytest.raises(HostKeyRejected):
        SFTPStorage.connect(_settings(srv, key_file), kh, lambda *a: asked.append(a) or False)
    assert not kh.exists()

    st = SFTPStorage.connect(_settings(srv, key_file), kh, lambda *a: True)
    st.close()
    assert f"[127.0.0.1]:{srv.port}" in kh.read_text()

    # zweites Mal: keine Rückfrage mehr
    st = SFTPStorage.connect(_settings(srv, key_file), kh, lambda *a: pytest.fail("erneute Rückfrage"))
    st.close()

    # anderer Host-Key → Abbruch
    srv.host_key = paramiko.RSAKey.generate(2048)
    with pytest.raises(HostKeyMismatch):
        SFTPStorage.connect(_settings(srv, key_file), kh, lambda *a: True)


def test_wrong_user_and_passphrase(server, tmp_path):
    srv, key_file, _ = server
    kh = tmp_path / "kh"
    with pytest.raises(StorageError, match="abgelehnt"):
        SFTPStorage.connect(_settings(srv, key_file, user="falsch"), kh, lambda *a: True)

    enc = tmp_path / "id_enc"
    _make_key(enc, passphrase="geheim")
    with pytest.raises(KeyPassphraseRequired):
        SFTPStorage.connect(_settings(srv, enc), kh, lambda *a: True)


def _sync(storage, mapper, state_file, host, cats):
    store = Store(storage, "/backups")
    entries = Scanner(mapper).scan(LINUX, cats).entries
    st = SyncState.load(state_file)
    plan = plan_sync(store, entries, st, LINUX, mapper, "linux", host, set(cats), None)
    res = run_sync(store, plan, st, LINUX, mapper, "linux", host, ConflictWinner.NEWER, Reporter())
    assert not res.failed, res.failed
    return res


def test_sync_over_sftp(server, tmp_path, mapper, fake_home):
    from .conftest import build_home
    from yaleno_wizard.catalog.placeholders import PathMapper

    srv, key_file, remote_root = server
    remote_root.joinpath("backups").mkdir()
    storage = SFTPStorage.connect(_settings(srv, key_file), tmp_path / "kh", lambda *a: True)
    try:
        cats = ["personal", "shell", "keys"]
        r = _sync(storage, mapper, tmp_path / "a.json", "laptop", cats)
        assert r.uploaded == len(Scanner(mapper).scan(LINUX, cats).entries)
        assert Store(storage, "/backups").head() == 1

        # zweites Gerät holt alles, inkl. Dateirechten
        other = PathMapper(build_home(tmp_path, "zweit", files=False))
        r2 = _sync(storage, other, tmp_path / "b.json", "desktop", cats)
        assert r2.downloaded == r.uploaded
        key = other.to_local("{HOME}/.ssh/id_ed25519")
        assert key.read_text() == "PRIVATE"
        assert key.stat().st_mode & 0o777 == 0o600

        # Sperre über SFTP (exklusives Anlegen)
        store = Store(storage, "/backups")
        store.acquire_lock("laptop")
        with pytest.raises(StoreLocked):
            Store(storage, "/backups").acquire_lock("desktop")
        store.release_lock()
        assert not (remote_root / "backups" / "yaleno" / "lock").exists()
    finally:
        storage.close()


def test_passphrase_key_loading(tmp_path):
    from yaleno_wizard.storage.sftp import load_private_key
    enc = tmp_path / "id_enc"
    _make_key(enc, passphrase="geheim")
    assert load_private_key(str(enc), "geheim") is not None
    with pytest.raises(StorageError):
        load_private_key(str(enc), "falsch")
    with pytest.raises(KeyPassphraseRequired):
        load_private_key(str(enc))
