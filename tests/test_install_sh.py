"""packaging/linux/install.sh und scripts/pack_linux.sh – mit einer Platzhalter-Programmdatei."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform.startswith("win"), reason="nur Linux")

ROOT = Path(__file__).resolve().parents[1]
INSTALL_SH = ROOT / "packaging" / "linux" / "install.sh"
PACK_SH = ROOT / "scripts" / "pack_linux.sh"


def stub(path: Path, log: Path) -> Path:
    """Platzhalter für die Programmdatei: schreibt ihren Pfad und ihre Argumente ins Protokoll."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'#!/bin/sh\necho "$0 $*" >> "{log}"\n')
    path.chmod(0o644)  # wie nach dem Entpacken ohne Ausführungsrecht
    return path


def run(script: Path, *args: str, home: Path, cwd: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    return subprocess.run(["sh", str(script), *args], cwd=cwd, env=env, capture_output=True, text=True)


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def test_archive_layout(tmp_path, home):
    pkg = tmp_path / "yaleno-wizard-0.1.0"
    pkg.mkdir()
    shutil.copy(INSTALL_SH, pkg / "install.sh")
    binary = stub(pkg / "yaleno-wizard", tmp_path / "log")
    r = run(pkg / "install.sh", home=home, cwd=tmp_path)  # Aufruf von außerhalb des Ordners
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "log").read_text() == f"{binary} --install\n"
    assert os.access(binary, os.X_OK)


def test_source_layout_uses_dist(tmp_path, home):
    repo = tmp_path / "repo"
    (repo / "packaging" / "linux").mkdir(parents=True)
    script = Path(shutil.copy(INSTALL_SH, repo / "packaging" / "linux" / "install.sh"))
    stub(repo / "dist" / "yaleno-wizard", tmp_path / "log")
    r = run(script, home=home, cwd=repo)
    assert r.returncode == 0, r.stderr
    log = (tmp_path / "log").read_text()
    assert log.endswith("dist/yaleno-wizard --install\n")


def test_missing_binary_explains(tmp_path, home):
    (tmp_path / "packaging" / "linux").mkdir(parents=True)
    script = Path(shutil.copy(INSTALL_SH, tmp_path / "packaging" / "linux" / "install.sh"))
    r = run(script, home=home, cwd=tmp_path)
    assert r.returncode == 1
    assert "Programmdatei 'yaleno-wizard' nicht gefunden" in r.stderr
    assert "pyinstaller yaleno_wizard.spec" in r.stderr
    assert "cannot access" not in r.stderr


def test_unknown_option(tmp_path, home):
    r = run(INSTALL_SH, "--foo", home=home, cwd=tmp_path)
    assert r.returncode == 2 and "Unbekannte Option" in r.stderr


def test_uninstall_uses_installed_program(tmp_path, home):
    installed = stub(home / ".local" / "bin" / "yaleno-wizard", tmp_path / "log")
    installed.chmod(0o755)
    r = run(INSTALL_SH, "--uninstall", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "log").read_text() == f"{installed} --uninstall\n"


def test_uninstall_without_installation(tmp_path, home):
    (tmp_path / "x").mkdir()
    script = Path(shutil.copy(INSTALL_SH, tmp_path / "x" / "install.sh"))
    r = run(script, "--uninstall", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "nichts zu entfernen" in r.stdout


def test_uninstall_falls_back_to_archive_binary(tmp_path, home):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    script = Path(shutil.copy(INSTALL_SH, pkg / "install.sh"))
    binary = stub(pkg / "yaleno-wizard", tmp_path / "log")
    r = run(script, "--uninstall", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "log").read_text() == f"{binary} --uninstall\n"


def test_pack_and_install_from_archive(tmp_path, home):
    repo = tmp_path / "repo"
    for rel in ("packaging/linux/install.sh", "scripts/pack_linux.sh", "src/yaleno_wizard/__init__.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, repo / rel)
    stub(repo / "dist" / "yaleno-wizard", tmp_path / "log")
    r = run(repo / "scripts" / "pack_linux.sh", home=home, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    archive = repo / r.stdout.strip()
    assert archive.name.endswith("-linux-x86_64.tar.gz")

    out = tmp_path / "download"
    with tarfile.open(archive) as tar:
        names = sorted(m.name for m in tar.getmembers() if m.isfile())
        assert all((m.mode & 0o111) for m in tar.getmembers() if m.isfile())
        tar.extractall(out, filter="data")
    top = names[0].split("/")[0]
    assert names == [f"{top}/install.sh", f"{top}/yaleno-wizard"]

    r = run(out / top / "install.sh", home=home, cwd=out / top)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "log").read_text() == f"{out / top / 'yaleno-wizard'} --install\n"


def test_pack_without_build(tmp_path, home):
    repo = tmp_path / "repo"
    for rel in ("scripts/pack_linux.sh", "src/yaleno_wizard/__init__.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, repo / rel)
    r = run(repo / "scripts" / "pack_linux.sh", home=home, cwd=tmp_path)
    assert r.returncode == 1 and "dist/yaleno-wizard fehlt" in r.stderr
