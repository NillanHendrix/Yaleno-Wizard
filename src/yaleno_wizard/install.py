"""Einrichten im Startmenü (mit Logo) – für den aktuellen Benutzer, ohne Admin-Rechte.

Linux:   Programm nach ~/.local/bin, Startmenü-Eintrag (.desktop) und Symbole nach
         ~/.local/share (freedesktop-Standard, funktioniert in KDE, GNOME, XFCE …).
Windows: Verknüpfung im Startmenü. Normalerweise übernimmt das der Installer
         (yaleno-wizard-setup.exe); --install ist für die einzelne .exe gedacht.

Einstellungen, gespeicherte Passwörter und der Abgleich-Stand bleiben beim Entfernen erhalten.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME, autostart
from .assets import PNG_SIZES, png, svg


# ---------------------------------------------------------------------- Pfade (Linux)
def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def desktop_file() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_files() -> list[tuple[Path, Path]]:
    """(Quelle, Ziel) für alle Symbolgrößen im hicolor-Thema."""
    base = data_home() / "icons" / "hicolor"
    out = [(png(s), base / f"{s}x{s}" / "apps" / f"{APP_ID}.png") for s in PNG_SIZES]
    out.append((svg(), base / "scalable" / "apps" / f"{APP_ID}.svg"))
    return out


def desktop_entry(command: list[str]) -> str:
    exec_line = autostart.quote_exec(command)
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.5\n"
        f"Name={APP_NAME}\n"
        "GenericName=Geräte abgleichen\n"
        "GenericName[en]=Device sync\n"
        "Comment=Dateien und Einstellungen über einen zentralen Speicher zwischen Geräten abgleichen\n"
        "Comment[en]=Sync files and settings between devices through central storage\n"
        f"Exec={exec_line}\n"
        f"TryExec={command[0]}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Utility;Archiving;FileTools;Qt;\n"
        "Keywords=sync;backup;nextcloud;webdav;sftp;abgleich;sicherung;\n"
        f"StartupWMClass={APP_ID}\n"
        "StartupNotify=true\n"
        "Actions=background;\n"
        "\n"
        "[Desktop Action background]\n"
        "Name=Hintergrund-Abgleich starten\n"
        "Name[en]=Start background sync\n"
        f"Exec={autostart.quote_exec(command + ['--background'])}\n"
    )


def _refresh_caches() -> None:
    """Startmenü neu einlesen lassen (je nach Desktop; Fehler sind egal)."""
    for cmd in (
        ["update-desktop-database", str(data_home() / "applications")],
        ["gtk-update-icon-cache", "-q", "-t", "-f", str(data_home() / "icons" / "hicolor")],
        ["kbuildsycoca6", "--noincremental"],
        ["kbuildsycoca5", "--noincremental"],
    ):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60, check=False)
            except (OSError, subprocess.SubprocessError):
                pass


# ---------------------------------------------------------------------- Linux
def install_linux(executable: Path | None = None, refresh: bool = True) -> list[str]:
    """Richtet den Startmenü-Eintrag ein. ``executable``: Binärdatei, die installiert werden soll."""
    done: list[str] = []
    if executable is None and getattr(sys, "frozen", False):
        executable = Path(sys.executable)
    if executable is not None:
        target = bin_dir() / APP_ID
        target.parent.mkdir(parents=True, exist_ok=True)
        if executable.resolve() != target.resolve():
            tmp = target.with_name(target.name + ".part")
            shutil.copy2(executable, tmp)
            os.chmod(tmp, 0o755)
            os.replace(tmp, target)
            done.append(f"Programm: {target}")
        command = [str(target)]
    else:  # aus dem Quellcode / pip: Python-Modul starten
        command = autostart.app_command()

    for src, dst in icon_files():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    done.append(f"Symbole: {data_home() / 'icons' / 'hicolor'}")

    f = desktop_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(desktop_entry(command), encoding="utf-8")
    os.chmod(f, 0o755)
    done.append(f"Startmenü: {f}")

    if autostart.is_enabled():  # Autostart auf das installierte Programm umstellen
        autostart.set_enabled(True, command[0] if executable is not None else None)
        done.append("Autostart aktualisiert")
    if refresh:
        _refresh_caches()
    return done


def uninstall_linux(refresh: bool = True) -> list[str]:
    done: list[str] = []
    for path in [desktop_file(), *(dst for _, dst in icon_files()), bin_dir() / APP_ID]:
        if path.exists():
            path.unlink()
            done.append(f"entfernt: {path}")
    if autostart.is_enabled():
        autostart.set_enabled(False)
        done.append("Autostart entfernt")
    if refresh:
        _refresh_caches()
    return done


# ---------------------------------------------------------------------- Windows
def _start_menu() -> Path:  # pragma: no cover - nur Windows
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def install_windows() -> list[str]:  # pragma: no cover - nur Windows
    """Verknüpfung im Startmenü für eine einzelne .exe (der Installer macht das selbst)."""
    command = autostart.app_command()
    lnk = _start_menu() / f"{APP_NAME}.lnk"
    args = subprocess.list2cmdline(command[1:])
    ps = (
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:YLNK);"
        "$s.TargetPath=$env:YEXE;$s.Arguments=$env:YARGS;$s.IconLocation=$env:YEXE+',0';"
        "$s.Description='Dateien und Einstellungen zwischen Geräten abgleichen';$s.Save()"
    )
    env = {**os.environ, "YLNK": str(lnk), "YEXE": command[0], "YARGS": args}
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], env=env, check=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [f"Startmenü: {lnk}"]


def uninstall_windows() -> list[str]:  # pragma: no cover - nur Windows
    done = []
    lnk = _start_menu() / f"{APP_NAME}.lnk"
    if lnk.exists():
        lnk.unlink()
        done.append(f"entfernt: {lnk}")
    if autostart.is_enabled():
        autostart.set_enabled(False)
        done.append("Autostart entfernt")
    return done


# ---------------------------------------------------------------------- Einstieg
def main(uninstall: bool = False) -> int:
    win = sys.platform.startswith("win")
    try:
        if uninstall:
            done = uninstall_windows() if win else uninstall_linux()
            print("\n".join(done) or "Nichts zu entfernen.")
            print("Einstellungen und gespeicherte Passwörter bleiben erhalten.")
        else:
            done = install_windows() if win else install_linux()
            print("\n".join(done))
            print(f"✔ {APP_NAME} ist im Startmenü eingetragen.")
            if not win and str(bin_dir()) not in os.environ.get("PATH", "").split(os.pathsep):
                print(f"Hinweis: {bin_dir()} ist nicht im PATH – im Terminal ggf. mit vollem Pfad starten.")
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"FEHLER: {exc}")
        return 1
    return 0
