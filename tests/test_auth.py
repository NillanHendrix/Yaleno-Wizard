"""Anmeldung im Browser: Nextcloud Login Flow v2 und OIDC (gegen einen lokalen Stub-Server)."""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import requests

from yaleno_wizard.storage import auth
from yaleno_wizard.storage.auth import AuthError, OIDCBearerAuth, OIDCConfig, TokenSet


class Stub:
    def __init__(self):
        self.logged_in_after = 2      # Login Flow: so viele Abfragen bis „angemeldet“
        self.polls = 0
        self.codes: dict[str, dict] = {}
        self.valid_tokens: set[str] = set()
        self.refreshes = 0
        self.last_verifier = ""


def make_handler(stub: Stub, base: list[str]):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, data):
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _form(self):
            n = int(self.headers.get("Content-Length") or 0)
            return {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path == "/realm/.well-known/openid-configuration":
                return self._json(200, {"authorization_endpoint": base[0] + "/authorize",
                                        "token_endpoint": base[0] + "/token"})
            if u.path == "/authorize":
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                assert q["code_challenge_method"] == "S256" and q["response_type"] == "code"
                code = "code-" + q["state"][:6]
                stub.codes[code] = q
                self.send_response(302)
                self.send_header("Location", q["redirect_uri"] + "?" + urlencode({"code": code, "state": q["state"]}))
                self.end_headers()
                return
            if u.path == "/dav":
                tok = (self.headers.get("Authorization") or "").removeprefix("Bearer ")
                return self._json(200 if tok in stub.valid_tokens else 401, {"token": tok})
            self._json(404, {})

        def do_POST(self):
            u = urlsplit(self.path)
            if u.path == "/index.php/login/v2":
                return self._json(200, {"poll": {"token": "t0k", "endpoint": base[0] + "/login/v2/poll"},
                                        "login": base[0] + "/login/v2/flow/abc"})
            if u.path == "/login/v2/poll":
                assert self._form()["token"] == "t0k"
                stub.polls += 1
                if stub.polls < stub.logged_in_after:
                    return self._json(404, {})
                return self._json(200, {"server": base[0], "loginName": "niko", "appPassword": "app-pw"})
            if u.path == "/token":
                f = self._form()
                if f["grant_type"] == "authorization_code":
                    req = stub.codes.pop(f["code"], None)
                    import base64, hashlib
                    ok = req and base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()
                                                         ).rstrip(b"=").decode() == req["code_challenge"]
                    if not ok:
                        return self._json(400, {"error": "invalid_grant"})
                    claims = base64.urlsafe_b64encode(json.dumps(
                        {"preferred_username": "niko", "nonce": req["nonce"]}).encode()).rstrip(b"=").decode()
                    stub.valid_tokens.add("access-1")
                    return self._json(200, {"access_token": "access-1", "refresh_token": "refresh-1",
                                            "expires_in": 300, "id_token": f"x.{claims}.y"})
                if f["grant_type"] == "refresh_token":
                    if not f["refresh_token"].startswith("refresh-"):
                        return self._json(400, {"error": "invalid_grant", "error_description": "abgelaufen"})
                    stub.refreshes += 1
                    tok = f"access-r{stub.refreshes}"
                    stub.valid_tokens = {tok}
                    return self._json(200, {"access_token": tok, "refresh_token": f"refresh-{stub.refreshes + 1}",
                                            "expires_in": 300})
            self._json(404, {})
    return H


@pytest.fixture
def server():
    stub = Stub()
    base: list[str] = [""]
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stub, base))
    base[0] = f"http://127.0.0.1:{httpd.server_address[1]}"
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    auth._discovery_cache.clear()
    yield stub, base[0]
    httpd.shutdown()


def test_login_flow(server):
    stub, base = server
    flow = auth.login_flow_start(base)
    assert flow.login_url.endswith("/login/v2/flow/abc")
    res = auth.login_flow_poll(flow, interval=0.01)
    assert (res.login_name, res.app_password) == ("niko", "app-pw") and stub.polls == 2


def test_login_flow_cancel(server):
    stub, base = server
    stub.logged_in_after = 10 ** 6
    flow = auth.login_flow_start(base)
    t0 = time.monotonic()
    with pytest.raises(InterruptedError):
        auth.login_flow_poll(flow, interval=0.05, cancelled=lambda: time.monotonic() - t0 > 0.2)


def test_oidc_authorize_and_bearer_refresh(server):
    stub, base = server
    cfg = OIDCConfig(base + "/realm", "yaleno-wizard")

    def browser(url):  # „Browser“: folgt der Umleitung zur Loopback-Adresse
        threading.Thread(target=lambda: requests.get(url, timeout=10), daemon=True).start()

    tokens = auth.authorize(cfg, open_browser=browser, timeout=10)
    assert tokens.access_token == "access-1" and tokens.refresh_token == "refresh-1"
    assert tokens.id_claims["preferred_username"] == "niko"

    seen = []
    a = OIDCBearerAuth(cfg, tokens, on_refresh=seen.append)
    assert requests.get(base + "/dav", auth=a, timeout=10).status_code == 200
    # Token serverseitig widerrufen → 401 → erneuern → nochmal
    stub.valid_tokens.clear()
    r = requests.get(base + "/dav", auth=a, timeout=10)
    assert r.status_code == 200 and r.json()["token"] == "access-r1" and seen[-1].refresh_token == "refresh-2"
    # abgelaufen → vorab erneuern
    a.tokens.expires_at = time.time()
    assert requests.get(base + "/dav", auth=a, timeout=10).json()["token"] == "access-r2"

    bad = OIDCBearerAuth(cfg, TokenSet(refresh_token="kaputt"))
    with pytest.raises(AuthError, match="abgelaufen"):
        requests.get(base + "/dav", auth=bad, timeout=10)


def test_oidc_rejects_wrong_state(server, monkeypatch):
    stub, base = server
    cfg = OIDCConfig(base + "/realm", "yaleno-wizard")

    def browser(url):
        q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
        threading.Thread(target=lambda: requests.get(
            q["redirect_uri"] + "?code=x&state=falsch", timeout=10), daemon=True).start()

    with pytest.raises(AuthError, match="state"):
        auth.authorize(cfg, open_browser=browser, timeout=10)


def test_discover_requires_https():
    auth._discovery_cache.clear()
    with pytest.raises(AuthError, match="https"):
        auth.discover("http://id.example.org")


def test_open_storage_oidc_needs_login():
    from yaleno_wizard.settings import Profile
    from yaleno_wizard.storage.base import StorageError
    from yaleno_wizard.storage.connect import open_storage
    p = Profile(storage_type="webdav", webdav_url="https://cloud.example.org", webdav_auth="oidc",
                oidc_issuer="https://id.example.org", oidc_client_id="yaleno")
    with pytest.raises(StorageError, match="nicht angemeldet"):
        open_storage(p, None)
