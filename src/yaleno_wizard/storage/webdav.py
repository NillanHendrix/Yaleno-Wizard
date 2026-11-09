"""WebDAV-Speicher, insbesondere Nextcloud (Anmeldung mit App-Passwort).

Bei Nextcloud genügt die normale Server-Adresse (z. B. ``https://cloud.example.org``); der
WebDAV-Pfad ``/remote.php/dav/files/<benutzer-id>/`` wird automatisch ermittelt. Jeder andere
WebDAV-Server wird über seine vollständige WebDAV-Adresse angesprochen.
"""

from __future__ import annotations

import hashlib
import os
import posixpath
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import BinaryIO, Callable
from urllib.parse import quote, unquote, urljoin, urlsplit

import requests

from .. import __version__
from .base import CHUNK, ProgressCallback, Storage, StorageError

DAV = "{DAV:}"
TIMEOUT = (15, 300)  # Verbindungsaufbau, Lesen


@dataclass
class WebDAVSettings:
    url: str              # Nextcloud-Adresse oder vollständige WebDAV-Adresse
    username: str
    folder: str = "Yaleno"


def _err(resp: requests.Response, what: str) -> StorageError:
    code = resp.status_code
    if code == 401:
        return StorageError("Anmeldung abgelehnt – Benutzername und App-Passwort prüfen.")
    if code == 403:
        return StorageError(f"Zugriff verweigert ({what}).")
    if code == 507:
        return StorageError("Kein Speicherplatz mehr auf dem Server (Quota erreicht).")
    return StorageError(f"WebDAV-Fehler {code} {resp.reason} ({what})")


class _PutFile:
    """Datei-Objekt für open_write: sammelt die Daten und lädt sie beim Schließen hoch."""

    def __init__(self, storage: "WebDAVStorage", path: str):
        self._storage = storage
        self._path = path
        self._buf = tempfile.SpooledTemporaryFile(max_size=8 << 20)
        self._closed = False

    def write(self, data: bytes) -> int:
        return self._buf.write(data)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            size = self._buf.tell()
            self._buf.seek(0)
            self._storage._put(self._path, self._buf, size)
        finally:
            self._buf.close()

    def discard(self) -> None:
        self._closed = True
        self._buf.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            self.discard()


class _UploadBody:
    """Liest aus dem Quell-Stream, berechnet SHA-256, meldet Fortschritt und prüft auf Abbruch.

    Hat eine feste Länge, damit ohne „chunked“-Übertragung hochgeladen wird (manche
    Nextcloud-Installationen mit nginx/PHP-FPM speichern sonst leere Dateien)."""

    def __init__(self, src: BinaryIO, size: int, progress: ProgressCallback | None,
                 cancelled: Callable[[], bool] | None):
        self.src = src
        self.size = size
        self.progress = progress
        self.cancelled = cancelled
        self.digest = hashlib.sha256()
        self.sent = 0
        self.was_cancelled = False

    def __len__(self) -> int:
        return self.size

    def read(self, n: int = -1) -> bytes:
        if self.cancelled and self.cancelled():
            self.was_cancelled = True
            raise InterruptedError("abgebrochen")
        # nie mehr als angekündigt senden (Datei könnte währenddessen wachsen)
        want = min(n if n and n > 0 else CHUNK, CHUNK, self.size - self.sent)
        if want <= 0:
            return b""
        chunk = self.src.read(want)
        if chunk:
            self.digest.update(chunk)
            self.sent += len(chunk)
            if self.progress:
                self.progress(len(chunk))
        return chunk

    def __iter__(self):
        while True:
            chunk = self.read(CHUNK)
            if not chunk:
                return
            yield chunk


def _stream_size(src: BinaryIO) -> int | None:
    try:
        return os.fstat(src.fileno()).st_size - src.tell()
    except (AttributeError, OSError, ValueError):
        pass
    try:
        pos = src.tell()
        end = src.seek(0, os.SEEK_END)
        src.seek(pos)
        return end - pos
    except (AttributeError, OSError, ValueError):
        return None


class WebDAVStorage(Storage):
    PART_SUFFIX = ".yaleno-tmp"  # Nextcloud behandelt *.part-Dateien besonders

    def __init__(self, root_url: str, username: str, password: str, label: str | None = None,
                 verify: bool | str = True):
        if not root_url.endswith("/"):
            root_url += "/"
        self.root_url = root_url
        self._root_path = unquote(urlsplit(root_url).path).rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify
        self.session.headers["User-Agent"] = f"yaleno-wizard/{__version__}"
        self._label = label or root_url

    # ---------------------------------------------------------------- verbinden
    @classmethod
    def connect(cls, settings: WebDAVSettings, password: str, verify: bool | str = True) -> "WebDAVStorage":
        url = settings.url.strip()
        if "://" not in url:
            url = "https://" + url
        dav_root = discover_dav_root(url, settings.username, password, verify)
        st = cls(dav_root, settings.username, password, verify=verify)
        st.check_access()
        folder = "/".join(p for p in settings.folder.strip().strip("/").split("/") if p not in ("", "."))
        if folder:
            st.makedirs(folder)
            st = cls(dav_root + quote(folder) + "/", settings.username, password, verify=verify)
        host = urlsplit(url).netloc
        st._label = f"webdav://{settings.username}@{host}/{folder}"
        return st

    def check_access(self) -> None:
        resp = self._request("PROPFIND", "", headers={"Depth": "0"}, what="Anmeldung")
        if resp.status_code not in (207, 200):
            raise _err(resp, "Anmeldung")

    # ---------------------------------------------------------------- intern
    def _url(self, path: str, collection: bool = False) -> str:
        parts = [p for p in path.split("/") if p not in ("", ".")]
        if ".." in parts:
            raise ValueError(f"Ungültiger Pfad: {path}")
        rel = "/".join(quote(p) for p in parts)
        if collection and rel:
            rel += "/"
        return self.root_url + rel

    def _request(self, method: str, path: str, what: str = "", collection: bool = False, **kw) -> requests.Response:
        try:
            return self.session.request(method, self._url(path, collection), timeout=TIMEOUT, **kw)
        except requests.exceptions.SSLError as exc:
            raise StorageError(f"TLS-Zertifikat des Servers wurde nicht akzeptiert: {exc}") from exc
        except requests.RequestException as exc:
            raise StorageError(f"Verbindung zum WebDAV-Server fehlgeschlagen: {exc}") from exc

    def _propfind(self, path: str, depth: int) -> ET.Element | None:
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:resourcetype/>'
                '</d:prop></d:propfind>')
        resp = self._request("PROPFIND", path, what=path, collection=depth > 0,
                             headers={"Depth": str(depth), "Content-Type": "application/xml"}, data=body)
        if resp.status_code == 404:
            return None
        if resp.status_code != 207:
            raise _err(resp, f"PROPFIND {path}")
        return ET.fromstring(resp.content)

    def _put(self, path: str, data, size: int, extra_headers: dict | None = None) -> requests.Response:
        headers = {"Content-Length": str(size), "Content-Type": "application/octet-stream",
                   **(extra_headers or {})}
        # Nextcloud prüft damit, ob alles angekommen ist
        headers["OC-Total-Length"] = str(size)
        resp = self._request("PUT", path, what=path, data=data, headers=headers)
        if resp.status_code not in (200, 201, 204):
            if resp.status_code == 412:
                raise FileExistsError(path)
            raise _err(resp, f"Hochladen {path}")
        return resp

    # ---------------------------------------------------------------- Storage-API
    def listdir(self, path: str) -> list[str]:
        tree = self._propfind(path, 1)
        if tree is None:
            raise FileNotFoundError(path)
        own = posixpath.normpath(unquote(urlsplit(self._url(path)).path))
        names = []
        for resp in tree.findall(f"{DAV}response"):
            href = resp.findtext(f"{DAV}href") or ""
            p = posixpath.normpath(unquote(urlsplit(href).path))
            if p == own:
                continue
            names.append(posixpath.basename(p))
        return sorted(n for n in names if n)

    def exists(self, path: str) -> bool:
        return self._propfind(path, 0) is not None

    def is_dir(self, path: str) -> bool:
        tree = self._propfind(path, 0)
        if tree is None:
            return False
        return tree.find(f".//{DAV}resourcetype/{DAV}collection") is not None

    def mkdir(self, path: str) -> None:
        resp = self._request("MKCOL", path, what=path, collection=True)
        if resp.status_code not in (201, 200):
            if resp.status_code == 405:  # existiert bereits
                raise FileExistsError(path)
            raise _err(resp, f"Ordner anlegen {path}")

    def open_read(self, path: str) -> BinaryIO:
        resp = self._request("GET", path, what=path, stream=True)
        if resp.status_code == 404:
            resp.close()
            raise FileNotFoundError(path)
        if resp.status_code != 200:
            resp.close()
            raise _err(resp, f"Lesen {path}")
        resp.raw.decode_content = True
        return resp.raw  # type: ignore[return-value]

    def open_write(self, path: str) -> BinaryIO:
        return _PutFile(self, path)  # type: ignore[return-value]

    def create_exclusive(self, path: str, data: bytes) -> None:
        self._put(path, data, len(data), {"If-None-Match": "*"})

    def rename(self, src: str, dst: str) -> None:
        resp = self._request("MOVE", src, what=src,
                             headers={"Destination": self._url(dst), "Overwrite": "T"})
        if resp.status_code not in (201, 204):
            raise _err(resp, f"Verschieben {src} → {dst}")

    def rmdir(self, path: str) -> None:
        resp = self._request("DELETE", path, what=path, collection=True)
        if resp.status_code not in (200, 204, 404):
            raise _err(resp, f"Löschen {path}")

    def remove_tree(self, path: str) -> None:
        self.rmdir(path)  # WebDAV löscht Ordner samt Inhalt

    def remove(self, path: str) -> None:
        resp = self._request("DELETE", path, what=path)
        if resp.status_code == 404:
            raise FileNotFoundError(path)
        if resp.status_code not in (200, 204):
            raise _err(resp, f"Löschen {path}")

    def close(self) -> None:
        self.session.close()

    @property
    def description(self) -> str:
        return self._label

    # ---------------------------------------------------------------- Streams
    def upload_stream(
        self, src: BinaryIO, path: str, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        size = _stream_size(src)
        spool = None
        if size is None:  # unbekannte Länge → zwischenspeichern
            spool = tempfile.TemporaryFile()
            while chunk := src.read(CHUNK):
                spool.write(chunk)
            size = spool.tell()
            spool.seek(0)
            src = spool
        part = path + self.PART_SUFFIX
        body = _UploadBody(src, size, progress, cancelled)
        try:
            try:
                self._put(part, body, size)
            except StorageError:
                if body.was_cancelled:
                    raise InterruptedError("abgebrochen") from None
                raise
            if body.sent != size:
                raise StorageError(f"Datei hat sich während des Hochladens geändert: {path}")
            self.rename(part, path)
        except BaseException:
            try:
                self.remove(part)
            except Exception:
                pass
            raise
        finally:
            if spool is not None:
                spool.close()
        return body.digest.hexdigest()

    def write_bytes_atomic(self, path: str, data: bytes) -> None:
        part = path + self.PART_SUFFIX
        self._put(part, data, len(data))
        self.rename(part, path)


# ---------------------------------------------------------------------- Nextcloud
def discover_dav_root(url: str, username: str, password: str, verify: bool | str = True) -> str:
    """Ermittelt die WebDAV-Adresse der Dateien.

    Ist ``url`` eine Nextcloud (``status.php`` antwortet), wird über den angemeldeten Benutzer
    ``/remote.php/dav/files/<id>/`` bestimmt – die ID kann vom Anmeldenamen abweichen (z. B. bei
    Anmeldung per E-Mail). Andernfalls wird ``url`` unverändert als WebDAV-Adresse verwendet.
    """
    base = url.rstrip("/")
    if "/remote.php/" in base:
        return base + "/"
    session = requests.Session()
    session.verify = verify
    session.headers["User-Agent"] = f"yaleno-wizard/{__version__}"
    try:
        try:
            r = session.get(base + "/status.php", timeout=TIMEOUT)
            is_nc = r.ok and "installed" in r.json()
        except (ValueError, requests.RequestException) as exc:
            if isinstance(exc, requests.exceptions.SSLError):
                raise StorageError(f"TLS-Zertifikat des Servers wurde nicht akzeptiert: {exc}") from exc
            if isinstance(exc, requests.exceptions.ConnectionError):
                raise StorageError(f"Server {base} nicht erreichbar: {exc}") from exc
            is_nc = False
        if not is_nc:
            return base + "/"
        body = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop><d:current-user-principal/>'
                '</d:prop></d:propfind>')
        try:
            r = session.request("PROPFIND", base + "/remote.php/dav/", auth=(username, password),
                                data=body, headers={"Depth": "0", "Content-Type": "application/xml"},
                                timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise StorageError(f"Verbindung zu Nextcloud fehlgeschlagen: {exc}") from exc
        if r.status_code == 401:
            raise StorageError("Anmeldung bei Nextcloud abgelehnt – Benutzername und App-Passwort prüfen.")
        uid = username
        if r.status_code == 207:
            href = ET.fromstring(r.content).findtext(f".//{DAV}current-user-principal/{DAV}href") or ""
            # …/remote.php/dav/principals/users/<uid>/
            parts = [p for p in unquote(urlsplit(href).path).split("/") if p]
            if len(parts) >= 2 and parts[-2] == "users":
                uid = parts[-1]
        return urljoin(base + "/", f"remote.php/dav/files/{quote(uid)}/")
    finally:
        session.close()
