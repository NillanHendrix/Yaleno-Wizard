"""Logische Pfade mit Platzhaltern ↔ echte Pfade.

Ein logischer Pfad sieht so aus: ``{DOCUMENTS}/Rechnungen/2026.pdf``. Dadurch
lassen sich persönliche Dateien zwischen Linux und Windows übertragen, auch
wenn die Ordner unterschiedlich heißen (z.B. ~/Dokumente vs. C:\\Users\\x\\Documents).
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path, PurePath

from .model import OSName

PLACEHOLDER_RE = re.compile(r"^\{([A-Z_]+)\}(?:/(.*))?$")

DISPLAY_NAMES = {
    "HOME": "Benutzerordner",
    "DOCUMENTS": "Dokumente",
    "PICTURES": "Bilder",
    "MUSIC": "Musik",
    "VIDEOS": "Videos",
    "DESKTOP": "Schreibtisch",
    "DOWNLOADS": "Downloads",
    "CONFIG": "Konfiguration (~/.config)",
    "DATA": "Programmdaten (~/.local/share)",
    "APPDATA": "AppData\\Roaming",
    "LOCALAPPDATA": "AppData\\Local",
    "ROOT": "System",
}


def current_os() -> OSName:
    return "windows" if sys.platform.startswith("win") else "linux"


def split_logical(logical: str) -> tuple[str, str]:
    """``{DOCUMENTS}/a/b`` → (``DOCUMENTS``, ``a/b``)."""
    m = PLACEHOLDER_RE.match(logical)
    if not m:
        raise ValueError(f"Kein logischer Pfad: {logical!r}")
    return m.group(1), m.group(2) or ""


class PathMapper:
    def __init__(self, mapping: dict[str, Path]):
        self.mapping = {k: Path(v) for k, v in mapping.items() if v}
        # Spezifischste (längste) Basis zuerst prüfen, ROOT zuletzt.
        self._ordered = sorted(
            self.mapping.items(), key=lambda kv: (kv[0] == "ROOT", -len(kv[1].parts))
        )

    def base(self, placeholder: str) -> Path | None:
        return self.mapping.get(placeholder)

    def to_local(self, logical: str) -> Path | None:
        ph, rest = split_logical(logical)
        base = self.mapping.get(ph)
        if base is None:
            return None
        return base.joinpath(*[p for p in rest.split("/") if p]) if rest else base

    def to_logical(self, path: Path) -> str | None:
        for ph, base in self._ordered:
            try:
                rel = PurePath(path).relative_to(base)
            except ValueError:
                continue
            rel_posix = "/".join(rel.parts)
            return f"{{{ph}}}/{rel_posix}" if rel_posix else f"{{{ph}}}"
        return None

    @classmethod
    def for_current_system(cls) -> "PathMapper":
        if current_os() == "windows":
            return cls(_windows_mapping())
        return cls(_linux_mapping())


# --------------------------------------------------------------------- Linux
def _read_user_dirs(home: Path, config: Path) -> dict[str, Path]:
    """Liest ~/.config/user-dirs.dirs (XDG, lokalisierte Ordnernamen)."""
    result: dict[str, Path] = {}
    f = config / "user-dirs.dirs"
    if not f.is_file():
        return result
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r'^\s*XDG_([A-Z]+)_DIR\s*=\s*"(.*)"\s*$', line)
        if not m:
            continue
        value = m.group(2).replace("$HOME", str(home))
        p = Path(value)
        if p != home:  # XDG setzt deaktivierte Ordner auf $HOME
            result[m.group(1)] = p
    return result


def _linux_mapping() -> dict[str, Path]:
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    xdg = _read_user_dirs(home, config)
    defaults = {
        "DOCUMENTS": "Documents", "PICTURES": "Pictures", "MUSIC": "Music",
        "VIDEOS": "Videos", "DESKTOP": "Desktop", "DOWNLOADS": "Downloads",
    }
    xdg_keys = {
        "DOCUMENTS": "DOCUMENTS", "PICTURES": "PICTURES", "MUSIC": "MUSIC",
        "VIDEOS": "VIDEOS", "DESKTOP": "DESKTOP", "DOWNLOADS": "DOWNLOAD",
    }
    mapping: dict[str, Path] = {"HOME": home, "CONFIG": config, "DATA": data, "ROOT": Path("/")}
    for ph, default in defaults.items():
        mapping[ph] = xdg.get(xdg_keys[ph], home / default)
    return mapping


# ------------------------------------------------------------------- Windows
_KNOWN_FOLDERS = {
    "DOCUMENTS": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "PICTURES": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "MUSIC": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
    "VIDEOS": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
    "DESKTOP": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
    "DOWNLOADS": "{374DE290-123F-4565-9164-39C4925E467B}",
}


def _known_folder(guid: str) -> Path | None:  # pragma: no cover - nur Windows
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8),
        ]

    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(guid), ctypes.byref(g))
    out = ctypes.c_wchar_p()
    try:
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
    except OSError:
        return None
    value = out.value
    ctypes.windll.ole32.CoTaskMemFree(out)
    return Path(value) if value else None


def _windows_mapping() -> dict[str, Path]:  # pragma: no cover - nur Windows
    home = Path(os.environ.get("USERPROFILE") or Path.home())
    mapping: dict[str, Path] = {
        "HOME": home,
        "APPDATA": Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming"),
        "LOCALAPPDATA": Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local"),
        "ROOT": Path(os.environ.get("SystemDrive", "C:") + "\\"),
    }
    defaults = {
        "DOCUMENTS": "Documents", "PICTURES": "Pictures", "MUSIC": "Music",
        "VIDEOS": "Videos", "DESKTOP": "Desktop", "DOWNLOADS": "Downloads",
    }
    for ph, guid in _KNOWN_FOLDERS.items():
        mapping[ph] = _known_folder(guid) or home / defaults[ph]
    return mapping
