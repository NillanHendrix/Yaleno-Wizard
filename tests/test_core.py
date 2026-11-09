from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.catalog.placeholders import PathMapper, _read_user_dirs
from yaleno_wizard.core.backup import run_backup
from yaleno_wizard.core.entry import Entry
from yaleno_wizard.core.inventory import apply_inventory, export_inventory, parse_inventory
from yaleno_wizard.core.manifest import list_snapshots, load_manifest
from yaleno_wizard.core.reporter import Reporter
from yaleno_wizard.core.restore import ActionKind, ConflictPolicy, plan_restore, run_restore
from yaleno_wizard.core.scanner import Scanner
from yaleno_wizard.storage.local import LocalStorage

LINUX = catalog_for("linux")


def scan(mapper, cats=None):
    return Scanner(mapper).scan(LINUX, cats)


# ------------------------------------------------------------------ placeholders
def test_mapper_roundtrip(mapper, fake_home):
    p = fake_home["DOCUMENTS"] / "a" / "b.txt"
    assert mapper.to_logical(p) == "{DOCUMENTS}/a/b.txt"
    assert mapper.to_local("{DOCUMENTS}/a/b.txt") == p
    # spezifischster Platzhalter gewinnt vor HOME
    assert mapper.to_logical(fake_home["CONFIG"] / "x") == "{CONFIG}/x"
    assert mapper.to_local("{APPDATA}/x") is None


def test_user_dirs(tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        'XDG_DOCUMENTS_DIR="$HOME/Dokumente"\nXDG_DOWNLOAD_DIR="$HOME/Downloads"\nXDG_MUSIC_DIR="$HOME/"\n'
    )
    d = _read_user_dirs(Path("/home/x"), cfg)
    assert d["DOCUMENTS"] == Path("/home/x/Dokumente")
    assert d["DOWNLOAD"] == Path("/home/x/Downloads")
    assert "MUSIC" not in d


# ------------------------------------------------------------------ scanner
def test_scan_categories_and_excludes(mapper):
    res = scan(mapper)
    logicals = {(e.category, e.logical) for e in res.entries}
    assert ("personal", "{DOCUMENTS}/Rechnungen/2026.pdf") in logicals
    assert ("shell", "{HOME}/.bashrc") in logicals
    assert ("shell", "{CONFIG}/fish/config.fish") in logicals
    assert ("keys", "{HOME}/.ssh/id_ed25519") in logicals
    assert ("desktop", "{CONFIG}/kwinrc") in logicals
    assert ("system", "{ROOT}/etc/fstab") in logicals
    assert ("apps", "{CONFIG}/someapp/settings.ini") in logicals
    # Excludes
    assert not any("node_modules" in l for _, l in logicals)
    assert not any("/Cache/" in l for _, l in logicals)
    # Dedup: fish/kde gehören nicht zusätzlich zu "apps"
    assert ("apps", "{CONFIG}/fish/config.fish") not in logicals
    assert ("apps", "{CONFIG}/kwinrc") not in logicals


def test_scan_subset(mapper):
    res = scan(mapper, ["personal"])
    assert {e.category for e in res.entries} == {"personal"}


# ------------------------------------------------------------------ inventory
def test_inventory_roundtrip(mapper):
    res = scan(mapper)
    chosen = [e for e in res.entries if e.category in ("personal", "shell")][:4]
    text = export_inventory(chosen, {"personal": "Persönliche Dateien"}, {"host": "pc"})
    inv = parse_inventory(text)
    assert not inv.errors
    assert inv.meta.get("host") == "pc"
    applied = apply_inventory(inv, res.entries)
    assert applied.selected == {e.key for e in chosen}
    assert applied.unmatched == []


def test_inventory_dirs_globs_excludes():
    entries = [
        Entry("personal", "{DOCUMENTS}/a/1.txt"),
        Entry("personal", "{DOCUMENTS}/a/2.txt"),
        Entry("personal", "{DOCUMENTS}/a/old/3.txt"),
        Entry("personal", "{DOWNLOADS}/x.iso"),
        Entry("personal", "{DOWNLOADS}/y.pdf"),
        Entry("shell", "{HOME}/.zshrc"),
    ]
    text = """# Yaleno Wizard Bestand v1
[personal]
{DOCUMENTS}/a/
!{DOCUMENTS}/a/old/
{DOWNLOADS}/*.pdf
{PICTURES}/gibtsnicht.jpg
[unbekannt]
{HOME}/x
"""
    r = apply_inventory(parse_inventory(text), entries)
    assert r.selected == {
        ("personal", "{DOCUMENTS}/a/1.txt"),
        ("personal", "{DOCUMENTS}/a/2.txt"),
        ("personal", "{DOWNLOADS}/y.pdf"),
    }
    assert [x.pattern for x in r.unmatched] == ["{PICTURES}/gibtsnicht.jpg", "{HOME}/x"]
    assert r.missing_categories == ["unbekannt"]


def test_inventory_errors():
    inv = parse_inventory("{HOME}/x\n[a]\n/etc/fstab\n")
    assert len(inv.errors) == 2


# ------------------------------------------------------------------ backup / restore
@pytest.fixture
def backed_up(mapper, tmp_path):
    storage = LocalStorage(tmp_path / "server")
    res = scan(mapper)
    r = run_backup(storage, "backups", "mein pc", "linux", LINUX, res.entries, Reporter(),
                   now=datetime(2026, 11, 9, 12, 0, 0))
    assert r.ok and not r.failed
    return storage, r, res


def test_backup_layout(backed_up, tmp_path):
    storage, r, res = backed_up
    assert r.snapshot_path == "backups/yaleno/mein-pc/2026-11-09_120000"
    root = tmp_path / "server" / r.snapshot_path
    assert (root / "manifest.json").is_file()
    assert (root / "files/personal/DOCUMENTS/Rechnungen/2026.pdf").read_text() == "pdf-inhalt"
    assert (root / "files/keys/HOME/.ssh/id_ed25519").stat().st_mode & 0o077 == 0
    snaps = list_snapshots(storage, "backups")
    assert [(s.host, s.snapshot) for s in snaps] == [("mein-pc", "2026-11-09_120000")]
    m = load_manifest(storage, snaps[0].path)
    assert len(m.entries) == len(res.entries)
    assert all(len(e.sha256) == 64 for e in m.entries)


def test_restore_same_os_with_policies(backed_up, mapper, fake_home, tmp_path):
    storage, r, _ = backed_up
    m = r.manifest
    doc = fake_home["DOCUMENTS"] / "notiz.txt"
    pdf = fake_home["DOCUMENTS"] / "Rechnungen" / "2026.pdf"
    doc.write_text("lokal geändert")
    pdf.unlink()
    staging = tmp_path / "staging"

    actions = plan_restore(m, m.entries, mapper, LINUX, "linux", staging)
    kinds = {a.entry.logical: a.kind for a in actions}
    assert kinds["{ROOT}/etc/fstab"] == ActionKind.STAGING  # requires_admin

    # SKIP: geänderte Datei bleibt, gelöschte kommt zurück, unveränderte werden erkannt
    res = run_restore(storage, r.snapshot_path, m, actions, LINUX, ConflictPolicy.SKIP, Reporter())
    assert not res.failed
    assert doc.read_text() == "lokal geändert"
    assert pdf.read_text() == "pdf-inhalt"
    assert res.unchanged > 0
    assert (staging / "system/ROOT/etc/fstab").read_text() == "UUID=1 / ext4"

    # KEEP_BOTH
    run_restore(storage, r.snapshot_path, m, actions, LINUX, ConflictPolicy.KEEP_BOTH, Reporter())
    assert doc.read_text() == "lokal geändert"
    assert (doc.parent / "notiz.yaleno-2026-11-09_120000.txt").read_text() == "hallo"

    # OVERWRITE
    run_restore(storage, r.snapshot_path, m, actions, LINUX, ConflictPolicy.OVERWRITE, Reporter())
    assert doc.read_text() == "hallo"


def test_restore_dry_run_writes_nothing(backed_up, mapper, fake_home, tmp_path):
    storage, r, _ = backed_up
    pdf = fake_home["DOCUMENTS"] / "Rechnungen" / "2026.pdf"
    pdf.unlink()
    actions = plan_restore(r.manifest, r.manifest.entries, mapper, LINUX, "linux", tmp_path / "st")
    res = run_restore(storage, r.snapshot_path, r.manifest, actions, LINUX, ConflictPolicy.OVERWRITE,
                      Reporter(), dry_run=True)
    assert res.written >= 1
    assert not pdf.exists()


def test_restore_cross_os_only_personal(backed_up, tmp_path):
    storage, r, _ = backed_up
    win_home = tmp_path / "winhome"
    win_mapper = PathMapper({
        "HOME": win_home, "DOCUMENTS": win_home / "Documents", "PICTURES": win_home / "Pictures",
        "APPDATA": win_home / "AppData" / "Roaming",
    })
    actions = plan_restore(r.manifest, r.manifest.entries, win_mapper, catalog_for("windows"), "windows",
                           tmp_path / "st")
    for a in actions:
        if a.entry.category == "personal":
            assert a.kind == ActionKind.FILE
        else:
            assert a.kind == ActionKind.BLOCKED
    res = run_restore(storage, r.snapshot_path, r.manifest, actions, catalog_for("windows"),
                      ConflictPolicy.SKIP, Reporter())
    assert (win_home / "Documents" / "Rechnungen" / "2026.pdf").read_text() == "pdf-inhalt"
    assert not (win_home / ".bashrc").exists()
    assert not res.failed


def test_restore_rejects_path_traversal(backed_up, mapper, tmp_path):
    _, r, _ = backed_up
    evil = Entry("personal", "{DOCUMENTS}/../../../etc/passwd", size=1)
    actions = plan_restore(r.manifest, [evil], mapper, LINUX, "linux", tmp_path / "st")
    assert actions[0].kind == ActionKind.BLOCKED


def test_corrupted_file_detected(backed_up, mapper, fake_home, tmp_path):
    storage, r, _ = backed_up
    (tmp_path / "server" / r.snapshot_path / "files/personal/DOCUMENTS/notiz.txt").write_text("kaputt")
    (fake_home["DOCUMENTS"] / "notiz.txt").unlink()
    entries = [e for e in r.manifest.entries if e.logical == "{DOCUMENTS}/notiz.txt"]
    actions = plan_restore(r.manifest, entries, mapper, LINUX, "linux", tmp_path / "st")
    res = run_restore(storage, r.snapshot_path, r.manifest, actions, LINUX, ConflictPolicy.SKIP, Reporter())
    assert len(res.failed) == 1
    assert not (fake_home["DOCUMENTS"] / "notiz.txt").exists()


def test_cancelled_backup_has_no_manifest(mapper, tmp_path):
    storage = LocalStorage(tmp_path / "server")
    rep = Reporter()
    rep.cancel()
    r = run_backup(storage, ".", "pc", "linux", LINUX, scan(mapper).entries, rep)
    assert r.cancelled and not r.ok
    assert list_snapshots(storage, ".") == []
