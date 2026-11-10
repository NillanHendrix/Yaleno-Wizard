"""Zentraler Speicher: ein gemeinsamer Datenbestand mit linearem Versionsverlauf.

Layout auf dem Speicher::

    <basis>/yaleno/
        store.json                         Kennung des Speichers
        HEAD                               Nummer der aktuellen Version
        lock                               Sperre während eines Abgleichs
        objects/<ab>/<sha256>              Dateiinhalte (inhaltsadressiert, dedupliziert)
        revisions/00000042.json.gz         vollständiger Dateibaum der Version 42
        revisions/00000042.info.json       Kurzinfo (Datum, Gerät, Änderungen)

Verschlüsselter Speicher (``store.json`` Version 2 mit Abschnitt ``encryption``, siehe
``core/crypto.py``): Inhalte liegen dann unter ``eobjects/`` (Name = HMAC der Prüfsumme),
Versionen unter ``erevisions/`` – alles AES-256-GCM.
Lesbar bleiben nur ``store.json`` (Schlüsselplätze), ``HEAD`` und ``lock``.

Jede Version beschreibt den *gesamten* Bestand. Die Versionen dienen nur dazu,
zwischen Ständen vor- und zurückzuspringen; ein Inhalt wird nur einmal gespeichert,
egal in wie vielen Versionen er vorkommt.

Jeder Eintrag gehört zu einem *Bereich* (scope):

* ``all``         – auf allen Geräten gleich (persönliche Dateien, auch OS-übergreifend)
* ``os:<os>``     – auf allen Geräten mit diesem Betriebssystem (Shell, Git, Desktop …)
* ``host:<name>`` – nur dieses Gerät (Befehlsausgaben, Systemdateien); wird nur
                    hochgeladen, nie automatisch auf ein Gerät geschrieben.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import posixpath
import re
import socket
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import BinaryIO, Callable, Iterator

from .. import __version__
from ..catalog.model import Category
from ..storage.base import CHUNK, ProgressCallback, Storage, StorageError
from .crypto import CryptoError, EncryptionInfo, StoreKeys, spooled
from .entry import Entry

FORMAT = "yaleno-store"
FORMAT_VERSION = 1            # Versionen und unverschlüsselte Speicher
FORMAT_VERSION_ENCRYPTED = 2  # store.json eines verschlüsselten Speichers
SCOPE_ALL = "all"
LOCK_STALE = timedelta(minutes=30)
LOCK_REFRESH = timedelta(minutes=5)

TreeKey = tuple[str, str]  # (scope, logical)


class StoreLocked(StorageError):
    pass


class StoreEncrypted(StorageError):
    """Der Speicher ist verschlüsselt und (noch) nicht entsperrt."""

    def __init__(self, msg: str = "Der Speicher ist verschlüsselt – bitte zuerst entsperren."):
        super().__init__(msg)


def sanitize_host(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-.")
    return cleaned or "rechner"


def yaleno_root(base: str) -> str:
    base = (base or ".").rstrip("/") or "/"
    return posixpath.join(base, "yaleno")


# ---------------------------------------------------------------------- Bereiche
def os_scope(os_name: str) -> str:
    return f"os:{os_name}"


def host_scope(host: str) -> str:
    return f"host:{sanitize_host(host)}"


def device_scopes(os_name: str, host: str) -> set[str]:
    return {SCOPE_ALL, os_scope(os_name), host_scope(host)}


def scope_for(entry: Entry, category: Category | dict | None, os_name: str, host: str) -> str:
    meta = category.meta() if isinstance(category, Category) else (category or {})
    if entry.is_command or meta.get("requires_admin"):
        return host_scope(host)
    if meta.get("cross_os"):
        return SCOPE_ALL
    return os_scope(os_name)


def is_push_only(scope: str) -> bool:
    """Gerätebezogene Daten werden gesichert, aber nie automatisch zurückgeschrieben."""
    return scope.startswith("host:")


def tree_key(e: Entry) -> TreeKey:
    return (e.scope, e.logical)


# ---------------------------------------------------------------------- Versionen
@dataclass
class RevisionInfo:
    number: int
    created: str
    host: str
    os: str
    message: str
    files: int = 0
    size: int = 0
    added: int = 0
    changed: int = 0
    deleted: int = 0

    @property
    def date(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.created)
        except ValueError:
            return None

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "RevisionInfo":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Revision:
    info: RevisionInfo
    parent: int = 0
    entries: list[Entry] = field(default_factory=list)
    categories: dict[str, dict] = field(default_factory=dict)
    devices: dict[str, str] = field(default_factory=dict)  # Gerätename -> OS
    app_version: str = __version__

    @property
    def number(self) -> int:
        return self.info.number

    @property
    def total_size(self) -> int:
        return sum(e.size for e in self.entries)

    def tree(self) -> dict[TreeKey, Entry]:
        return {tree_key(e): e for e in self.entries}

    def entry_os(self, e: Entry) -> str | None:
        """Betriebssystem, auf dem ein Eintrag gilt (None = überall)."""
        if e.scope.startswith("os:"):
            return e.scope[3:]
        if e.scope.startswith("host:"):
            return self.devices.get(e.scope[5:])
        return None

    def entries_for_device(self, os_name: str, host: str) -> list[Entry]:
        scopes = device_scopes(os_name, host)
        return [e for e in self.entries if e.scope in scopes]

    def to_json(self) -> str:
        return json.dumps({
            "format": FORMAT,
            "version": FORMAT_VERSION,
            "app_version": self.app_version,
            "info": self.info.to_dict(),
            "parent": self.parent,
            "categories": self.categories,
            "devices": self.devices,
            "entries": [e.to_dict() for e in self.entries],
        }, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, text: str) -> "Revision":
        d = json.loads(text)
        if d.get("format") != FORMAT:
            raise ValueError("Keine Yaleno-Version.")
        if int(d.get("version", 0)) > FORMAT_VERSION:
            raise ValueError("Diese Version stammt von einem neueren Yaleno Wizard.")
        return cls(
            info=RevisionInfo.from_dict(d["info"]),
            parent=int(d.get("parent", 0)),
            entries=[Entry.from_dict(e) for e in d.get("entries", [])],
            categories=d.get("categories", {}),
            devices=d.get("devices", {}),
            app_version=d.get("app_version", ""),
        )


def diff_trees(old: dict[TreeKey, Entry], new: dict[TreeKey, Entry]) -> tuple[int, int, int]:
    added = sum(1 for k in new if k not in old)
    deleted = sum(1 for k in old if k not in new)
    changed = sum(1 for k, e in new.items() if k in old and old[k].sha256 != e.sha256)
    return added, changed, deleted


# ---------------------------------------------------------------------- Speicher
class Store:
    def __init__(self, storage: Storage, base: str):
        self.storage = storage
        self.base = base
        self.root = yaleno_root(base)
        self._meta: dict | None = None
        self.keys: StoreKeys | None = None
        self._lock_token: str | None = None
        self._lock_time: datetime | None = None

    # ------------------------------------------------------------ Pfade
    def _p(self, *parts: str) -> str:
        return posixpath.join(self.root, *parts)

    def object_path(self, sha: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"Ungültige Prüfsumme: {sha!r}")
        if self.encrypted:
            name = self._need_keys().object_name(sha)
            return self._p("eobjects", name[:2], name)
        return self._p("objects", sha[:2], sha)

    def _rev_dir(self) -> str:
        return self._p("erevisions" if self.encrypted else "revisions")

    def _rev_path(self, n: int, suffix: str) -> str:
        return posixpath.join(self._rev_dir(), f"{n:08d}{suffix}")

    # ------------------------------------------------------------ Kennung / HEAD
    @property
    def initialized(self) -> bool:
        return self.storage.exists(self._p("store.json"))

    def meta(self) -> dict:
        """Inhalt von ``store.json`` (zwischengespeichert)."""
        if self._meta is None:
            d = json.loads(self.storage.read_bytes(self._p("store.json")).decode("utf-8"))
            if d.get("format") != FORMAT:
                raise StorageError("store.json gehört nicht zu einem Yaleno-Speicher.")
            if int(d.get("version", 0)) > FORMAT_VERSION_ENCRYPTED:
                raise StorageError("Der Speicher wurde mit einer neueren Version des Yaleno Wizard angelegt.")
            self._meta = d
        return self._meta

    @property
    def id(self) -> str:
        return str(self.meta()["id"])

    # ------------------------------------------------------------ Verschlüsselung
    @property
    def encrypted(self) -> bool:
        if self._meta is None and not self.initialized:
            return False
        return "encryption" in self.meta()

    @property
    def encryption(self) -> EncryptionInfo | None:
        if not self.encrypted:
            return None
        try:
            return EncryptionInfo.from_dict(self.meta()["encryption"])
        except (CryptoError, KeyError, TypeError) as exc:
            raise StorageError(f"Verschlüsselungsangaben im Speicher sind ungültig: {exc}") from exc

    @property
    def unlocked(self) -> bool:
        return not self.encrypted or self.keys is not None

    def _need_keys(self) -> StoreKeys:
        if self.keys is None:
            raise StoreEncrypted()
        return self.keys

    def unlock(self, keys_or_master: StoreKeys | bytes) -> StoreKeys:
        """Entsperrt mit dem Hauptschlüssel; ``WrongKey``, wenn er nicht passt."""
        info = self.encryption
        if info is None:
            raise StorageError("Der Speicher ist nicht verschlüsselt.")
        master = keys_or_master.master if isinstance(keys_or_master, StoreKeys) else keys_or_master
        self.keys = info.verify(master)
        return self.keys

    def unlock_password(self, password: str) -> StoreKeys:
        info = self.encryption
        if info is None:
            raise StorageError("Der Speicher ist nicht verschlüsselt.")
        self.keys = info.unlock_password(password)
        return self.keys

    def unlock_recovery(self, code: str) -> StoreKeys:
        info = self.encryption
        if info is None:
            raise StorageError("Der Speicher ist nicht verschlüsselt.")
        self.keys = info.unlock_recovery(code)
        return self.keys

    def save_encryption(self, info: EncryptionInfo) -> None:
        """Schreibt geänderte Schlüsselplätze (Aufrufer muss die Sperre halten)."""
        self._need_keys()
        if not info.slots:
            raise StorageError("Mindestens ein Schlüsselplatz muss bleiben.")
        meta = dict(self.meta())
        meta["encryption"] = info.to_dict()
        self.storage.write_bytes_atomic(self._p("store.json"), json.dumps(meta, indent=1).encode())
        self._meta = meta

    def _seal(self, data: bytes, context: str) -> bytes:
        return self._need_keys().encrypt_bytes(data, context.encode()) if self.encrypted else data

    def _open(self, data: bytes, context: str) -> bytes:
        if not self.encrypted:
            return data
        try:
            return self._need_keys().decrypt_bytes(data, context.encode())
        except CryptoError as exc:
            raise StorageError(f"{context}: {exc}") from exc

    def ensure_initialized(self) -> str:
        if not self.initialized:
            self.storage.makedirs(self.root)
            data = {"format": FORMAT, "version": FORMAT_VERSION, "id": uuid.uuid4().hex,
                    "created": datetime.now().isoformat(timespec="seconds")}
            self.storage.write_bytes_atomic(self._p("store.json"), json.dumps(data, indent=1).encode())
            self._meta = None
        return self.id

    def head(self) -> int:
        path = self._p("HEAD")
        if not self.storage.exists(path):
            return 0
        return int(self.storage.read_bytes(path).decode().strip() or 0)

    # ------------------------------------------------------------ Versionen lesen
    def load_revision(self, n: int) -> Revision:
        raw = self._open(self.storage.read_bytes(self._rev_path(n, ".json.gz")), f"rev:{n}")
        return Revision.from_json(gzip.decompress(raw).decode("utf-8"))

    def load_head(self) -> Revision | None:
        n = self.head()
        return self.load_revision(n) if n else None

    def list_revisions(self) -> list[RevisionInfo]:
        """Alle Versionen, neueste zuerst."""
        d = self._rev_dir()
        if not self.storage.is_dir(d):
            return []
        head = self.head()
        out: list[RevisionInfo] = []
        for name in self.storage.listdir(d):
            m = re.fullmatch(r"(\d{8})\.info\.json", name)
            if not m or int(m.group(1)) > head:
                continue  # Versionen hinter HEAD sind unvollständige Schreibversuche
            try:
                raw = self._open(self.storage.read_bytes(posixpath.join(d, name)), f"info:{int(m.group(1))}")
                out.append(RevisionInfo.from_dict(json.loads(raw)))
            except StoreEncrypted:
                raise
            except (ValueError, KeyError, OSError, StorageError):
                continue
        out.sort(key=lambda r: r.number, reverse=True)
        return out

    # ------------------------------------------------------------ Objekte
    def has_object(self, sha: str) -> bool:
        return self.storage.exists(self.object_path(sha))

    def put_object(
        self, src: BinaryIO, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Lädt einen Inhalt hoch und gibt seine Prüfsumme zurück (vorhandene Inhalte bleiben)."""
        if self.encrypted:
            return self._put_encrypted(src, progress, cancelled)
        tmp_dir = self._p("tmp")
        self.storage.makedirs(tmp_dir)
        tmp = posixpath.join(tmp_dir, uuid.uuid4().hex)
        sha = self.storage.upload_stream(src, tmp, progress=progress, cancelled=cancelled)
        target = self.object_path(sha)
        try:
            if self.storage.exists(target):
                self.storage.remove(tmp)
            else:
                self.storage.makedirs(posixpath.dirname(target))
                self.storage.rename(tmp, target)
        except BaseException:
            try:
                self.storage.remove(tmp)
            except Exception:
                pass
            raise
        return sha

    def _put_encrypted(
        self, src: BinaryIO, progress: ProgressCallback | None, cancelled: Callable[[], bool] | None,
    ) -> str:
        keys = self._need_keys()
        try:
            start = src.tell()
            src.seek(start)
        except (AttributeError, OSError, ValueError):  # nicht zurückspulbar → zwischenspeichern
            buf = tempfile.TemporaryFile()
            for block in iter(lambda: src.read(CHUNK), b""):
                buf.write(block)
            buf.seek(0)
            src, start = buf, 0
        h = hashlib.sha256()
        for block in iter(lambda: src.read(CHUNK), b""):
            if cancelled and cancelled():
                raise InterruptedError("abgebrochen")
            h.update(block)
        sha = h.hexdigest()
        target = self.object_path(sha)
        if self.storage.exists(target):
            return sha
        src.seek(start)
        name = posixpath.basename(target)
        with spooled() as enc:
            keys.encrypt_stream(src, enc, f"obj:{name}".encode(), cancelled)
            enc.seek(0)
            tmp_dir = self._p("tmp")
            self.storage.makedirs(tmp_dir)
            tmp = posixpath.join(tmp_dir, uuid.uuid4().hex)
            self.storage.upload_stream(enc, tmp, progress=progress, cancelled=cancelled)
        try:
            self.storage.makedirs(posixpath.dirname(target))
            self.storage.rename(tmp, target)
        except BaseException:
            try:
                self.storage.remove(tmp)
            except Exception:
                pass
            raise
        return sha

    def get_object(
        self, sha: str, dst: BinaryIO, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        path = self.object_path(sha)
        if self.encrypted:
            with spooled() as enc:
                self.storage.download_stream(path, enc, progress=progress, cancelled=cancelled)
                enc.seek(0)
                try:
                    got = self._need_keys().decrypt_stream(
                        enc, dst, f"obj:{posixpath.basename(path)}".encode(), cancelled)
                except CryptoError as exc:
                    raise StorageError(str(exc)) from exc
        else:
            got = self.storage.download_stream(path, dst, progress=progress, cancelled=cancelled)
        if got != sha:
            raise StorageError("Prüfsumme stimmt nicht – Inhalt auf dem Speicher beschädigt?")

    # ------------------------------------------------------------ Schreiben
    def commit(
        self,
        entries: list[Entry],
        categories: dict[str, dict],
        devices: dict[str, str],
        host: str,
        os_name: str,
        message: str,
        now: datetime | None = None,
    ) -> Revision:
        """Schreibt eine neue Version und setzt HEAD darauf. Aufrufer muss die Sperre halten."""
        self.ensure_initialized()
        parent = self.head()
        old = self.load_revision(parent).tree() if parent else {}
        new_tree = {tree_key(e): e for e in entries}
        added, changed, deleted = diff_trees(old, new_tree)
        n = parent + 1
        info = RevisionInfo(
            number=n, created=(now or datetime.now()).isoformat(timespec="seconds"),
            host=sanitize_host(host), os=os_name, message=message,
            files=len(new_tree), size=sum(e.size for e in new_tree.values()),
            added=added, changed=changed, deleted=deleted,
        )
        clean = [Entry.from_dict(e.to_dict()) for e in sorted(new_tree.values(), key=lambda e: tree_key(e))]
        rev = Revision(info=info, parent=parent, entries=clean, categories=categories, devices=devices)
        self.storage.makedirs(self._rev_dir())
        self.storage.write_bytes_atomic(
            self._rev_path(n, ".json.gz"), self._seal(gzip.compress(rev.to_json().encode("utf-8")), f"rev:{n}"))
        self.storage.write_bytes_atomic(
            self._rev_path(n, ".info.json"),
            self._seal(json.dumps(info.to_dict(), ensure_ascii=False).encode("utf-8"), f"info:{n}"))
        self.storage.write_bytes_atomic(self._p("HEAD"), f"{n}\n".encode())
        return rev

    def revert_to(self, number: int, host: str, os_name: str) -> Revision:
        """Macht den Stand einer älteren Version wieder zum aktuellen (als neue Version)."""
        old = self.load_revision(number)
        head = self.load_head()
        devices = {**(head.devices if head else {}), **old.devices}
        categories = {**(head.categories if head else {}), **old.categories}
        return self.commit(old.entries, categories, devices, host, os_name,
                           f"Zurückgesetzt auf Version {number}")

    # ------------------------------------------------------------ Umstellung auf Verschlüsselung
    def convert_to_encrypted(
        self,
        keys: StoreKeys,
        info: EncryptionInfo,
        log: Callable[[str], None] | None = None,
        progress: Callable[[int, int, str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        """Verschlüsselt einen bestehenden (oder leeren) Speicher. Aufrufer muss die Sperre halten.

        Absturzsicher: Alles wird zuerst nach ``eobjects/``, ``erevisions/``
        geschrieben; erst danach wird ``store.json`` umgestellt und der alte Stand gelöscht.
        Bricht der Vorgang vorher ab, bleibt der unverschlüsselte Speicher gültig.
        """
        log = log or (lambda _m: None)
        progress = progress or (lambda _d, _t, _c: None)
        cancelled = cancelled or (lambda: False)
        self.ensure_initialized()
        if self.encrypted:
            raise StorageError("Der Speicher ist bereits verschlüsselt.")
        if info.check != keys.check_value():
            raise StorageError("Schlüssel und Schlüsselplätze passen nicht zusammen.")
        plain = Store(self.storage, self.base)  # liest den alten Stand
        enc = Store(self.storage, self.base)
        enc._meta = {**self.meta(), "version": FORMAT_VERSION_ENCRYPTED, "encryption": info.to_dict()}
        enc.keys = keys

        head = plain.head()
        numbers = sorted(r.number for r in plain.list_revisions())
        shas: dict[str, int] = {}
        enc.storage.makedirs(enc._rev_dir())
        for n in numbers:
            if cancelled():
                raise InterruptedError("abgebrochen")
            rev = plain.load_revision(n)
            for e in rev.entries:
                if e.sha256:
                    shas[e.sha256] = e.size
            self.refresh_lock()
            enc.storage.write_bytes_atomic(
                enc._rev_path(n, ".json.gz"), enc._seal(gzip.compress(rev.to_json().encode("utf-8")), f"rev:{n}"))
            enc.storage.write_bytes_atomic(
                enc._rev_path(n, ".info.json"),
                enc._seal(json.dumps(rev.info.to_dict(), ensure_ascii=False).encode("utf-8"), f"info:{n}"))
        log(f"{len(numbers)} Versionen verschlüsselt.")

        total = sum(shas.values())
        done = 0
        for i, (sha, size) in enumerate(sorted(shas.items()), start=1):
            if cancelled():
                raise InterruptedError("abgebrochen")
            progress(done, total, f"[{i}/{len(shas)}] Inhalte verschlüsseln")
            self.refresh_lock()
            if not enc.has_object(sha):
                if not plain.has_object(sha):
                    log(f"Inhalt {sha[:12]}… fehlt im Speicher – übersprungen.")
                    continue
                with tempfile.TemporaryFile() as buf:
                    plain.get_object(sha, buf, cancelled=cancelled)
                    buf.seek(0)
                    enc.put_object(buf, cancelled=cancelled)
            done += size
        log(f"{len(shas)} Inhalte verschlüsselt.")

        # --- Umschalten: ab hier gilt der verschlüsselte Stand
        if plain.head() != head:
            raise StorageError("Der Speicher wurde während der Umstellung verändert.")
        self.storage.write_bytes_atomic(self._p("store.json"), json.dumps(enc._meta, indent=1).encode())
        self._meta = enc._meta
        self.keys = keys
        progress(total, total, "aufräumen")
        for d in ("objects", "revisions", "plugins"):  # plugins/: Überbleibsel älterer Versionen
            try:
                self.storage.remove_tree(self._p(d))
            except (OSError, StorageError, NotImplementedError) as exc:
                log(f"Alter Ordner {d}/ konnte nicht gelöscht werden: {exc}")
        log("Speicher ist jetzt verschlüsselt.")

    # ------------------------------------------------------------ Sperre
    def _read_lock(self) -> dict | None:
        try:
            return json.loads(self.storage.read_bytes(self._p("lock")).decode("utf-8"))
        except Exception:
            return None

    def acquire_lock(self, host: str, force: bool = False) -> None:
        self.storage.makedirs(self.root)
        path = self._p("lock")
        token = uuid.uuid4().hex
        now = datetime.now()
        data = json.dumps({"host": host, "machine": socket.gethostname(), "token": token,
                           "since": now.isoformat(timespec="seconds")}).encode()
        for _attempt in range(2):
            try:
                self.storage.create_exclusive(path, data)
                self._lock_token, self._lock_time = token, now
                return
            except FileExistsError:
                info = self._read_lock() or {}
                try:
                    since = datetime.fromisoformat(info.get("since", ""))
                except ValueError:
                    since = datetime.min
                if force or now - since > LOCK_STALE:
                    try:
                        self.storage.remove(path)
                    except Exception:
                        pass
                    continue
                raise StoreLocked(
                    f"Der Speicher wird gerade von „{info.get('host', '?')}“ abgeglichen "
                    f"(seit {since:%H:%M}). Bitte später erneut versuchen."
                )
        raise StoreLocked("Sperre konnte nicht gesetzt werden.")

    def refresh_lock(self) -> None:
        """Hält eine lange laufende Sperre frisch (sonst gilt sie nach 30 min als verwaist)."""
        if self._lock_token is None or self._lock_time is None:
            return
        now = datetime.now()
        if now - self._lock_time < LOCK_REFRESH:
            return
        info = self._read_lock() or {}
        if info.get("token") != self._lock_token:
            raise StoreLocked("Die Sperre wurde von einem anderen Gerät übernommen.")
        info["since"] = now.isoformat(timespec="seconds")
        self.storage.write_bytes_atomic(self._p("lock"), json.dumps(info).encode())
        self._lock_time = now

    def release_lock(self) -> None:
        if self._lock_token is None:
            return
        info = self._read_lock() or {}
        if info.get("token") == self._lock_token:
            try:
                self.storage.remove(self._p("lock"))
            except Exception:
                pass
        self._lock_token = self._lock_time = None

    @contextmanager
    def locked(self, host: str, force: bool = False) -> Iterator["Store"]:
        self.acquire_lock(host, force)
        try:
            yield self
        finally:
            self.release_lock()


def sha256_file(path, chunk: int = CHUNK) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()
