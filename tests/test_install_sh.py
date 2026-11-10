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


# ---------------------------------------------------------------------- install.sh im Hauptordner
ONE_SH = ROOT / "install.sh"
needs_x86 = pytest.mark.skipif(__import__("platform").machine() != "x86_64", reason="Releases nur für x86_64")


def app_stub(path: Path, version: str, log: Path) -> Path:
    """Platzhalter-Programm: kennt --version, --install (kopiert sich nach ~/.local/bin), --uninstall."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/bin/sh\n"
        f'echo "$(basename "$0") $*" >> "{log}"\n'
        'case "$1" in\n'
        f"  --version) echo {version} ;;\n"
        '  --install) mkdir -p "$HOME/.local/bin"; cp "$0" "$HOME/.local/bin/yaleno-wizard";'
        ' chmod +x "$HOME/.local/bin/yaleno-wizard" ;;\n'
        '  --uninstall) rm -f "$HOME/.local/bin/yaleno-wizard" ;;\n'
        "esac\n")
    path.chmod(0o755)
    return path


def fake_release(tmp_path: Path, version: str, log: Path) -> Path:
    """Release-Archiv + API-Antwort wie bei GitHub; gibt die API-Datei zurück."""
    rel = tmp_path / f"release-{version}"
    pkg = rel / f"yaleno-wizard-{version}"
    app_stub(pkg / "yaleno-wizard", version, log)
    archive = rel / f"yaleno-wizard-{version}-linux-x86_64.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(pkg, arcname=pkg.name)
    api = rel / "latest.json"
    api.write_text('{"tag_name": "v%s", "assets": [{"name": "%s", "size": 1,\n'
                   '  "browser_download_url": "file://%s"}]}' % (version, archive.name, archive))
    return api


def run_one(*args: str, home: Path, api: str = "none", **env: str) -> subprocess.CompletedProcess:
    full = {"PATH": os.environ["PATH"], "HOME": str(home), "YALENO_API": api, **env}
    return subprocess.run(["sh", str(ONE_SH), *args], cwd=home, env=full, capture_output=True, text=True)


def test_one_needs_action(home):
    r = run_one(home=home)
    assert r.returncode == 2 and "--install" in r.stderr
    r = run_one("--install", "--uninstall", home=home)
    assert r.returncode == 1 and "nur eine" in r.stderr
    r = run_one("--bla", home=home)
    assert r.returncode == 2 and "Unbekannte Option: --bla" in r.stderr
    r = run_one("--help", home=home)
    assert r.returncode == 0 and "--update" in r.stdout


@needs_x86
def test_one_install_update_uninstall_release(tmp_path, home):
    log = tmp_path / "log"
    api = fake_release(tmp_path, "0.2.0", log)
    r = run_one("--install", home=home, api=f"file://{api}")
    assert r.returncode == 0, r.stderr
    assert (home / ".local/bin/yaleno-wizard").exists()
    assert "Yaleno Wizard 0.2.0 ist installiert" in r.stdout

    r = run_one("--update", home=home, api=f"file://{api}")
    assert r.returncode == 0, r.stderr
    assert "0.2.0 ist aktuell" in r.stdout

    api = fake_release(tmp_path, "0.10.0", log)  # Versionsvergleich numerisch, nicht als Text
    r = run_one("--update", home=home, api=f"file://{api}")
    assert r.returncode == 0, r.stderr
    assert "0.2.0 → 0.10.0" in r.stdout and "0.10.0 ist installiert" in r.stdout

    r = run_one("--uninstall", home=home)
    assert r.returncode == 0, r.stderr
    assert not (home / ".local/bin/yaleno-wizard").exists()
    assert not (home / ".local/share/yaleno-wizard").exists()
    r = run_one("--uninstall", home=home)
    assert "nichts zu entfernen" in r.stdout


@needs_x86
def test_one_update_installs_when_missing(tmp_path, home):
    api = fake_release(tmp_path, "0.2.0", tmp_path / "log")
    r = run_one("--update", home=home, api=f"file://{api}")
    assert r.returncode == 0, r.stderr
    assert "noch nicht installiert" in r.stdout and (home / ".local/bin/yaleno-wizard").exists()


def test_one_update_source_already_current(tmp_path, home):
    """Ohne Release: gleicher Quellcode-Stand wie installiert → nichts bauen."""
    repo = tmp_path / "repo"
    repo.mkdir()
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git[:3], "init", "-q", "-b", "main"], check=True)
    (repo / "x").write_text("x")
    subprocess.run([*git, "add", "x"], check=True)
    subprocess.run([*git, "commit", "-qm", "x"], check=True)
    sha = subprocess.run([*git[:3], "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    app_stub(home / ".local/bin/yaleno-wizard", "0.2.0", tmp_path / "log")
    (home / ".local/share/yaleno-wizard").mkdir(parents=True)
    (home / ".local/share/yaleno-wizard/installed-from").write_text(f"source {sha}\n")
    r = run_one("--update", home=home, YALENO_REPO=str(repo))
    assert r.returncode == 0, r.stderr
    assert f"0.2.0 ist aktuell (Quellcode-Stand {sha[:7]})" in r.stdout
    assert not (home / ".local/share/yaleno-wizard/build").exists()
