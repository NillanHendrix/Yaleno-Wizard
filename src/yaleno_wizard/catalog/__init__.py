from __future__ import annotations

from .model import Catalog, Category, Item, OSName
from .placeholders import PathMapper, current_os


def catalog_for(os_name: OSName | None = None) -> Catalog:
    """Kategorien für ein Betriebssystem."""
    os_name = os_name or current_os()
    if os_name == "windows":
        from . import windows
        return windows.build()
    from . import linux
    return linux.build()


__all__ = ["Catalog", "Category", "Item", "OSName", "PathMapper", "catalog_for", "current_os"]
