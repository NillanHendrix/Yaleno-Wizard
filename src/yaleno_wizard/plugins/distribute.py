"""Plugins über den Speicher auf andere Geräte bringen.

Beim Abgleich legt jedes Gerät seine aktiven Catalog-Plugins unter ``yaleno/plugins/`` ab.
Andere Geräte bieten sie nach dem Verbinden zur Übernahme an – **nie automatisch**, weil
Plugins Befehle enthalten können. Abgelehnte Angebote werden je Version gemerkt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..settings import Profile
from . import manager
from .model import Plugin, PluginChanges, PluginError, newer
from .registry import find


def publish(store, plugin_ids: list[str], profile: Profile | None = None) -> list[str]:
    """Lädt die Plugins hoch, die im Speicher fehlen oder dort älter sind. Gibt deren Namen zurück."""
    remote = set(store.list_plugins())
    out = []
    for pid in plugin_ids:
        lp = find(pid, profile)
        if lp is None or not lp.ok or lp.plugin.is_feature or not lp.plugin.text:  # type: ignore[union-attr]
            continue
        if pid in remote:
            try:
                there = Plugin.from_text(store.get_plugin(pid))
                if not newer(lp.version, there.version):
                    continue
            except (PluginError, OSError, UnicodeDecodeError):
                pass  # defekt im Speicher → überschreiben
        store.put_plugin(pid, lp.plugin.text)  # type: ignore[union-attr]
        out.append(lp.name)
    return out


@dataclass
class Offer:
    pending: manager.PendingInstall
    enable_only: bool = False  # gleiche Version schon vorhanden, nur aktivieren

    @property
    def plugin(self) -> Plugin:
        return self.pending.plugin

    def describe(self) -> str:
        if self.enable_only:
            return f"{self.plugin.name} {self.plugin.version} – hier vorhanden, aber nicht aktiv"
        return f"{self.plugin.name}\n{self.pending.changes.describe()}"


def _declined() -> dict[str, str]:
    return dict(manager._read_state().get("declined", {}))


def offers(store, profile: Profile | None = None) -> list[Offer]:
    """Plugins im Speicher, die hier fehlen, neuer sind oder nicht aktiv sind."""
    profile = profile if profile is not None else Profile.load()
    declined = _declined()
    out = []
    for pid in store.list_plugins():
        try:
            p = Plugin.from_text(store.get_plugin(pid))
        except (PluginError, OSError, UnicodeDecodeError):
            continue
        if p.id != pid or p.is_feature or not p.compatible or declined.get(pid) == p.version:
            continue
        local = find(pid, profile)
        old = local.plugin if local is not None and local.ok else None
        if old is not None and not newer(p.version, old.version):
            if local.enabled:  # type: ignore[union-attr]
                continue
            out.append(Offer(manager.PendingInstall(old, PluginChanges.between(None, old), local), True))
            continue
        out.append(Offer(manager.PendingInstall(p, PluginChanges.between(old, p), local)))
    return out


def accept(offer: Offer, profile: Profile) -> None:
    if offer.enable_only:
        manager.set_enabled(offer.plugin.id, True, profile)
    else:
        manager.install(offer.pending, profile, enable=True)


def decline(offer: Offer) -> None:
    state = manager._read_state()
    state.setdefault("declined", {})[offer.plugin.id] = offer.plugin.version
    manager._write_atomic(manager._state_file(), json.dumps(state, indent=1))
