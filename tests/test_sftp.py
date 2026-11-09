from __future__ import annotations

from pathlib import Path

import paramiko
import pytest

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.core.backup import run_backup
from yaleno_wizard.core.manifest import list_snapshots, load_manifest
from yaleno_wizard.core.reporter import Reporter
from yaleno_wizard.core.restore import ConflictPolicy, plan_restore, run_restore
from yaleno_wizard.core.scanner import Scanner
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


def test_backup_restore_over_sftp(server, tmp_path, mapper, fake_home):
    srv, key_file, remote_root = server
    remote_root.joinpath("backups").mkdir()
    storage = SFTPStorage.connect(_settings(srv, key_file), tmp_path / "kh", lambda *a: True)
    try:
        entries = Scanner(mapper).scan(LINUX, ["personal", "shell", "keys"]).entries
        r = run_backup(storage, "/backups", "testpc", "linux", LINUX, entries, Reporter())
        assert r.ok and not r.failed
        snaps = list_snapshots(storage, "/backups")
        assert len(snaps) == 1
        m = load_manifest(storage, snaps[0].path)
        assert len(m.entries) == len(entries)

        (fake_home["DOCUMENTS"] / "Rechnungen" / "2026.pdf").unlink()
        (fake_home["HOME"] / ".ssh" / "id_ed25519").unlink()
        actions = plan_restore(m, m.entries, mapper, LINUX, "linux", tmp_path / "st")
        res = run_restore(storage, snaps[0].path, m, actions, LINUX, ConflictPolicy.SKIP, Reporter())
        assert not res.failed
        assert res.written == 2
        key = fake_home["HOME"] / ".ssh" / "id_ed25519"
        assert key.read_text() == "PRIVATE"
        assert key.stat().st_mode & 0o777 == 0o600
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
