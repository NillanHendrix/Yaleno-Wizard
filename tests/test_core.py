from __future__ import annotations

from pathlib import Path

from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.catalog.placeholders import PathMapper, _read_user_dirs
from yaleno_wizard.core.entry import Entry
from yaleno_wizard.core.inventory import apply_inventory, export_inventory, parse_inventory
from yaleno_wizard.core.scanner import Scanner

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
