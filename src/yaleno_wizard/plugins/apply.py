"""Catalog-Plugins in den Katalog einbauen."""

from __future__ import annotations

from dataclasses import replace

from ..catalog.model import Catalog, Category, OSName
from .model import Plugin


def apply_plugins(catalog: Catalog, plugins: list[Plugin], os_name: OSName) -> Catalog:
    """Hängt Kategorien/Erweiterungen der Plugins an ``catalog`` an (verändert ihn).

    Ein fehlerhaftes Plugin (z. B. Kategorie-ID schon vergeben) wird komplett übersprungen;
    der Grund landet in ``catalog.plugin_errors``.
    """
    for p in plugins:
        if p.is_feature:
            continue
        cats = list(catalog.categories)
        index = {c.id: i for i, c in enumerate(cats)}
        try:
            for spec in p.categories:
                if spec.id in index:
                    raise ValueError(f"Kategorie „{spec.id}“ gibt es schon")
                cat = spec.to_category(os_name)
                if cat is not None:
                    cat = replace(cat, plugin=p.id)
                    index[cat.id] = len(cats)
                    cats.append(cat)
            for ext in p.extends:
                i = index.get(ext.category)
                if i is None:
                    continue  # Kategorie gibt es auf diesem Betriebssystem nicht
                cats[i] = _extend(cats[i], ext, os_name)
        except ValueError as exc:
            catalog.plugin_errors.append(f"Plugin „{p.name}“: {exc} – übersprungen.")
            continue
        catalog.categories = cats
        catalog.plugins.append(p.id)
    return catalog


def _extend(cat: Category, ext, os_name: OSName) -> Category:
    items = list(cat.items)
    ids = {it.id for it in items}
    for item_id, pats in ext.excludes.items():
        for n, it in enumerate(items):
            if it.id == item_id:
                items[n] = replace(it, excludes=tuple(it.excludes) + tuple(pats))
                break
        else:
            raise ValueError(f"Eintrag „{item_id}“ gibt es in „{cat.id}“ nicht")
    for spec in ext.items:
        if spec.id in ids:
            raise ValueError(f"Eintrag „{spec.id}“ gibt es in „{cat.id}“ schon")
        it = spec.to_item(os_name)
        if it is not None:
            items.append(it)
            ids.add(it.id)
    return replace(cat, items=tuple(items))
