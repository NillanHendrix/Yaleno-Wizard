from __future__ import annotations

from .model import Catalog, Category, Item, OSName
from .placeholders import PathMapper, current_os


def catalog_for(os_name: OSName | None = None, plugins: bool | list = True) -> Catalog:
    """Kategorien für ein Betriebssystem.

    ``plugins=True`` baut die aktiven Catalog-Plugins ein, ``False`` nur die eingebauten
    Kategorien, eine Liste genau diese Plugins.
    """
    os_name = os_name or current_os()
    if os_name == "windows":
        from . import windows
        catalog = windows.build()
    else:
        from . import linux
        catalog = linux.build()
    if plugins is False:
        return catalog
    from ..plugins.apply import apply_plugins
    if plugins is True:
        from ..plugins.registry import active_plugins
        try:
            plugins = active_plugins()
        except Exception as exc:  # defekte Plugins dürfen das Programm nie lahmlegen
            catalog.plugin_errors.append(f"Plugins konnten nicht geladen werden: {exc}")
            return catalog
    return apply_plugins(catalog, list(plugins), os_name)


__all__ = ["Catalog", "Category", "Item", "OSName", "PathMapper", "catalog_for", "current_os"]
