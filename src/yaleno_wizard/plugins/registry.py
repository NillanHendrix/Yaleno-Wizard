"""Installierte und mitgelieferte Plugins finden und laden.

* Mitgeliefert: ``yaleno_wizard/plugins/builtin/*.yml`` (kommen mit dem Programm, standardmäßig aus).
* Installiert: ``~/.config/yaleno-wizard/plugins/<id>.yml`` (Windows: ``%APPDATA%\\yaleno-wizard\\plugins``).

Gibt es ein Plugin in beiden Orten, gilt das installierte – außer das mitgelieferte ist neuer
(z. B. nach einem Programm-Update). Welche Plugins aktiv sind, steht in der Einstellungsdatei
(``plugins.enabled``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..settings import Profile, config_dir
from .model import Plugin, PluginError, newer

BUILTIN = "builtin"
LOCAL = "local"


def plugins_dir() -> Path:
    return config_dir() / "plugins"


def builtin_dir() -> Path:
    return Path(__file__).resolve().parent / "builtin"


@dataclass
class LoadedPlugin:
    id: str
    origin: str              # builtin | local
    path: Path
    plugin: Plugin | None    # None bei Fehler
    enabled: bool = False
    error: str = ""
    has_builtin: bool = False  # es gibt (auch) eine mitgelieferte Fassung

    @property
    def ok(self) -> bool:
        return self.plugin is not None and not self.error

    @property
    def name(self) -> str:
        return self.plugin.name if self.plugin else self.id

    @property
    def version(self) -> str:
        return self.plugin.version if self.plugin else "?"

    @property
    def removable(self) -> bool:
        return self.origin == LOCAL


def _scan(directory: Path, origin: str) -> dict[str, LoadedPlugin]:
    out: dict[str, LoadedPlugin] = {}
    if not directory.is_dir():
        return out
    for f in sorted(directory.iterdir()):
        if f.suffix.lower() not in (".yml", ".yaml") or not f.is_file():
            continue
        try:
            p = Plugin.read(f)
        except PluginError as exc:
            out.setdefault(f.stem, LoadedPlugin(f.stem, origin, f, None, error=str(exc)))
            continue
        if p.id in out and out[p.id].ok:
            continue  # doppelte ID – erste Datei gewinnt
        out[p.id] = LoadedPlugin(p.id, origin, f, p)
    return out


def discover(profile: Profile | None = None) -> list[LoadedPlugin]:
    """Alle bekannten Plugins (auch fehlerhafte), nach Name sortiert."""
    profile = profile if profile is not None else Profile.load()
    builtin = _scan(builtin_dir(), BUILTIN)
    local = _scan(plugins_dir(), LOCAL)
    merged: dict[str, LoadedPlugin] = dict(builtin)
    for pid, lp in local.items():
        b = builtin.get(pid)
        lp.has_builtin = b is not None
        if b is not None and b.ok and lp.ok and newer(b.version, lp.version):
            b.has_builtin = True
            continue  # mitgelieferte Fassung ist neuer
        merged[pid] = lp
    enabled = set(profile.plugins_enabled)
    for lp in merged.values():
        lp.enabled = lp.id in enabled
        if lp.ok and not lp.plugin.compatible:  # type: ignore[union-attr]
            lp.error = (f"braucht Yaleno Wizard {lp.plugin.min_app_version} oder neuer")  # type: ignore[union-attr]
    return sorted(merged.values(), key=lambda lp: lp.name.lower())


def find(plugin_id: str, profile: Profile | None = None) -> LoadedPlugin | None:
    for lp in discover(profile):
        if lp.id == plugin_id:
            return lp
    return None


def active_plugins(profile: Profile | None = None) -> list[Plugin]:
    """Aktive, fehlerfreie Plugins."""
    return [lp.plugin for lp in discover(profile) if lp.enabled and lp.ok]  # type: ignore[misc]


def feature_enabled(feature: str, profile: Profile | None = None) -> bool:
    return any(p.is_feature and p.feature == feature for p in active_plugins(profile))
