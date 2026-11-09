"""Klickt den Wizard headless (offscreen) einmal durch: Sichern und Wiederherstellen."""

from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from yaleno_wizard.core.inventory import export_inventory  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _wait(cond, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("Timeout")


def test_wizard_backup_and_restore(app, tmp_path, monkeypatch, mapper, fake_home):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from yaleno_wizard.gui import wizard as wz

    w = wz.YalenoWizard()
    w.state.mapper = mapper
    w.state.host_name = "testpc"
    w.show()

    conn = w.page(wz.P_CONNECTION)
    conn.rb_local.setChecked(True)
    conn.local_dir.setText(str(tmp_path / "speicher"))
    w.next()
    assert w.currentId() == wz.P_MODE, conn.status.text()

    w.page(wz.P_MODE).rb_backup.setChecked(True)
    w.next()
    cats = w.page(wz.P_CATEGORIES)
    _wait(cats.isComplete)
    # nur persönliche Dateien + Shell
    for i in range(cats.list.count()):
        it = cats.list.item(i)
        on = it.data(Qt.ItemDataRole.UserRole) in ("personal", "shell")
        it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    w.next()

    files = w.page(wz.P_FILES)
    n, _ = files.model.stats()
    assert n == 5  # 3 persönliche Dateien + .bashrc + config.fish (siehe conftest)
    # Bestand importieren: nur Dokumente-Ordner
    inv_entries = [e for e in w.state.scan.entries if e.logical.startswith("{DOCUMENTS}/Rechnungen")]
    sel = {e.key for e in inv_entries}
    files.model.set_selection(sel)
    assert files.model.stats()[0] == 1
    files.model.set_all(True)
    w.next()

    assert w.currentId() == wz.P_SUMMARY
    w.next()
    prog = w.page(wz.P_PROGRESS)
    _wait(prog.isComplete)
    assert "Gesichert" in prog.result.text(), prog.log.toPlainText()

    # ---- Wiederherstellen
    (fake_home["DOCUMENTS"] / "notiz.txt").unlink()
    (fake_home["HOME"] / ".bashrc").write_text("geändert")
    w.button(w.WizardButton.CustomButton1).click()
    assert w.currentId() == wz.P_MODE
    w.page(wz.P_MODE).rb_restore.setChecked(True)
    w.next()
    snap = w.page(wz.P_SNAPSHOT)
    assert snap.tree.topLevelItemCount() == 1
    _wait(snap.isComplete)
    w.next()
    w.next()  # Kategorien (Vorauswahl)
    files = w.page(wz.P_FILES)
    assert files.model.stats()[0] == 5
    w.next()
    summary = w.page(wz.P_SUMMARY)
    summary.conflict.setCurrentIndex(0)  # überspringen
    w.next()
    prog = w.page(wz.P_PROGRESS)
    _wait(prog.isComplete)
    log = prog.log.toPlainText()
    assert "1 geschrieben" in log, log
    assert (fake_home["DOCUMENTS"] / "notiz.txt").read_text() == "hallo"
    assert (fake_home["HOME"] / ".bashrc").read_text() == "geändert"
    w.close()


def test_export_contains_selection(mapper):
    from yaleno_wizard.catalog import catalog_for
    from yaleno_wizard.core.scanner import Scanner
    res = Scanner(mapper).scan(catalog_for("linux"), ["personal"])
    text = export_inventory(res.entries, {"personal": "Persönliche Dateien"})
    assert "[personal]" in text and "{DOCUMENTS}/notiz.txt" in text


def test_tree_tristate(app):
    from yaleno_wizard.core.entry import Entry
    from yaleno_wizard.gui.file_tree_model import FileTreeModel
    m = FileTreeModel()
    entries = [Entry("personal", "{DOCUMENTS}/a/1.txt", size=10), Entry("personal", "{DOCUMENTS}/a/2.txt", size=5),
               Entry("personal", "{DOCUMENTS}/b.txt", size=1)]
    m.set_entries(entries, None, {"personal": "Persönlich"})
    cat = m.index(0, 0)
    docs = m.index(0, 0, cat)
    folder_a = m.index(0, 0, docs)
    assert m.data(folder_a) == "a"
    first = m.index(0, 0, folder_a)
    m.setData(first, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert m.data(folder_a, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.PartiallyChecked
    assert m.data(cat, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.PartiallyChecked
    assert m.stats() == (2, 6)
    m.setData(cat, Qt.CheckState.Unchecked.value, Qt.ItemDataRole.CheckStateRole)
    assert m.stats() == (0, 0)
    m.setData(folder_a, Qt.CheckState.Checked.value, Qt.ItemDataRole.CheckStateRole)
    assert m.stats() == (2, 15)
    assert m.selected_keys() == {("personal", "{DOCUMENTS}/a/1.txt"), ("personal", "{DOCUMENTS}/a/2.txt")}
