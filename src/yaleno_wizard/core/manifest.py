"""Snapshot-Manifest und Ablagestruktur auf dem Speicher.

Layout:  <basis>/yaleno/<host>/<YYYY-MM-DD_HHMMSS>/manifest.json
                                                 /files/<kategorie>/<PLATZHALTER>/<pfad>
Ein Snapshot ist nur gültig, wenn manifest.json existiert (wird zuletzt geschrieben).
"""

from __future__ import annotations

import json
import posixpath
import re
from dataclasses import dataclass, field
from datetime import datetime

from .. import __version__
from ..storage.base import Storage
from .entry import Entry

FORMAT = "yaleno-snapshot"
FORMAT_VERSION = 1
MANIFEST = "manifest.json"
SNAPSHOT_FMT = "%Y-%m-%d_%H%M%S"
SNAPSHOT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")


def sanitize_host(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return cleaned or "rechner"


def yaleno_root(base: str) -> str:
    base = (base or ".").rstrip("/") or "/"
    return posixpath.join(base, "yaleno")


def snapshot_dir(base: str, host: str, snapshot: str) -> str:
    return posixpath.join(yaleno_root(base), sanitize_host(host), snapshot)


@dataclass
class Manifest:
    host: str
    os: str
    snapshot: str
    created: str
    categories: dict[str, dict] = field(default_factory=dict)
    entries: list[Entry] = field(default_factory=list)
    app_version: str = __version__
    errors: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)

    def to_json(self) -> str:
        return json.dumps({
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": self.app_version,
            "host": self.host,
            "os": self.os,
            "snapshot": self.snapshot,
            "created": self.created,
            "categories": self.categories,
            "errors": self.errors,
            "entries": [e.to_dict() for e in self.entries],
        }, ensure_ascii=False, indent=1)

    @classmethod
    def from_json(cls, text: str) -> "Manifest":
        d = json.loads(text)
        if d.get("format") != FORMAT:
            raise ValueError("Keine Yaleno-Snapshot-Datei.")
        if int(d.get("version", 0)) > FORMAT_VERSION:
            raise ValueError("Snapshot stammt von einer neueren Version des Yaleno Wizard.")
        return cls(
            host=d["host"], os=d["os"], snapshot=d["snapshot"], created=d.get("created", ""),
            categories=d.get("categories", {}),
            entries=[Entry.from_dict(e) for e in d.get("entries", [])],
            app_version=d.get("app_version", ""),
            errors=d.get("errors", []),
        )


@dataclass
class SnapshotInfo:
    host: str
    snapshot: str
    path: str

    @property
    def date(self) -> datetime | None:
        try:
            return datetime.strptime(self.snapshot, SNAPSHOT_FMT)
        except ValueError:
            return None


def list_snapshots(storage: Storage, base: str) -> list[SnapshotInfo]:
    root = yaleno_root(base)
    if not storage.is_dir(root):
        return []
    out: list[SnapshotInfo] = []
    for host in storage.listdir(root):
        host_dir = posixpath.join(root, host)
        if not storage.is_dir(host_dir):
            continue
        for snap in storage.listdir(host_dir):
            if not SNAPSHOT_RE.match(snap):
                continue
            path = posixpath.join(host_dir, snap)
            if storage.exists(posixpath.join(path, MANIFEST)):
                out.append(SnapshotInfo(host=host, snapshot=snap, path=path))
    out.sort(key=lambda s: (s.snapshot, s.host), reverse=True)
    return out


def load_manifest(storage: Storage, snapshot_path: str) -> Manifest:
    return Manifest.from_json(storage.read_bytes(posixpath.join(snapshot_path, MANIFEST)).decode("utf-8"))
