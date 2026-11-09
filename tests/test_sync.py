"""Zentraler Speicher: Abgleich zwischen mehreren Geräten, Verlauf, Zurückspringen."""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime
from pathlib import Path

import pytest

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.catalog.placeholders import PathMapper
from yaleno_wizard.core.entry import Entry
from yaleno_wizard.core.reporter import Reporter
from yaleno_wizard.core.restore import ActionKind, ConflictPolicy, plan_restore, run_restore
from yaleno_wizard.core.scanner import Scanner
from yaleno_wizard.core.store import Store, StoreLocked
from yaleno_wizard.core.sync import ConflictWinner, Op, SyncState, plan_sync, run_sync
from yaleno_wizard.storage.local import LocalStorage

from .conftest import build_home

CATS = {"personal", "shell", "keys", "dev", "system", "apps"}  # ohne Befehle (pacman, dconf …)


class Device:
    def __init__(self, tmp_path: Path, storage, name: str, os_name: str = "linux", files: bool = True,
                 mapping: dict | None = None):
        self.name = name
        self.os = os_name
        self.paths = mapping or build_home(tmp_path, name, files=files)
        self.mapper = PathMapper(self.paths)
        self.catalog = catalog_for(os_name)
        self.store = Store(storage, "daten")
        self.state_dir = tmp_path / f"{name}-state"

    def state(self) -> SyncState:
        sid = self.store.ensure_initialized()
        return SyncState.load(SyncState.file_for(self.state_dir, sid, self.name))

    def plan(self, selected=None, cats=CATS):
        entries = Scanner(self.mapper).scan(self.catalog, cats).entries
        state = self.state()
        return plan_sync(self.store, entries, state, self.catalog, self.mapper, self.os, self.name,
                         set(cats), selected), state

    def sync(self, winner=ConflictWinner.NEWER, selected=None, cats=CATS, rep=None):
        plan, state = self.plan(selected, cats)
        res = run_sync(self.store, plan, state, self.catalog, self.mapper, self.os, self.name, winner,
                       rep or Reporter())
        assert not res.failed, res.failed
        return res

    def p(self, ph: str, *rest: str) -> Path:
        return self.paths[ph].joinpath(*rest)


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "server")


@pytest.fixture
def two(tmp_path, storage):
    a = Device(tmp_path, storage, "laptop")
    b = Device(tmp_path, storage, "desktop", files=False)
    return a, b


def touch_later(path: Path, text: str) -> None:
    path.write_text(text)
    t = time.time() + 5
    os.utime(path, (t, t))


# ---------------------------------------------------------------------- Grundlagen
def test_first_sync_layout_and_idempotent(two, tmp_path):
    a, _ = two
    r = a.sync()
    assert r.uploaded > 0 and r.revision == 1
    root = tmp_path / "server" / "daten" / "yaleno"
    assert (root / "store.json").is_file()
    assert (root / "HEAD").read_text().strip() == "1"
    rev = json.loads(gzip.decompress((root / "revisions" / "00000001.json.gz").read_bytes()))
    scopes = {e["logical"]: e["scope"] for e in rev["entries"]}
    assert scopes["{DOCUMENTS}/notiz.txt"] == "all"
    assert scopes["{HOME}/.bashrc"] == "os:linux"
    assert scopes["{ROOT}/etc/fstab"] == "host:laptop"
    assert not any(root.joinpath("tmp").iterdir())
    # Inhalte liegen dedupliziert unter objects/
    assert len(list((root / "objects").rglob("*"))) > 0

    r2 = a.sync()
    assert r2.changes == 0 and r2.revision == 1  # nichts geändert → keine neue Version


def test_new_device_gets_everything_but_device_data(two):
    a, b = two
    a.sync()
    r = b.sync()
    assert r.downloaded > 0
    assert b.p("DOCUMENTS", "Rechnungen", "2026.pdf").read_text() == "pdf-inhalt"
    assert b.p("HOME", ".bashrc").read_text() == "alias ll='ls -l'"
    key = b.p("HOME", ".ssh", "id_ed25519")
    assert key.read_text() == "PRIVATE" and key.stat().st_mode & 0o777 == 0o600
    assert not b.p("ROOT", "etc", "fstab").exists()  # Systemdateien sind gerätebezogen
    # Gerät wird im Speicher registriert
    head = a.store.load_head()
    assert head.devices == {"laptop": "linux", "desktop": "linux"}


def test_changes_and_deletions_propagate(two):
    a, b = two
    a.sync()
    b.sync()
    touch_later(b.p("DOCUMENTS", "notiz.txt"), "von desktop")
    (b.p("PICTURES", "Urlaub", "IMG_0001.jpg")).unlink()
    b.p("DOCUMENTS", "neu.txt").write_text("neu")
    rb = b.sync()
    assert (rb.uploaded, rb.deleted_remote) == (2, 1)

    plan, _ = a.plan()
    ops = {x.logical: x.op for x in plan.actions}
    assert ops == {
        "{DOCUMENTS}/notiz.txt": Op.DOWNLOAD,
        "{DOCUMENTS}/neu.txt": Op.DOWNLOAD,
        "{PICTURES}/Urlaub/IMG_0001.jpg": Op.DELETE_LOCAL,
    }
    ra = a.sync()
    assert (ra.downloaded, ra.deleted_local) == (2, 1)
    assert a.p("DOCUMENTS", "notiz.txt").read_text() == "von desktop"
    assert a.p("DOCUMENTS", "neu.txt").read_text() == "neu"
    assert not a.p("PICTURES", "Urlaub", "IMG_0001.jpg").exists()
    assert a.sync().changes == 0 and b.sync().changes == 0


def test_local_delete_vs_remote_change_keeps_file(two):
    a, b = two
    a.sync()
    b.sync()
    touch_later(a.p("DOCUMENTS", "notiz.txt"), "geändert auf laptop")
    a.sync()
    b.p("DOCUMENTS", "notiz.txt").unlink()
    b.sync()
    assert b.p("DOCUMENTS", "notiz.txt").read_text() == "geändert auf laptop"


@pytest.mark.parametrize("winner", [ConflictWinner.NEWER, ConflictWinner.REMOTE, ConflictWinner.LOCAL])
def test_conflict_keeps_both_versions(two, winner):
    a, b = two
    a.sync()
    b.sync()
    a.p("DOCUMENTS", "notiz.txt").write_text("laptop")
    a.sync()
    touch_later(b.p("DOCUMENTS", "notiz.txt"), "desktop")  # jünger
    plan, _ = b.plan()
    assert [x.op for x in plan.actions] == [Op.CONFLICT]
    r = b.sync(winner)
    assert r.conflicts == 1
    docs = b.p("DOCUMENTS")
    copies = [p for p in docs.iterdir() if "Konflikt" in p.name]
    assert len(copies) == 1
    main = docs.joinpath("notiz.txt").read_text()
    if winner in (ConflictWinner.NEWER, ConflictWinner.LOCAL):
        assert main == "desktop" and copies[0].read_text() == "laptop"
    else:
        assert main == "laptop" and copies[0].read_text() == "desktop"
    # beide Fassungen landen auch auf dem anderen Gerät
    a.sync()
    assert a.p("DOCUMENTS", "notiz.txt").read_text() == main
    assert a.p("DOCUMENTS", copies[0].name).read_text() == copies[0].read_text()
    assert b.sync().changes == 0


def test_deselected_files_are_left_alone(two):
    a, b = two
    a.sync()
    b.sync()
    b.p("DOCUMENTS", "notiz.txt").unlink()
    entries = Scanner(b.mapper).scan(b.catalog, CATS).entries
    selected = {e.key for e in entries}  # notiz.txt fehlt lokal und ist nicht gewählt
    r = b.sync(selected=selected)
    assert r.deleted_remote == 0
    assert any(e.logical == "{DOCUMENTS}/notiz.txt" for e in a.store.load_head().entries)


def test_unselected_category_not_touched(two):
    a, b = two
    a.sync()
    r = b.sync(cats={"personal"})
    assert not b.p("HOME", ".bashrc").exists()
    assert r.deleted_remote == 0
    assert any(e.logical == "{HOME}/.bashrc" for e in a.store.load_head().entries)


def test_cross_os_only_personal(tmp_path, storage, two):
    a, _ = two
    a.sync()
    wh = tmp_path / "winhome"
    win = Device(tmp_path, storage, "winpc", "windows", mapping={
        "HOME": wh, "DOCUMENTS": wh / "Documents", "PICTURES": wh / "Pictures",
        "APPDATA": wh / "AppData" / "Roaming",
    })
    for p in win.paths.values():
        p.mkdir(parents=True, exist_ok=True)
    win.sync(cats={"personal", "shell", "dev"})
    assert (wh / "Documents" / "Rechnungen" / "2026.pdf").read_text() == "pdf-inhalt"
    assert not (wh / ".bashrc").exists()
    (wh / "Documents" / "von-windows.txt").write_text("hallo linux")
    win.sync(cats={"personal"})
    a.sync()
    assert a.p("DOCUMENTS", "von-windows.txt").read_text() == "hallo linux"


# ---------------------------------------------------------------------- Verlauf
def test_history_restore_and_revert(two, tmp_path):
    a, b = two
    a.sync()                                              # Version 1
    a.p("DOCUMENTS", "notiz.txt").write_text("v2")
    a.p("DOCUMENTS", "spaeter.txt").write_text("erst ab v2")
    a.sync()                                              # Version 2
    infos = a.store.list_revisions()
    assert [i.number for i in infos] == [2, 1]
    assert (infos[0].added, infos[0].changed) == (1, 1)
    b.sync()                                              # Version 3 (neues Gerät registriert)

    # einzelne Datei aus Version 1 holen
    v1 = a.store.load_revision(1)
    e = [x for x in v1.entries if x.logical == "{DOCUMENTS}/notiz.txt"]
    acts = plan_restore(v1, e, a.mapper, a.catalog, "linux", tmp_path / "st")
    run_restore(a.store, v1, acts, a.catalog, ConflictPolicy.KEEP_BOTH, Reporter())
    assert a.p("DOCUMENTS", "notiz.yaleno-v1.txt").read_text() == "hallo"

    # ganzen Speicher auf Version 1 zurücksetzen → alle Geräte folgen beim Abgleich
    rev = a.store.revert_to(1, "laptop", "linux")
    assert rev.number == 4 and rev.info.message == "Zurückgesetzt auf Version 1"
    b.sync()
    assert b.p("DOCUMENTS", "notiz.txt").read_text() == "hallo"
    assert not b.p("DOCUMENTS", "spaeter.txt").exists()
    # und wieder vor auf Version 2
    a.store.revert_to(2, "laptop", "linux")
    b.sync()
    assert b.p("DOCUMENTS", "notiz.txt").read_text() == "v2"
    assert b.p("DOCUMENTS", "spaeter.txt").read_text() == "erst ab v2"


def test_restore_device_data_goes_to_staging(two, tmp_path):
    a, b = two
    a.sync()
    head = b.store.load_head()
    entries = [e for e in head.entries if e.scope == "host:laptop"]
    acts = plan_restore(head, entries, b.mapper, b.catalog, "linux", tmp_path / "st")
    assert {x.kind for x in acts} == {ActionKind.STAGING}
    run_restore(b.store, head, acts, b.catalog, ConflictPolicy.SKIP, Reporter())
    assert (tmp_path / "st" / "system/ROOT/etc/fstab").read_text() == "UUID=1 / ext4"


def test_restore_rejects_path_traversal(two, tmp_path):
    a, _ = two
    a.sync()
    head = a.store.load_head()
    evil = Entry("personal", "{DOCUMENTS}/../../../etc/passwd", size=1, scope="all")
    assert plan_restore(head, [evil], a.mapper, a.catalog, "linux", tmp_path / "st")[0].kind == ActionKind.BLOCKED


def test_corrupted_object_detected(two, tmp_path):
    a, b = two
    a.sync()
    head = a.store.load_head()
    e = next(x for x in head.entries if x.logical == "{DOCUMENTS}/notiz.txt")
    (tmp_path / "server" / a.store.object_path(e.sha256)).write_text("kaputt")
    plan, state = b.plan()
    res = run_sync(b.store, plan, state, b.catalog, b.mapper, "linux", "desktop", ConflictWinner.NEWER, Reporter())
    assert [f[0] for f in res.failed] == ["{DOCUMENTS}/notiz.txt"]
    assert not b.p("DOCUMENTS", "notiz.txt").exists()


# ---------------------------------------------------------------------- Sperre / Abbruch
def test_lock(two, tmp_path):
    a, b = two
    a.store.acquire_lock("laptop")
    with pytest.raises(StoreLocked, match="laptop"):
        b.sync()
    a.store.release_lock()
    b.sync()
    # verwaiste Sperre wird nach einer Weile übernommen
    lock = tmp_path / "server" / "daten" / "yaleno" / "lock"
    lock.write_text(json.dumps({"host": "alt", "token": "x", "since": "2020-01-01T00:00:00"}))
    a.sync()
    assert not lock.exists()


def test_store_changed_between_plan_and_run(two):
    a, b = two
    a.sync()
    plan, state = b.plan()
    a.p("DOCUMENTS", "zwischendurch.txt").write_text("x")
    a.sync()
    with pytest.raises(RuntimeError, match="inzwischen"):
        run_sync(b.store, plan, state, b.catalog, b.mapper, "linux", "desktop", ConflictWinner.NEWER, Reporter())
    res = run_sync(b.store, plan, state, b.catalog, b.mapper, "linux", "desktop", ConflictWinner.NEWER,
                   Reporter(), replan=lambda: b.plan()[0])
    assert b.p("DOCUMENTS", "zwischendurch.txt").read_text() == "x"
    assert not res.failed


def test_dry_run_changes_nothing(two, tmp_path):
    a, _ = two
    plan, state = a.plan()
    res = run_sync(a.store, plan, state, a.catalog, a.mapper, "linux", "laptop", ConflictWinner.NEWER,
                   Reporter(), dry_run=True)
    assert res.revision == 0 and a.store.head() == 0


def test_cancelled_sync_is_consistent(two):
    a, b = two
    rep = Reporter()
    rep.cancel()
    plan, state = a.plan()
    res = run_sync(a.store, plan, state, a.catalog, a.mapper, "linux", "laptop", ConflictWinner.NEWER, rep)
    assert res.cancelled
    # nächster Abgleich holt alles nach
    r = a.sync()
    assert r.uploaded > 0
    b.sync()
    assert b.p("DOCUMENTS", "notiz.txt").read_text() == "hallo"


def test_revision_timestamps(two):
    a, _ = two
    plan, state = a.plan()
    res = run_sync(a.store, plan, state, a.catalog, a.mapper, "linux", "laptop", ConflictWinner.NEWER,
                   Reporter(), now=datetime(2026, 11, 9, 12, 0))
    info = a.store.list_revisions()[0]
    assert info.number == res.revision == 1
    assert info.created == "2026-11-09T12:00:00" and info.host == "laptop"
