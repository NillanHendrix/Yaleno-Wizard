"""Einstellungsdatei (YAML), gespeicherte Passwörter, Hintergrund-Abgleich, Autostart."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from yaleno_wizard import autostart, credentials, settings
from yaleno_wizard.catalog import catalog_for
from yaleno_wizard.catalog.placeholders import PathMapper
from yaleno_wizard.core.background import BackgroundError, excluded_selection, sync_once
from yaleno_wizard.core.entry import Entry
from yaleno_wizard.core.store import Store
from yaleno_wizard.settings import ConfigError, Profile
from yaleno_wizard.storage.local import LocalStorage

from .conftest import build_home

LINUX = catalog_for("linux")


# ---------------------------------------------------------------------- YAML
def test_yaml_roundtrip_and_permissions(tmp_path):
    p = Profile(storage_type="webdav", webdav_url="https://cloud.example.org", webdav_user="niko",
                webdav_folder="Yaleno", backup_name="laptop", sync_categories=["personal", "shell"],
                sync_excludes={"personal": ["{DOWNLOADS}/"]}, conflicts="remote", bg_enabled=True,
                bg_interval=30, bg_autostart=True)
    p.save()
    f = settings.config_file()
    assert f == tmp_path / "cfg" / "yaleno-wizard" / "yaleno.yml"
    assert f.stat().st_mode & 0o777 == 0o600
    text = f.read_text()
    assert text.startswith("# Yaleno Wizard")
    assert "url: https://cloud.example.org" in text and "interval_minutes: 30" in text
    assert Profile.load() == p


def test_hand_written_yaml_with_password(tmp_path):
    f = tmp_path / "meine.yml"
    f.write_text("""
storage:
  type: nextcloud
  webdav:
    url: https://cloud.example.org/
    username: niko
    password: abcde-fghij
device: buero-pc
sync:
  categories: [personal]
background:
  enabled: true
""")
    settings.set_config_file(f)
    p = Profile.load()
    assert p.storage_type == "webdav" and p.password_store == "file"
    assert p.webdav_folder == "Yaleno" and p.backup_name == "buero-pc" and p.bg_interval == 15
    assert credentials.load_secret(p) == "abcde-fghij"


@pytest.mark.parametrize("text, msg", [
    ("storage: [1, 2]", "Abschnitt"),
    ("storage:\n  type: ftp", "Speichertyp"),
    ("sync:\n  conflicts: egal", "Konfliktregel"),
    ("storage:\n  sftp:\n    port: abc", "Zahl"),
    ("storage: {type: sftp", "YAML"),
])
def test_invalid_yaml(tmp_path, text, msg):
    f = tmp_path / "x.yml"
    f.write_text(text)
    with pytest.raises(ConfigError, match=msg):
        Profile.read(f)


def test_migrates_old_profile_json(tmp_path):
    d = tmp_path / "cfg" / "yaleno-wizard"
    d.mkdir(parents=True)
    (d / "profile.json").write_text(json.dumps({"storage_type": "local", "local_dir": "/mnt/x",
                                                "backup_name": "pc", "unbekannt": 1}))
    p = Profile.load()
    assert (p.storage_type, p.local_dir, p.backup_name) == ("local", "/mnt/x", "pc")


# ---------------------------------------------------------------------- Passwörter
def test_secret_in_keyring(isolated_env):
    p = Profile(storage_type="webdav", webdav_url="https://c.example.org", webdav_user="niko")
    assert credentials.save_secret(p, "geheim", "keyring") == "keyring"
    assert p.webdav_password == "" and "geheim" not in p.to_yaml()
    assert isolated_env.data == {("yaleno-wizard", "webdav:niko@https://c.example.org"): "geheim"}
    assert credentials.load_secret(Profile(storage_type="webdav", webdav_url="https://c.example.org",
                                           webdav_user="niko")) == "geheim"
    # nicht mehr merken → aus dem Schlüsselbund entfernt
    credentials.save_secret(p, "geheim", "none")
    assert isolated_env.data == {} and p.password_store == "none"
    assert credentials.load_secret(p) is None


def test_secret_falls_back_to_file_without_keyring(monkeypatch):
    import keyring

    def broken(*a):
        raise RuntimeError("kein Schlüsselbund")

    monkeypatch.setattr(keyring, "set_password", broken)
    p = Profile(storage_type="sftp", host="h", username="u", key_path="/k")
    assert credentials.save_secret(p, "pass", "keyring") == "file"
    p.save()
    assert Profile.load().sftp_passphrase == "pass"
    assert credentials.load_secret(Profile.load()) == "pass"


# ---------------------------------------------------------------------- Hintergrund-Abgleich
def _profile(tmp_path, cats=("personal", "shell")) -> Profile:
    return Profile(storage_type="local", local_dir=str(tmp_path / "speicher"), backup_name="laptop",
                   sync_categories=list(cats), bg_enabled=True)


def test_background_sync_and_excludes(tmp_path):
    a = PathMapper(build_home(tmp_path, "laptop"))
    p = _profile(tmp_path)
    p.sync_excludes = {"personal": ["{PICTURES}/"], "shell": ["{CONFIG}/fish/config.fish"]}
    out = sync_once(p, mapper=a, catalog=LINUX, os_name="linux")
    assert out.device == "laptop" and not out.result.failed
    head = Store(LocalStorage(tmp_path / "speicher"), ".").load_head()
    logicals = {e.logical for e in head.entries}
    assert "{DOCUMENTS}/notiz.txt" in logicals and "{HOME}/.bashrc" in logicals
    assert not any(l.startswith("{PICTURES}") for l in logicals)
    assert "{CONFIG}/fish/config.fish" not in logicals

    # zweites Gerät im Hintergrund: holt alles, was nicht abgewählt ist
    b = PathMapper(build_home(tmp_path, "desktop", files=False))
    p2 = _profile(tmp_path)
    p2.backup_name = "desktop"
    sync_once(p2, mapper=b, catalog=LINUX, os_name="linux")
    assert b.to_local("{DOCUMENTS}/notiz.txt").read_text() == "hallo"


def test_background_needs_categories(tmp_path):
    p = _profile(tmp_path)
    p.sync_categories = None
    with pytest.raises(BackgroundError, match="Kategorien"):
        sync_once(p, mapper=PathMapper(build_home(tmp_path)), catalog=LINUX, os_name="linux")


def test_background_refuses_mass_deletion(tmp_path):
    home = build_home(tmp_path, "laptop")
    docs = home["DOCUMENTS"]
    for i in range(40):
        (docs / f"datei{i}.txt").write_text(str(i))
    m = PathMapper(home)
    p = _profile(tmp_path, ("personal",))
    sync_once(p, mapper=m, catalog=LINUX, os_name="linux")
    for i in range(40):
        (docs / f"datei{i}.txt").unlink()
    with pytest.raises(BackgroundError, match="40 von"):
        sync_once(p, mapper=m, catalog=LINUX, os_name="linux")
    assert len(Store(LocalStorage(tmp_path / "speicher"), ".").load_head().entries) > 40


def test_missing_base_folder_is_not_a_deletion(tmp_path):
    import shutil
    home = build_home(tmp_path, "laptop")
    m = PathMapper(home)
    p = _profile(tmp_path, ("personal",))
    sync_once(p, mapper=m, catalog=LINUX, os_name="linux")
    shutil.rmtree(home["PICTURES"])  # z. B. Laufwerk nicht eingehängt
    out = sync_once(p, mapper=m, catalog=LINUX, os_name="linux")
    assert out.result.deleted_remote == 0
    assert any(e.logical.startswith("{PICTURES}") for e in Store(LocalStorage(tmp_path / "speicher"), ".").load_head().entries)


def test_excluded_selection():
    es = [Entry("personal", "{DOCUMENTS}/a/1"), Entry("personal", "{DOCUMENTS}/b"), Entry("shell", "{HOME}/.x")]
    assert excluded_selection(es, {}) is None
    assert excluded_selection(es, {"personal": ["{DOCUMENTS}/a/"]}) == {("personal", "{DOCUMENTS}/b"),
                                                                       ("shell", "{HOME}/.x")}
    assert excluded_selection(es, {"shell": ["*"]}) == {("personal", "{DOCUMENTS}/a/1"), ("personal", "{DOCUMENTS}/b")}


def test_cli_sync_with_config_file(tmp_path, monkeypatch, capsys):
    from yaleno_wizard.__main__ import main
    home = build_home(tmp_path, "home")
    monkeypatch.setenv("HOME", str(home["HOME"]))
    (tmp_path / "cfg").mkdir(exist_ok=True)
    (tmp_path / "cfg" / "user-dirs.dirs").write_text('XDG_DOCUMENTS_DIR="$HOME/Dokumente"\n'
                                                      'XDG_PICTURES_DIR="$HOME/Bilder"\n')
    cfg = tmp_path / "cli.yml"
    cfg.write_text(f"storage:\n  type: local\n  local:\n    path: {tmp_path / 'speicher'}\n"
                   "device: cli-pc\nsync:\n  categories: [personal]\n")
    assert main(["--sync", "--config", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "Abgleich abgeschlossen: 3 hochgeladen" in out
    assert (tmp_path / "state" / "yaleno-wizard" / "log" / "hintergrund.log").exists()
    settings.set_config_file(None)

    cfg.write_text("storage:\n  type: local\n  local:\n    path: /x\n")
    assert main(["--sync", "--config", str(cfg)]) == 2
    settings.set_config_file(None)


# ---------------------------------------------------------------------- Autostart
def test_autostart_desktop_file(tmp_path):
    assert not autostart.is_enabled()
    settings.set_config_file(tmp_path / "mit leerzeichen.yml")
    autostart.set_enabled(True)
    f = tmp_path / "cfg" / "autostart" / "yaleno-wizard.desktop"
    text = f.read_text()
    assert "Exec=" in text and "--background" in text
    assert f'--config "{tmp_path / "mit leerzeichen.yml"}"' in text
    assert autostart.is_enabled()
    autostart.set_enabled(False)
    assert not f.exists()
    settings.set_config_file(None)


# ---------------------------------------------------------------------- Logo / Installation
def test_icons_present_and_valid():
    import struct
    from yaleno_wizard import assets
    for s in assets.PNG_SIZES:
        assert assets.png(s).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    data = assets.ico().read_bytes()
    reserved, typ, count = struct.unpack("<HHH", data[:6])
    assert (reserved, typ, count) == (0, 1, 7)
    assert assets.svg().read_text().lstrip().startswith("<?xml")


def test_install_and_uninstall_linux(tmp_path, monkeypatch):
    from yaleno_wizard import install
    monkeypatch.setenv("HOME", str(tmp_path / "h"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "h" / ".local" / "share"))
    fake_exe = tmp_path / "download" / "yaleno-wizard"
    fake_exe.parent.mkdir()
    fake_exe.write_bytes(b"#!/bin/sh\n")
    autostart.set_enabled(True)  # zeigt bisher auf den Download-Ort

    done = install.install_linux(fake_exe, refresh=False)
    target = tmp_path / "h" / ".local" / "bin" / "yaleno-wizard"
    assert target.read_bytes() == b"#!/bin/sh\n" and os.access(target, os.X_OK)
    desktop = (tmp_path / "h" / ".local" / "share" / "applications" / "yaleno-wizard.desktop").read_text()
    assert f"Exec={target}\n" in desktop and "Icon=yaleno-wizard\n" in desktop
    assert "Name=Yaleno Wizard" in desktop and f"Exec={target} --background" in desktop
    icons = tmp_path / "h" / ".local" / "share" / "icons" / "hicolor"
    assert (icons / "256x256" / "apps" / "yaleno-wizard.png").exists()
    assert (icons / "scalable" / "apps" / "yaleno-wizard.svg").exists()
    auto = (tmp_path / "cfg" / "autostart" / "yaleno-wizard.desktop").read_text()
    assert f"Exec={target} --background" in auto and "Icon=yaleno-wizard" in auto
    assert any("Autostart" in d for d in done)

    # aus dem Quellcode: kein Kopieren, Python-Modul als Befehl
    install.install_linux(None, refresh=False)
    assert "-m yaleno_wizard" in (tmp_path / "h" / ".local" / "share" / "applications" / "yaleno-wizard.desktop").read_text()

    install.uninstall_linux(refresh=False)
    assert not target.exists() and not (icons / "256x256" / "apps" / "yaleno-wizard.png").exists()
    assert not (tmp_path / "h" / ".local" / "share" / "applications" / "yaleno-wizard.desktop").exists()
    assert not autostart.is_enabled()


def test_desktop_entry_is_valid():
    import shutil
    import subprocess
    from yaleno_wizard import install
    if not shutil.which("desktop-file-validate"):
        pytest.skip("desktop-file-validate nicht installiert")
    f = Path(os.environ.get("XDG_CONFIG_HOME", "/tmp")) / "test.desktop"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(install.desktop_entry(["/usr/bin/yaleno-wizard"]))
    r = subprocess.run(["desktop-file-validate", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
