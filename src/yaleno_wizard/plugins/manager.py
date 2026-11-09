"""Plugin-Manager ohne Oberfläche: installieren, entfernen, (de)aktivieren, Updates.

Wird vom Wizard-Dialog, der Kommandozeile (``yaleno-wizard plugin …``) und dem
Hintergrund-Abgleich gemeinsam benutzt. Änderungen am Zustand landen im übergebenen
``Profile`` und werden sofort gespeichert.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .. import __version__
from ..settings import Profile
from .model import MAX_SIZE, Plugin, PluginChanges, PluginError, newer
from .registry import BUILTIN, LoadedPlugin, discover, find, plugins_dir

TIMEOUT = 20
CHECK_EVERY = timedelta(hours=24)


# ---------------------------------------------------------------------- Laden aus Datei/URL
def is_url(source: str) -> bool:
    return str(source).startswith(("https://", "http://"))


def fetch_text(url: str) -> str:
    """Lädt eine Plugin-Datei (nur https, höchstens 256 KB)."""
    if not url.startswith("https://"):
        raise PluginError("Plugins werden nur über https:// geladen.")
    import requests
    try:
        with requests.get(url, timeout=TIMEOUT, stream=True,
                          headers={"User-Agent": f"yaleno-wizard/{__version__}"}) as resp:
            if resp.status_code != 200:
                raise PluginError(f"{url}: Server antwortet mit {resp.status_code}.")
            data = b""
            for chunk in resp.iter_content(16384):
                data += chunk
                if len(data) > MAX_SIZE:
                    raise PluginError("Die Plugin-Datei ist zu groß (höchstens 256 KB).")
    except requests.RequestException as exc:
        raise PluginError(f"{url} konnte nicht geladen werden: {exc}") from exc
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PluginError("Die Plugin-Datei ist kein UTF-8-Text.") from exc


def load_source(source: str | Path) -> Plugin:
    if is_url(str(source)):
        return Plugin.from_text(fetch_text(str(source)))
    return Plugin.read(Path(source).expanduser())


# ---------------------------------------------------------------------- Installieren
@dataclass
class PendingInstall:
    """Geprüftes, noch nicht installiertes Plugin – zum Anzeigen und Bestätigen."""

    plugin: Plugin
    changes: PluginChanges
    existing: LoadedPlugin | None = None

    @property
    def is_update(self) -> bool:
        return self.existing is not None and self.existing.plugin is not None

    @property
    def is_downgrade(self) -> bool:
        return self.is_update and newer(self.existing.version, self.plugin.version)  # type: ignore[union-attr]


def prepare(plugin: Plugin, profile: Profile | None = None) -> PendingInstall:
    if not plugin.compatible:
        raise PluginError(f"„{plugin.name}“ braucht Yaleno Wizard {plugin.min_app_version} oder neuer "
                          f"(installiert: {__version__}).")
    existing = find(plugin.id, profile)
    old = existing.plugin if existing and existing.ok else None
    return PendingInstall(plugin, PluginChanges.between(old, plugin), existing)


def prepare_source(source: str | Path, profile: Profile | None = None) -> PendingInstall:
    return prepare(load_source(source), profile)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def install(pending: PendingInstall, profile: Profile, enable: bool = True) -> Path:
    """Schreibt das Plugin nach ``plugins_dir()`` und aktiviert es (Profil wird gespeichert)."""
    p = pending.plugin
    target = plugins_dir() / f"{p.id}.yml"
    text = p.text or ""
    if not text:
        raise PluginError("Plugin ohne Inhalt.")
    _write_atomic(target, text)
    if enable and p.id not in profile.plugins_enabled:
        profile.plugins_enabled.append(p.id)
    profile.save()
    return target


def remove(plugin_id: str, profile: Profile) -> None:
    """Entfernt ein installiertes Plugin. Mitgelieferte lassen sich nur deaktivieren."""
    lp = find(plugin_id, profile)
    local = plugins_dir() / f"{plugin_id}.yml"
    if lp is None and not local.exists():
        raise PluginError(f"Plugin „{plugin_id}“ ist nicht installiert.")
    if lp is not None and lp.origin == BUILTIN and not local.exists():
        raise PluginError(f"„{lp.name}“ gehört zum Programm und kann nur deaktiviert werden.")
    removed = False
    for f in plugins_dir().glob("*.y*ml"):
        try:
            same = Plugin.read(f).id == plugin_id
        except PluginError:
            same = f.stem == plugin_id
        if same:
            f.unlink()
            removed = True
    if not removed and local.exists():
        local.unlink()
    still = find(plugin_id, profile)  # mitgelieferte Fassung bleibt ggf. übrig
    if still is None:
        set_enabled(plugin_id, False, profile)


def set_enabled(plugin_id: str, on: bool, profile: Profile) -> None:
    if on:
        lp = find(plugin_id, profile)
        if lp is None:
            raise PluginError(f"Plugin „{plugin_id}“ ist nicht installiert.")
        if not lp.ok:
            raise PluginError(f"„{lp.name}“ kann nicht aktiviert werden: {lp.error}")
        if plugin_id not in profile.plugins_enabled:
            profile.plugins_enabled.append(plugin_id)
    else:
        profile.plugins_enabled = [x for x in profile.plugins_enabled if x != plugin_id]
    profile.save()


# ---------------------------------------------------------------------- Updates
@dataclass
class UpdateInfo:
    current: LoadedPlugin
    pending: PendingInstall

    @property
    def id(self) -> str:
        return self.current.id


@dataclass
class UpdateCheck:
    updates: list[UpdateInfo] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    checked: int = 0


def _state_file() -> Path:
    return plugins_dir() / "state.json"


def _read_state() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def last_check() -> datetime | None:
    try:
        return datetime.fromisoformat(_read_state().get("last_check", ""))
    except ValueError:
        return None


def update_due(profile: Profile, now: datetime | None = None) -> bool:
    if not profile.plugins_check_updates:
        return False
    last = last_check()
    return last is None or (now or datetime.now()) - last >= CHECK_EVERY


def check_updates(profile: Profile | None = None, plugin_ids: list[str] | None = None,
                  fetch=None) -> UpdateCheck:
    """Lädt die ``source`` jedes Plugins und vergleicht die Versionen."""
    fetch = fetch or fetch_text
    out = UpdateCheck()
    for lp in discover(profile):
        if plugin_ids is not None and lp.id not in plugin_ids:
            continue
        if not lp.plugin or not lp.plugin.source:
            continue
        out.checked += 1
        try:
            new = Plugin.from_text(fetch(lp.plugin.source))
        except PluginError as exc:
            out.errors.append(f"{lp.name}: {exc}")
            continue
        if new.id != lp.id:
            out.errors.append(f"{lp.name}: Quelle liefert ein anderes Plugin („{new.id}“).")
            continue
        if not newer(new.version, lp.version):
            continue
        if not new.compatible:
            out.errors.append(f"{lp.name}: Version {new.version} braucht Yaleno Wizard {new.min_app_version}.")
            continue
        out.updates.append(UpdateInfo(lp, PendingInstall(new, PluginChanges.between(lp.plugin, new), lp)))
    if plugin_ids is None:
        state = _read_state()
        state["last_check"] = datetime.now().isoformat(timespec="seconds")
        state["available"] = [u.id for u in out.updates]
        try:
            _write_atomic(_state_file(), json.dumps(state, indent=1))
        except OSError:
            pass
    return out


def known_updates() -> list[str]:
    """IDs mit verfügbarem Update laut letzter Prüfung."""
    return list(_read_state().get("available", []))


def apply_update(info: UpdateInfo, profile: Profile) -> Path:
    enabled = info.current.enabled
    path = install(info.pending, profile, enable=enabled)
    state = _read_state()
    state["available"] = [x for x in state.get("available", []) if x != info.id]
    try:
        _write_atomic(_state_file(), json.dumps(state, indent=1))
    except OSError:
        pass
    return path
