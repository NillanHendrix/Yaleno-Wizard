"""Anmeldung im Browser: Nextcloud Login Flow v2 und OpenID Connect (OIDC).

**Nextcloud Login Flow v2** – Nextcloud zeigt im Browser ihr normales Anmeldefenster (mit
Passkey, Zwei-Faktor, SSO …) und gibt danach ein frisch erzeugtes App-Passwort heraus.

**OIDC** – Authorization Code Flow mit PKCE und Loopback-Umleitung (``http://127.0.0.1:<port>``,
RFC 8252). Das Refresh-Token wird im Schlüsselbund gemerkt; WebDAV-Anfragen tragen
``Authorization: Bearer <access_token>``. Nextcloud braucht dafür die App ``user_oidc`` mit
aktivierter Bearer-Token-Prüfung.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

import requests
from requests.auth import AuthBase

from .. import __version__
from .base import StorageError

TIMEOUT = 30
UA = {"User-Agent": f"yaleno-wizard/{__version__}"}


class AuthError(StorageError):
    pass


def _check_cancel(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise InterruptedError("abgebrochen")


# ---------------------------------------------------------------------- Nextcloud Login Flow v2
@dataclass
class LoginFlow:
    login_url: str
    endpoint: str
    token: str


@dataclass
class LoginResult:
    server: str
    login_name: str
    app_password: str


def login_flow_start(server_url: str, verify: bool | str = True) -> LoginFlow:
    base = server_url.strip().rstrip("/")
    if "://" not in base:
        base = "https://" + base
    try:
        r = requests.post(base + "/index.php/login/v2", headers=UA, timeout=TIMEOUT, verify=verify)
    except requests.RequestException as exc:
        raise AuthError(f"Nextcloud unter {base} nicht erreichbar: {exc}") from exc
    if r.status_code != 200:
        raise AuthError(f"{base} unterstützt die Anmeldung im Browser nicht (Antwort {r.status_code}). "
                        "Ist das eine Nextcloud ab Version 16?")
    try:
        d = r.json()
        return LoginFlow(d["login"], d["poll"]["endpoint"], d["poll"]["token"])
    except (ValueError, KeyError) as exc:
        raise AuthError("Unerwartete Antwort von Nextcloud.") from exc


def login_flow_poll(
    flow: LoginFlow, timeout: float = 20 * 60, interval: float = 2.0,
    cancelled: Callable[[], bool] | None = None, verify: bool | str = True,
) -> LoginResult:
    """Wartet, bis im Browser angemeldet wurde (Nextcloud antwortet bis dahin mit 404)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        _check_cancel(cancelled)
        try:
            r = requests.post(flow.endpoint, data={"token": flow.token}, headers=UA, timeout=TIMEOUT, verify=verify)
        except requests.RequestException as exc:
            raise AuthError(f"Verbindung zu Nextcloud unterbrochen: {exc}") from exc
        if r.status_code == 200:
            try:
                d = r.json()
                return LoginResult(d["server"], d["loginName"], d["appPassword"])
            except (ValueError, KeyError) as exc:
                raise AuthError("Unerwartete Antwort von Nextcloud.") from exc
        if r.status_code != 404:
            raise AuthError(f"Anmeldung fehlgeschlagen (Antwort {r.status_code}).")
        step = time.monotonic() + interval
        while time.monotonic() < step:
            _check_cancel(cancelled)
            time.sleep(min(0.1, interval))
    raise AuthError("Zeit für die Anmeldung im Browser abgelaufen.")


# ---------------------------------------------------------------------- OIDC
@dataclass
class OIDCConfig:
    issuer: str
    client_id: str
    scopes: tuple[str, ...] = ("openid", "profile", "email", "offline_access")
    client_secret: str = ""

    @property
    def account(self) -> str:
        return f"oidc:{self.issuer.rstrip('/')}:{self.client_id}"


@dataclass
class TokenSet:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    id_claims: dict = field(default_factory=dict)

    def valid(self, margin: float = 60) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - margin


_discovery_cache: dict[str, dict] = {}


def discover(issuer: str, verify: bool | str = True) -> dict:
    issuer = issuer.rstrip("/")
    if issuer in _discovery_cache:
        return _discovery_cache[issuer]
    if not issuer.startswith("https://") and not issuer.startswith("http://127.0.0.1"):
        raise AuthError("Der OIDC-Anbieter muss per https:// erreichbar sein.")
    url = issuer + "/.well-known/openid-configuration"
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, verify=verify)
        d = r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError) as exc:
        raise AuthError(f"OIDC-Anbieter {issuer} nicht erreichbar: {exc}") from exc
    if not d or "authorization_endpoint" not in d or "token_endpoint" not in d:
        raise AuthError(f"{url} liefert keine gültige OIDC-Konfiguration.")
    _discovery_cache[issuer] = d
    return d


def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _jwt_claims(token: str) -> dict:
    """Liest die Angaben aus einem ID-Token (nur zur Anzeige; die Signatur prüft der Server)."""
    import json
    try:
        part = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except (IndexError, ValueError):
        return {}


def _token_request(cfg: OIDCConfig, data: dict, verify: bool | str = True) -> TokenSet:
    meta = discover(cfg.issuer, verify)
    data = {**data, "client_id": cfg.client_id}
    if cfg.client_secret:
        data["client_secret"] = cfg.client_secret
    try:
        r = requests.post(meta["token_endpoint"], data=data, headers=UA, timeout=TIMEOUT, verify=verify)
    except requests.RequestException as exc:
        raise AuthError(f"OIDC-Anbieter nicht erreichbar: {exc}") from exc
    try:
        d = r.json()
    except ValueError:
        d = {}
    if r.status_code != 200 or "access_token" not in d:
        why = d.get("error_description") or d.get("error") or f"Antwort {r.status_code}"
        raise AuthError(f"OIDC-Anmeldung abgelehnt: {why}")
    return TokenSet(
        access_token=d["access_token"], refresh_token=d.get("refresh_token", data.get("refresh_token", "")),
        expires_at=time.time() + float(d.get("expires_in", 300)),
        id_claims=_jwt_claims(d["id_token"]) if d.get("id_token") else {},
    )


class _Callback(http.server.BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self) -> None:  # noqa: N802 - Name von http.server vorgegeben
        q = parse_qs(urlsplit(self.path).query)
        if "code" not in q and "error" not in q:
            self.send_response(404)
            self.end_headers()
            return
        self.server.result = {k: v[0] for k, v in q.items()}  # type: ignore[attr-defined]
        ok = "code" in q
        body = ("<html><body style='font-family:sans-serif'><h2>"
                + ("✔ Angemeldet – du kannst dieses Fenster schließen und zum Yaleno Wizard zurückkehren."
                   if ok else "✘ Anmeldung abgebrochen.") + "</h2></body></html>").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


def authorize(
    cfg: OIDCConfig,
    open_browser: Callable[[str], object] = webbrowser.open,
    timeout: float = 300,
    cancelled: Callable[[], bool] | None = None,
    verify: bool | str = True,
) -> TokenSet:
    """Öffnet den Browser zur Anmeldung und wartet auf die Rückkehr (Code → Token)."""
    meta = discover(cfg.issuer, verify)
    verifier = secrets.token_urlsafe(64)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    server = http.server.HTTPServer(("127.0.0.1", 0), _Callback)
    server.result = {}  # type: ignore[attr-defined]
    server.timeout = 0.2
    redirect = f"http://127.0.0.1:{server.server_address[1]}/callback"
    params = {
        "response_type": "code", "client_id": cfg.client_id, "redirect_uri": redirect,
        "scope": " ".join(cfg.scopes), "state": state, "nonce": nonce,
        "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256",
    }
    sep = "&" if "?" in meta["authorization_endpoint"] else "?"
    url = meta["authorization_endpoint"] + sep + urlencode(params)
    try:
        open_browser(url)
        end = time.monotonic() + timeout
        while not server.result and time.monotonic() < end:  # type: ignore[attr-defined]
            _check_cancel(cancelled)
            server.handle_request()
    finally:
        server.server_close()
    res = server.result  # type: ignore[attr-defined]
    if not res:
        raise AuthError("Zeit für die Anmeldung im Browser abgelaufen.")
    if res.get("state") != state:
        raise AuthError("Antwort des OIDC-Anbieters passt nicht zur Anfrage (state).")
    if "error" in res:
        raise AuthError(f"OIDC-Anmeldung abgelehnt: {res.get('error_description') or res['error']}")
    tokens = _token_request(cfg, {"grant_type": "authorization_code", "code": res["code"],
                                  "redirect_uri": redirect, "code_verifier": verifier}, verify)
    if tokens.id_claims.get("nonce") not in (None, nonce):
        raise AuthError("Antwort des OIDC-Anbieters passt nicht zur Anfrage (nonce).")
    return tokens


def refresh(cfg: OIDCConfig, refresh_token: str, verify: bool | str = True) -> TokenSet:
    if not refresh_token:
        raise AuthError("Nicht per OIDC angemeldet – bitte im Wizard „Mit OIDC anmelden …“.")
    return _token_request(cfg, {"grant_type": "refresh_token", "refresh_token": refresh_token}, verify)


class OIDCBearerAuth(AuthBase):
    """Setzt das Access-Token und erneuert es bei Ablauf bzw. bei 401 automatisch."""

    def __init__(self, cfg: OIDCConfig, tokens: TokenSet,
                 on_refresh: Callable[[TokenSet], None] | None = None, verify: bool | str = True):
        self.cfg = cfg
        self.tokens = tokens
        self.on_refresh = on_refresh
        self.verify = verify
        self._lock = threading.Lock()

    def _renew(self) -> None:
        new = refresh(self.cfg, self.tokens.refresh_token, self.verify)
        self.tokens = new
        if self.on_refresh:
            self.on_refresh(new)

    def _ensure(self) -> str:
        with self._lock:
            if not self.tokens.valid():
                self._renew()
            return self.tokens.access_token

    def __call__(self, r: requests.PreparedRequest) -> requests.PreparedRequest:
        r.headers["Authorization"] = f"Bearer {self._ensure()}"
        r.register_hook("response", self._retry_401)
        return r

    def _retry_401(self, resp: requests.Response, **kwargs) -> requests.Response:
        if resp.status_code != 401 or getattr(resp.request, "_yaleno_retried", False):
            return resp
        with self._lock:
            self._renew()
        req = resp.request.copy()
        req._yaleno_retried = True  # type: ignore[attr-defined]
        req.headers["Authorization"] = f"Bearer {self.tokens.access_token}"
        body = req.body
        if hasattr(body, "seek"):
            try:
                body.seek(0)
            except (OSError, ValueError):
                return resp  # Datenstrom nicht wiederholbar
        elif body is not None and not isinstance(body, (bytes, str)):
            return resp  # Generator o. ä. – nicht wiederholbar
        resp.content  # Verbindung freigeben
        resp.close()
        new = resp.connection.send(req, **kwargs)
        new.history.append(resp)
        return new
