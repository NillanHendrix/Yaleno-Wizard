"""Klickt den Wizard headless (offscreen) durch: Abgleichen, Verlauf, Zurücksetzen."""

from __future__ import annotations

import os
import time

import pytest

pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")

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


def _run_to_end(w, wz):
    prog = w.page(wz.P_PROGRESS)
    _wait(prog.isComplete)
    return prog


def _choose_categories(w, wz, ids):
    cats = w.page(wz.P_CATEGORIES)
    _wait(cats.isComplete)
    for i in range(cats.list.count()):
        it = cats.list.item(i)
        on = it.data(Qt.ItemDataRole.UserRole) in ids
        it.setCheckState(Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)
    w.next()


def test_wizard_sync_and_history(app, tmp_path, monkeypatch, mapper, fake_home):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from yaleno_wizard.gui import wizard as wz

    w = wz.YalenoWizard()
    w.state.mapper = mapper
    w.show()

    conn = w.page(wz.P_CONNECTION)
    conn.rb_local.setChecked(True)
    conn.local_dir.setText(str(tmp_path / "speicher"))
    w.next()
    assert w.currentId() == wz.P_MODE, conn.status.text()

    mode = w.page(wz.P_MODE)
    assert not mode.rb_history.isEnabled()  # Speicher noch leer
    mode.name.setText("testpc")
    mode.rb_sync.setChecked(True)
    w.next()
    _choose_categories(w, wz, ("personal", "shell"))

    files = w.page(wz.P_FILES)
    n, _ = files.model.stats()
    assert n == 5  # 3 persönliche Dateien + .bashrc + config.fish (siehe conftest)
    inv_entries = [e for e in w.state.scan.entries if e.logical.startswith("{DOCUMENTS}/Rechnungen")]
    files.model.set_selection({e.key for e in inv_entries})
    assert files.model.stats()[0] == 1
    files.model.set_all(True)
    w.next()

    summary = w.page(wz.P_SUMMARY)
    assert w.currentId() == wz.P_SUMMARY
    _wait(summary.isComplete)
    assert "Hochladen" in summary.text.toPlainText()
    w.next()
    prog = _run_to_end(w, wz)
    assert "5 hochgeladen" in prog.result.text(), prog.log.toPlainText()

    # ---- zweiter Abgleich nach Änderung: neue Version 2
    (fake_home["DOCUMENTS"] / "notiz.txt").write_text("geändert")
    w.button(w.WizardButton.CustomButton1).click()
    assert w.currentId() == wz.P_MODE
    w.next()
    cats = w.page(wz.P_CATEGORIES)
    _wait(cats.isComplete)
    w.next()  # Kategorien gemerkt
    assert w.page(wz.P_FILES).model.stats()[0] == 5
    w.next()
    _wait(summary.isComplete)
    w.next()
    prog = _run_to_end(w, wz)
    assert "1 hochgeladen" in prog.result.text(), prog.log.toPlainText()

    # ---- Verlauf: notiz.txt aus Version 1 zurückholen (überschreiben)
    w.button(w.WizardButton.CustomButton1).click()
    w.page(wz.P_MODE).rb_history.setChecked(True)
    w.next()
    hist = w.page(wz.P_HISTORY)
    assert w.currentId() == wz.P_HISTORY
    assert hist.tree.topLevelItemCount() == 2
    _wait(hist.isComplete)
    assert not hist.rb_reset.isEnabled()  # aktuelle Version
    hist.older.click()
    assert hist._current() == 1
    assert hist.rb_reset.isEnabled()
    hist.rb_restore.setChecked(True)
    w.next()
    assert w.currentId() == wz.P_CATEGORIES
    w.next()
    files = w.page(wz.P_FILES)
    files.model.set_selection({("personal", "{DOCUMENTS}/notiz.txt")})
    w.next()
    summary.conflict.setCurrentIndex(2)  # überschreiben
    w.next()
    prog = _run_to_end(w, wz)
    assert "1 geschrieben" in prog.log.toPlainText(), prog.log.toPlainText()
    assert (fake_home["DOCUMENTS"] / "notiz.txt").read_text() == "hallo"

    # ---- Speicher auf Version 1 zurücksetzen
    w.button(w.WizardButton.CustomButton1).click()
    w.page(wz.P_MODE).rb_history.setChecked(True)
    w.next()
    _wait(hist.isComplete)
    hist.older.click()
    hist.rb_reset.setChecked(True)
    w.next()
    assert w.currentId() == wz.P_SUMMARY
    assert "Version 1" in summary.text.toPlainText()
    w.next()
    prog = _run_to_end(w, wz)
    assert "Version 3" in prog.result.text(), prog.log.toPlainText()
    assert w.state.store.head() == 3
    w.close()


def test_wizard_sync_over_webdav(app, tmp_path, monkeypatch, mapper, fake_home):
    pytest.importorskip("wsgidav")
    from .webdav_stub import PASSWORD, USER, DavServer

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    from yaleno_wizard.gui import wizard as wz

    (tmp_path / "dav").mkdir()
    srv = DavServer(tmp_path / "dav")
    try:
        w = wz.YalenoWizard()
        w.state.mapper = mapper
        w.show()
        conn = w.page(wz.P_CONNECTION)
        conn.rb_dav.setChecked(True)
        conn.dav_url.setText(srv.url)
        conn.dav_user.setText(USER)
        assert not conn.isComplete()  # ohne Passwort
        conn.dav_pw.setText("falsch")
        w.next()
        assert w.currentId() == wz.P_CONNECTION and "abgelehnt" in conn.status.text()
        conn.dav_pw.setText(PASSWORD)
        w.next()
        assert w.currentId() == wz.P_MODE, conn.status.text()
        assert w.state.profile.storage_type == "webdav"
        cfg = (tmp_path / "cfg" / "yaleno-wizard" / "yaleno.yml").read_text()
        assert PASSWORD not in cfg and "password_store: keyring" in cfg
        import keyring
        assert keyring.get_password("yaleno-wizard", f"webdav:{USER}@{srv.url}") == PASSWORD
        # neuer Wizard: Passwort ist vorausgefüllt
        w2 = wz.YalenoWizard()
        assert w2.page(wz.P_CONNECTION).dav_pw.text() == PASSWORD
        assert w2.page(wz.P_CONNECTION).rb_dav.isChecked()
        w2.close()
        w.page(wz.P_MODE).name.setText("testpc")
        w.next()
        _choose_categories(w, wz, ("personal",))
        w.next()
        _wait(w.page(wz.P_SUMMARY).isComplete)
        w.next()
        prog = _run_to_end(w, wz)
        assert "3 hochgeladen" in prog.result.text(), prog.log.toPlainText()
        assert (tmp_path / "dav" / "Yaleno" / "yaleno" / "HEAD").read_text().strip() == "1"
        w.close()
    finally:
        srv.close()


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


def test_tree_excluded_patterns(app):
    from yaleno_wizard.core.entry import Entry
    from yaleno_wizard.gui.file_tree_model import FileTreeModel
    entries = [Entry("personal", "{DOCUMENTS}/a/1.txt"), Entry("personal", "{DOCUMENTS}/a/b/2.txt"),
               Entry("personal", "{DOCUMENTS}/c.txt"), Entry("personal", "{PICTURES}/x.jpg"),
               Entry("shell", "{HOME}/.bashrc"), Entry("packages", "@cmd/pacman.txt", item="pacman")]
    m = FileTreeModel()
    keep = {("personal", "{DOCUMENTS}/c.txt"), ("personal", "{DOCUMENTS}/a/1.txt")}
    m.set_entries(entries, keep, {})
    assert m.excluded_patterns() == {
        "personal": ["{DOCUMENTS}/a/b/", "{PICTURES}/"],
        "shell": ["*"],
        "packages": ["*"],
    }
    from yaleno_wizard.core.background import excluded_selection
    assert excluded_selection(entries, m.excluded_patterns()) == keep


def test_tray_background_sync(app, tmp_path):
    from yaleno_wizard.core.background import BackgroundOutcome
    from yaleno_wizard.core.store import StoreLocked
    from yaleno_wizard.core.sync import SyncResult
    from yaleno_wizard.gui.tray import BackgroundSync, acquire_single_instance
    from yaleno_wizard.settings import Profile
    from datetime import datetime

    Profile(bg_enabled=True, bg_interval=7).save()
    calls = []

    def fake(profile, rep):
        calls.append(profile.bg_interval)
        if len(calls) == 2:
            raise StoreLocked("Der Speicher wird gerade von „x“ abgeglichen")
        rep.log("lief")
        return BackgroundOutcome(SyncResult(uploaded=2, conflicts=1), datetime.now(), "pc")

    bg = BackgroundSync(sync_fn=fake, show_tray=False)
    assert bg.timer.interval() == 7 * 60 * 1000
    results = []
    bg.finished.connect(results.append)
    bg.sync_now()
    _wait(lambda: len(results) == 1)
    assert "2 hochgeladen, 1 Konflikte" in bg.last
    bg.sync_now()
    _wait(lambda: len(results) == 2)
    assert "neuer Versuch" in bg.last

    # ausgeschaltet → automatischer Lauf beendet den Hintergrund-Abgleich
    Profile(bg_enabled=False).save()
    quit_called = []
    bg.quit = lambda: quit_called.append(1)
    bg.sync_now(automatic=True)
    assert quit_called and len(calls) == 2

    lock = acquire_single_instance()
    assert lock is not None and acquire_single_instance() is None
    lock.unlock()


def test_background_dialog(app, tmp_path):
    from yaleno_wizard import autostart
    from yaleno_wizard.gui.background_dialog import BackgroundDialog
    from yaleno_wizard.settings import Profile

    p = Profile(storage_type="webdav", webdav_url="https://x", webdav_user="u")
    dlg = BackgroundDialog(p)
    assert "Kategorien" in dlg.warn.text() and "App-Passwort" in dlg.warn.text()
    dlg.enabled.setChecked(True)
    dlg.interval.setValue(45)
    dlg.autostart.setChecked(True)
    dlg.conflicts.setCurrentIndex(2)
    dlg.apply()
    assert (p.bg_enabled, p.bg_interval, p.bg_autostart, p.conflicts) == (True, 45, True, "remote")
    assert autostart.is_enabled()
    dlg.enabled.setChecked(False)
    dlg.apply()
    assert not autostart.is_enabled()


def test_app_icon_has_all_sizes(app):
    from yaleno_wizard.assets import app_icon
    icon = app_icon()
    assert not icon.isNull()
    sizes = {s.width() for s in icon.availableSizes()}
    assert {16, 32, 48, 256} <= sizes
