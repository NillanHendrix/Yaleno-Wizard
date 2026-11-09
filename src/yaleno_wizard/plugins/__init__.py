"""Plugins: YAML-Dateien, die Kategorien hinzufügen oder eingebaute Funktionen freischalten.

Format: ``plugins/model.py``, Ablage und Laden: ``registry.py``, Verwaltung: ``manager.py``.
"""

from __future__ import annotations

from .model import FEATURES, Plugin, PluginChanges, PluginError
from .registry import LoadedPlugin, active_plugins, discover, feature_enabled, find, plugins_dir

__all__ = [
    "FEATURES", "LoadedPlugin", "Plugin", "PluginChanges", "PluginError", "active_plugins", "discover",
    "feature_enabled", "find", "plugins_dir",
]
