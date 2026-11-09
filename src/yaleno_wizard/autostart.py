"""Hintergrund-Abgleich beim Anmelden starten (Linux: XDG-Autostart, Windows: Run-Schlüssel)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import APP_ID, APP_NAME, settings

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def app_command(executable: str | None = None) -> list[str]:
    """Befehl, der den Yaleno Wizard startet (installierte Binärdatei oder Python-Modul)."""
    if executable:
        return [executable]
    if getattr(sys, "frozen", False):  # PyInstaller-Binärdatei
        return [sys.executable]
    exe = sys.executable
    if sys.platform.startswith("win"):
        pyw = Path(exe).with_name("pythonw.exe")  # ohne Konsolenfenster
        if pyw.exists():
            exe = str(pyw)
    return [exe, "-m", "yaleno_wizard"]


def quote_exec(args: list[str]) -> str:
    """Exec-Zeile für .desktop-Dateien."""
    return " ".join(_quote(a) for a in args)


def background_command(executable: str | None = None) -> list[str]:
    """Befehl, der den Hintergrund-Abgleich (Symbol im Infobereich) startet."""
    cmd = app_command(executable)
    cmd.append("--background")
    if settings._config_override is not None:
        cmd += ["--config", str(settings._config_override)]
    return cmd


def _desktop_file() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / f"{APP_ID}.desktop"


def _quote(arg: str) -> str:
    if any(c in arg for c in ' \t\n"\'\\$`'):
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`") + '"'
    return arg


def is_enabled() -> bool:
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_ID)
            return True
        except OSError:
            return False
    return _desktop_file().exists()


def set_enabled(enabled: bool, executable: str | None = None) -> None:
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        import winreg
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            if enabled:
                winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(background_command(executable)))
            else:
                try:
                    winreg.DeleteValue(k, APP_ID)
                except OSError:
                    pass
        return
    f = _desktop_file()
    if not enabled:
        f.unlink(missing_ok=True)
        return
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME} (Hintergrund-Abgleich)\n"
        "Comment=Gleicht dieses Gerät regelmäßig mit dem zentralen Speicher ab\n"
        f"Exec={quote_exec(background_command(executable))}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        "X-KDE-autostart-after=panel\n",
        encoding="utf-8",
    )


def launch_background() -> None:
    """Startet den Hintergrund-Abgleich als eigenen Prozess (läuft weiter, wenn der Wizard schließt)."""
    kwargs: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
                    "close_fds": True}
    if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(background_command(), **kwargs)
