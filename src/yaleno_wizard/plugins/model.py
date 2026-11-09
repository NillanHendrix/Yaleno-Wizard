"""Plugin-Format: YAML-Dateien, die Kategorien hinzufügen oder eingebaute Funktionen freischalten.

Ein Plugin enthält **keinen Programmcode**. Es gibt zwei Arten:

* ``type: catalog`` – neue Kategorien/Einträge (Pfade, Ausschlüsse, Befehle) oder Erweiterungen
  bestehender Kategorien (``extend``).
* ``type: feature`` – schaltet eine eingebaute Funktion frei (``feature: encryption`` …).

Beispiel::

    yaleno_plugin: 1
    id: prismlauncher
    name: Prism Launcher (Minecraft)
    version: 1.0.0
    source: https://example.org/prismlauncher.yml
    type: catalog
    categories:
      - id: games
        name: Spiele
        os: [linux, windows]
        items:
          - id: prism
            label: Prism Launcher
            paths:
              linux: ["{DATA}/PrismLauncher"]
              windows: ["{APPDATA}/PrismLauncher"]
            excludes: [cache, logs]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .. import __version__
from ..catalog.model import Category, Item, OSName
from ..catalog.placeholders import DISPLAY_NAMES, PLACEHOLDER_RE

FORMAT_VERSION = 1
ALL_OS: tuple[OSName, ...] = ("linux", "windows")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
MAX_SIZE = 256 * 1024

# Eingebaute Funktionen, die ein Feature-Plugin freischalten kann.
FEATURES: dict[str, str] = {
    "encryption": "Verschlüsselung des ganzen Speichers",
    "app_lock": "Zugangssperre für die App",
    "fido2": "Security-Key / Passkey (FIDO2)",
    "nextcloud_login_flow": "Nextcloud-Anmeldung im Browser (auch per Passkey)",
    "oidc": "Anmeldung per OpenID Connect (OIDC)",
}


class PluginError(ValueError):
    pass


def parse_version(v: str) -> tuple[int, ...]:
    """``1.2.3`` → (1, 2, 3); nicht-numerische Anhänge (``1.2.0-beta``) werden ignoriert."""
    out = []
    for part in str(v).strip().split("."):
        m = re.match(r"\d+", part)
        if not m:
            break
        out.append(int(m.group()))
    if not out:
        raise PluginError(f"Ungültige Versionsnummer „{v}“ (erwartet z. B. 1.0.0).")
    while len(out) > 1 and out[-1] == 0:
        out.pop()
    return tuple(out)


def newer(a: str, b: str) -> bool:
    """Ist Version ``a`` neuer als ``b``?"""
    return parse_version(a) > parse_version(b)


# ---------------------------------------------------------------------- Hilfen
def _str(d: dict, key: str, where: str, required: bool = False, default: str = "") -> str:
    v = d.get(key)
    if v is None:
        if required:
            raise PluginError(f"{where}: „{key}“ fehlt.")
        return default
    if not isinstance(v, (str, int, float)):
        raise PluginError(f"{where}: „{key}“ muss ein Text sein.")
    return str(v)


def _bool(d: dict, key: str, where: str, default: bool) -> bool:
    v = d.get(key, default)
    if not isinstance(v, bool):
        raise PluginError(f"{where}: „{key}“ muss true oder false sein.")
    return v


def _id(d: dict, key: str, where: str) -> str:
    v = _str(d, key, where, required=True)
    if not ID_RE.match(v):
        raise PluginError(f"{where}: „{key}: {v}“ – erlaubt sind Kleinbuchstaben, Ziffern, '.', '-', '_'.")
    return v


def _str_list(v, where: str) -> tuple[str, ...]:
    if v is None:
        return ()
    if isinstance(v, str):
        return (v,)
    if not isinstance(v, list) or not all(isinstance(x, (str, int, float)) for x in v):
        raise PluginError(f"{where} muss eine Liste von Texten sein.")
    return tuple(str(x) for x in v)


def _os_list(v, where: str) -> tuple[OSName, ...]:
    if v is None:
        return ALL_OS
    items = _str_list(v, where)
    for o in items:
        if o not in ALL_OS:
            raise PluginError(f"{where}: unbekanntes Betriebssystem „{o}“ (erlaubt: linux, windows).")
    return items  # type: ignore[return-value]


def _per_os(v, where: str) -> dict[str, tuple[str, ...]]:
    """Liste (für alle OS) oder ``{linux: [...], windows: [...]}``."""
    if v is None:
        return {}
    if isinstance(v, dict):
        out = {}
        for k, val in v.items():
            if k not in ALL_OS:
                raise PluginError(f"{where}: unbekanntes Betriebssystem „{k}“ (erlaubt: linux, windows).")
            out[k] = _str_list(val, f"{where}.{k}")
        return out
    lst = _str_list(v, where)
    return {o: lst for o in ALL_OS}


def _check_path(p: str, where: str) -> None:
    m = PLACEHOLDER_RE.match(p)
    if not m:
        raise PluginError(f"{where}: Pfad „{p}“ muss mit einem Platzhalter wie {{HOME}} oder {{CONFIG}} beginnen.")
    if m.group(1) not in DISPLAY_NAMES:
        raise PluginError(f"{where}: unbekannter Platzhalter {{{m.group(1)}}} "
                          f"(erlaubt: {', '.join('{' + k + '}' for k in DISPLAY_NAMES)}).")
    if ".." in (m.group(2) or "").split("/"):
        raise PluginError(f"{where}: „..“ ist in Pfaden nicht erlaubt.")


# ---------------------------------------------------------------------- Einträge
@dataclass(frozen=True)
class ItemSpec:
    id: str
    label: str
    kind: str = "path"
    os: tuple[OSName, ...] = ALL_OS
    paths: dict[str, tuple[str, ...]] = field(default_factory=dict)
    excludes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    backup_cmd: dict[str, tuple[str, ...]] = field(default_factory=dict)
    restore_cmd: dict[str, tuple[str, ...]] = field(default_factory=dict)
    output_ext: str = "txt"

    @classmethod
    def parse(cls, d, where: str) -> "ItemSpec":
        if not isinstance(d, dict):
            raise PluginError(f"{where} muss ein Abschnitt sein.")
        iid = _id(d, "id", where)
        where = f"{where} „{iid}“"
        kind = _str(d, "kind", where, default="path")
        if kind not in ("path", "command"):
            raise PluginError(f"{where}: kind muss path oder command sein.")
        paths = _per_os(d.get("paths"), f"{where}.paths")
        for lst in paths.values():
            for p in lst:
                _check_path(p, where)
        backup = _per_os(d.get("backup_cmd"), f"{where}.backup_cmd")
        restore = _per_os(d.get("restore_cmd"), f"{where}.restore_cmd")
        if kind == "path" and not any(paths.values()):
            raise PluginError(f"{where}: „paths“ fehlt.")
        if kind == "command" and not any(backup.values()):
            raise PluginError(f"{where}: „backup_cmd“ fehlt.")
        if kind == "path" and (backup or restore):
            raise PluginError(f"{where}: Befehle sind nur bei kind: command erlaubt.")
        ext = _str(d, "output_ext", where, default="txt")
        if not re.fullmatch(r"[A-Za-z0-9]{1,8}", ext):
            raise PluginError(f"{where}: output_ext „{ext}“ ist ungültig.")
        return cls(
            id=iid, label=_str(d, "label", where, required=True), kind=kind,
            os=_os_list(d.get("os"), f"{where}.os"), paths=paths,
            excludes=_per_os(d.get("excludes"), f"{where}.excludes"),
            backup_cmd=backup, restore_cmd=restore, output_ext=ext,
        )

    def to_item(self, os_name: OSName) -> Item | None:
        if os_name not in self.os:
            return None
        if self.kind == "command":
            cmd = self.backup_cmd.get(os_name)
            if not cmd:
                return None
            return Item(self.id, self.label, kind="command", backup_cmd=cmd,
                        restore_cmd=self.restore_cmd.get(os_name, ()), output_ext=self.output_ext)
        paths = self.paths.get(os_name)
        if not paths:
            return None
        return Item(self.id, self.label, paths=paths, excludes=self.excludes.get(os_name, ()))

    def commands(self) -> list[str]:
        out = []
        for o, cmd in self.backup_cmd.items():
            out.append(f"[{o}] sichern: {' '.join(cmd)}")
        for o, cmd in self.restore_cmd.items():
            out.append(f"[{o}] einspielen: {' '.join(cmd)}")
        return out


@dataclass(frozen=True)
class CategorySpec:
    id: str
    name: str
    description: str
    os: tuple[OSName, ...]
    items: tuple[ItemSpec, ...]
    cross_os: bool = False
    sensitive: bool = False
    requires_admin: bool = False
    default_selected: bool = True
    claim_priority: int = 50

    @classmethod
    def parse(cls, d, where: str) -> "CategorySpec":
        if not isinstance(d, dict):
            raise PluginError(f"{where} muss ein Abschnitt sein.")
        cid = _id(d, "id", where)
        where = f"Kategorie „{cid}“"
        raw_items = d.get("items")
        if not isinstance(raw_items, list) or not raw_items:
            raise PluginError(f"{where}: „items“ muss eine nicht-leere Liste sein.")
        items = tuple(ItemSpec.parse(x, f"{where}, Eintrag") for x in raw_items)
        _no_dupes([i.id for i in items], f"{where}: Eintrag")
        try:
            prio = int(d.get("claim_priority", 50))
        except (TypeError, ValueError) as exc:
            raise PluginError(f"{where}: claim_priority muss eine Zahl sein.") from exc
        return cls(
            id=cid, name=_str(d, "name", where, required=True),
            description=_str(d, "description", where), os=_os_list(d.get("os"), f"{where}.os"),
            items=items, cross_os=_bool(d, "cross_os", where, False),
            sensitive=_bool(d, "sensitive", where, False),
            requires_admin=_bool(d, "requires_admin", where, False),
            default_selected=_bool(d, "default_selected", where, True), claim_priority=prio,
        )

    def to_category(self, os_name: OSName) -> Category | None:
        if os_name not in self.os:
            return None
        items = tuple(i for i in (s.to_item(os_name) for s in self.items) if i is not None)
        if not items:
            return None
        return Category(
            id=self.id, name=self.name, description=self.description, os=os_name, items=items,
            cross_os=self.cross_os, sensitive=self.sensitive, requires_admin=self.requires_admin,
            claim_priority=self.claim_priority, default_selected=self.default_selected,
        )


@dataclass(frozen=True)
class Extension:
    """Erweiterung einer bestehenden Kategorie (``extend: {dev: {...}}``)."""

    category: str
    items: tuple[ItemSpec, ...] = ()
    excludes: dict[str, tuple[str, ...]] = field(default_factory=dict)  # Item-ID -> Muster

    @classmethod
    def parse(cls, cat_id: str, d, where: str) -> "Extension":
        if not isinstance(d, dict):
            raise PluginError(f"{where} muss ein Abschnitt sein.")
        items = tuple(ItemSpec.parse(x, f"{where}, Eintrag") for x in (d.get("items") or []))
        excl_raw = d.get("excludes") or {}
        if not isinstance(excl_raw, dict):
            raise PluginError(f"{where}.excludes muss ein Abschnitt je Eintrag sein.")
        excludes = {str(k): _str_list(v, f"{where}.excludes.{k}") for k, v in excl_raw.items()}
        if not items and not excludes:
            raise PluginError(f"{where}: weder „items“ noch „excludes“ angegeben.")
        return cls(category=cat_id, items=items, excludes=excludes)


def _no_dupes(ids: list[str], what: str) -> None:
    seen = set()
    for i in ids:
        if i in seen:
            raise PluginError(f"{what} „{i}“ ist doppelt.")
        seen.add(i)


# ---------------------------------------------------------------------- Plugin
@dataclass(frozen=True)
class Plugin:
    id: str
    name: str
    version: str
    type: str
    description: str = ""
    author: str = ""
    source: str = ""
    homepage: str = ""
    min_app_version: str = ""
    feature: str = ""
    categories: tuple[CategorySpec, ...] = ()
    extends: tuple[Extension, ...] = ()
    text: str = field(default="", compare=False, repr=False)  # Originaltext (zum Speichern/Verteilen)

    @property
    def is_feature(self) -> bool:
        return self.type == "feature"

    @property
    def compatible(self) -> bool:
        return not self.min_app_version or not newer(self.min_app_version, __version__)

    def all_items(self) -> list[ItemSpec]:
        out = [i for c in self.categories for i in c.items]
        out += [i for e in self.extends for i in e.items]
        return out

    def commands(self) -> list[str]:
        return [c for i in self.all_items() for c in i.commands()]

    def paths(self) -> list[str]:
        out = []
        for i in self.all_items():
            for o, lst in i.paths.items():
                out += [f"[{o}] {p}" for p in lst]
        return sorted(set(out))

    def summary(self) -> str:
        if self.is_feature:
            return FEATURES.get(self.feature, self.feature)
        parts = [f"Kategorie „{c.name}“" for c in self.categories]
        parts += [f"erweitert „{e.category}“" for e in self.extends]
        return ", ".join(parts)

    # ------------------------------------------------------------------ Laden
    @classmethod
    def from_dict(cls, d, text: str = "") -> "Plugin":
        if not isinstance(d, dict) or "yaleno_plugin" not in d:
            raise PluginError("Die Datei ist kein Yaleno-Plugin (Schlüssel „yaleno_plugin“ fehlt).")
        try:
            fmt = int(d["yaleno_plugin"])
        except (TypeError, ValueError) as exc:
            raise PluginError("„yaleno_plugin“ muss eine Zahl sein.") from exc
        if fmt > FORMAT_VERSION:
            raise PluginError("Das Plugin braucht eine neuere Version des Yaleno Wizard.")
        pid = _id(d, "id", "Plugin")
        where = f"Plugin „{pid}“"
        version = _str(d, "version", where, required=True)
        parse_version(version)
        typ = _str(d, "type", where, default="catalog")
        if typ not in ("catalog", "feature"):
            raise PluginError(f"{where}: type muss catalog oder feature sein.")
        source = _str(d, "source", where)
        if source and not source.startswith("https://"):
            raise PluginError(f"{where}: source muss eine https://-Adresse sein.")
        min_app = _str(d, "min_app_version", where)
        if min_app:
            parse_version(min_app)
        feature = ""
        cats: tuple[CategorySpec, ...] = ()
        exts: tuple[Extension, ...] = ()
        if typ == "feature":
            feature = _str(d, "feature", where, required=True)
            if feature not in FEATURES:
                raise PluginError(f"{where}: unbekannte Funktion „{feature}“ "
                                  f"(verfügbar: {', '.join(FEATURES)}).")
            if d.get("categories") or d.get("extend"):
                raise PluginError(f"{where}: Feature-Plugins dürfen keine Kategorien enthalten.")
        else:
            raw_cats = d.get("categories") or []
            if not isinstance(raw_cats, list):
                raise PluginError(f"{where}: „categories“ muss eine Liste sein.")
            cats = tuple(CategorySpec.parse(c, f"{where}, Kategorie") for c in raw_cats)
            _no_dupes([c.id for c in cats], f"{where}: Kategorie")
            raw_ext = d.get("extend") or {}
            if not isinstance(raw_ext, dict):
                raise PluginError(f"{where}: „extend“ muss ein Abschnitt je Kategorie sein.")
            exts = tuple(Extension.parse(str(k), v, f"{where}, extend.{k}") for k, v in raw_ext.items())
            if not cats and not exts:
                raise PluginError(f"{where}: enthält weder „categories“ noch „extend“.")
        return cls(
            id=pid, name=_str(d, "name", where, required=True), version=version, type=typ,
            description=_str(d, "description", where), author=_str(d, "author", where),
            source=source, homepage=_str(d, "homepage", where), min_app_version=min_app,
            feature=feature, categories=cats, extends=exts, text=text,
        )

    @classmethod
    def from_text(cls, text: str) -> "Plugin":
        if len(text.encode("utf-8")) > MAX_SIZE:
            raise PluginError("Die Plugin-Datei ist zu groß (höchstens 256 KB).")
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise PluginError(f"Ungültiges YAML: {exc}") from exc
        return cls.from_dict(data, text)

    @classmethod
    def read(cls, path: Path) -> "Plugin":
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise PluginError(f"Datei kann nicht gelesen werden: {exc}") from exc
        return cls.from_text(text)


# ---------------------------------------------------------------------- Änderungen
@dataclass
class PluginChanges:
    """Was sich bei Installation/Update ändert – wird vor dem Bestätigen angezeigt."""

    old_version: str | None
    new_version: str
    added_paths: list[str] = field(default_factory=list)
    removed_paths: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)       # alle Befehle des neuen Stands
    new_commands: list[str] = field(default_factory=list)   # davon neu hinzugekommen

    @classmethod
    def between(cls, old: Plugin | None, new: Plugin) -> "PluginChanges":
        old_paths = set(old.paths()) if old else set()
        new_paths = set(new.paths())
        old_cmds = set(old.commands()) if old else set()
        cmds = new.commands()
        return cls(
            old_version=old.version if old else None, new_version=new.version,
            added_paths=sorted(new_paths - old_paths), removed_paths=sorted(old_paths - new_paths),
            commands=cmds, new_commands=[c for c in cmds if c not in old_cmds],
        )

    def describe(self) -> str:
        lines = []
        if self.old_version:
            lines.append(f"Version {self.old_version} → {self.new_version}")
        else:
            lines.append(f"Version {self.new_version} (neu)")
        if self.added_paths:
            lines.append("Neue Pfade:")
            lines += [f"  + {p}" for p in self.added_paths]
        if self.removed_paths:
            lines.append("Entfallene Pfade:")
            lines += [f"  − {p}" for p in self.removed_paths]
        if self.new_commands:
            lines.append("⚠ Neue Befehle, die beim Abgleich ausgeführt werden:")
            lines += [f"  ! {c}" for c in self.new_commands]
        return "\n".join(lines)
