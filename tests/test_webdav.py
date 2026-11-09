"""WebDAV-Speicher (Nextcloud) gegen einen echten WebDAV-Server."""

from __future__ import annotations

import io
import json

import pytest
import requests

pytest.importorskip("wsgidav")

from yaleno_wizard.catalog import catalog_for  # noqa: E402
from yaleno_wizard.catalog.placeholders import PathMapper  # noqa: E402
from yaleno_wizard.core.reporter import Reporter  # noqa: E402
from yaleno_wizard.core.scanner import Scanner  # noqa: E402
from yaleno_wizard.core.store import Store, StoreLocked  # noqa: E402
from yaleno_wizard.core.sync import ConflictWinner, SyncState, plan_sync, run_sync  # noqa: E402
from yaleno_wizard.storage import webdav  # noqa: E402
from yaleno_wizard.storage.base import StorageError  # noqa: E402
from yaleno_wizard.storage.webdav import WebDAVSettings, WebDAVStorage  # noqa: E402

from .conftest import build_home  # noqa: E402
from .webdav_stub import PASSWORD, USER, DavServer  # noqa: E402

LINUX = catalog_for("linux")
# cheroot meldet beim Beenden des Testservers ggf. einen bereits geschlossenen Socket
pytestmark = pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")


@pytest.fixture
def dav(tmp_path):
    root = tmp_path / "dav"
    root.mkdir()
    srv = DavServer(root)
    yield srv, root
    srv.close()


@pytest.fixture
def storage(dav):
    srv, _ = dav
    st = WebDAVStorage.connect(WebDAVSettings(srv.url, USER, "Yaleno Daten"), PASSWORD)
    yield st
    st.close()


def test_connect_creates_folder_and_rejects_bad_password(dav):
    srv, root = dav
    st = WebDAVStorage.connect(WebDAVSettings(srv.url, USER, "Sicherung/Yaleno"), PASSWORD)
    st.close()
    assert (root / "Sicherung" / "Yaleno").is_dir()
    assert "webdav://tester@" in st.description
    with pytest.raises(StorageError, match="abgelehnt"):
        WebDAVStorage.connect(WebDAVSettings(srv.url, USER, "x"), "falsch")


def test_basic_operations(storage, dav):
    _, root = dav
    base = root / "Yaleno Daten"
    storage.makedirs("a/b ü")
    assert storage.is_dir("a/b ü") and not storage.is_dir("nope")
    storage.write_bytes_atomic("a/b ü/datei #1.txt", b"hallo")
    assert (base / "a" / "b ü" / "datei #1.txt").read_bytes() == b"hallo"
    assert storage.listdir("a/b ü") == ["datei #1.txt"]
    assert storage.listdir("a") == ["b ü"]
    assert storage.read_bytes("a/b ü/datei #1.txt") == b"hallo"
    assert storage.exists("a/b ü/datei #1.txt")

    data = b"x" * 700_000
    seen = []
    sha = storage.upload_stream(io.BytesIO(data), "a/gross.bin", progress=seen.append)
    assert sum(seen) == len(data)
    import hashlib
    assert sha == hashlib.sha256(data).hexdigest()
    assert (base / "a" / "gross.bin").read_bytes() == data
    assert not any(p.name.endswith(".yaleno-tmp") for p in base.rglob("*"))

    storage.rename("a/gross.bin", "a/b ü/datei #1.txt")  # überschreibt
    assert storage.read_bytes("a/b ü/datei #1.txt") == data
    storage.remove("a/b ü/datei #1.txt")
    assert not storage.exists("a/b ü/datei #1.txt")
    with pytest.raises(FileNotFoundError):
        storage.read_bytes("gibtsnicht")
    with pytest.raises(ValueError):
        storage.exists("../ausbruch")


def test_upload_cancel_leaves_nothing(storage, dav):
    _, root = dav
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(InterruptedError):
        storage.upload_stream(io.BytesIO(b"y" * 2_000_000), "abbruch.bin", cancelled=cancelled)
    assert not storage.exists("abbruch.bin")
    assert not any(p.name.startswith("abbruch") for p in (root / "Yaleno Daten").iterdir())


def test_exclusive_create_and_lock(storage):
    storage.create_exclusive("lockfile", b"1")
    with pytest.raises(FileExistsError):
        storage.create_exclusive("lockfile", b"2")
    assert storage.read_bytes("lockfile") == b"1"

    a, b = Store(storage, "."), Store(storage, ".")
    a.acquire_lock("laptop")
    with pytest.raises(StoreLocked, match="laptop"):
        b.acquire_lock("desktop")
    a.release_lock()
    b.acquire_lock("desktop")
    b.release_lock()


def test_sync_two_devices_over_webdav(storage, dav, tmp_path):
    _, root = dav
    cats = ["personal", "shell", "keys"]

    def sync(mapper, host):
        store = Store(storage, ".")
        sid = store.ensure_initialized()
        st = SyncState.load(SyncState.file_for(tmp_path / "state", sid, host))
        entries = Scanner(mapper).scan(LINUX, cats).entries
        plan = plan_sync(store, entries, st, LINUX, mapper, "linux", host, set(cats), None)
        res = run_sync(store, plan, st, LINUX, mapper, "linux", host, ConflictWinner.NEWER, Reporter())
        assert not res.failed, res.failed
        return res

    a = PathMapper(build_home(tmp_path, "laptop"))
    b = PathMapper(build_home(tmp_path, "desktop", files=False))
    r1 = sync(a, "laptop")
    assert r1.uploaded > 0
    assert json.loads((root / "Yaleno Daten" / "yaleno" / "store.json").read_text())["format"] == "yaleno-store"
    r2 = sync(b, "desktop")
    assert r2.downloaded == r1.uploaded
    key = b.to_local("{HOME}/.ssh/id_ed25519")
    assert key.read_text() == "PRIVATE" and key.stat().st_mode & 0o777 == 0o600

    b.to_local("{DOCUMENTS}/notiz.txt").write_text("vom desktop")
    sync(b, "desktop")
    sync(a, "laptop")
    assert a.to_local("{DOCUMENTS}/notiz.txt").read_text() == "vom desktop"
    assert [i.number for i in Store(storage, ".").list_revisions()] == [3, 2, 1]


# ---------------------------------------------------------------------- Nextcloud-Erkennung
class _FakeResp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("kein JSON")
        return self._payload


def test_discover_plain_webdav_and_explicit_path(monkeypatch):
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: _FakeResp(404))
    assert webdav.discover_dav_root("https://dav.example.org/files", "u", "p") == "https://dav.example.org/files/"
    assert (webdav.discover_dav_root("https://c.example.org/remote.php/dav/files/x", "u", "p")
            == "https://c.example.org/remote.php/dav/files/x/")


def test_discover_nextcloud_uses_user_id(monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, "get",
                        lambda self, url, **kw: calls.append(url) or _FakeResp(200, {"installed": True}))
    principal = (b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:href>/nc/remote.php/dav/'
                 b'</d:href><d:propstat><d:prop><d:current-user-principal><d:href>'
                 b'/nc/remote.php/dav/principals/users/niko%20k/</d:href></d:current-user-principal></d:prop>'
                 b'</d:propstat></d:response></d:multistatus>')
    monkeypatch.setattr(requests.Session, "request",
                        lambda self, method, url, **kw: _FakeResp(207, content=principal))
    root = webdav.discover_dav_root("https://cloud.example.org/nc/", "niko@example.org", "p")
    assert calls == ["https://cloud.example.org/nc/status.php"]
    assert root == "https://cloud.example.org/nc/remote.php/dav/files/niko%20k/"
