"""Security-Keys und Passkeys (FIDO2/WebAuthn).

Zwei Verwendungen:

* **Speicher entsperren** – über die PRF-/hmac-secret-Erweiterung liefert der Key zu einem
  festen Salz immer dasselbe 32-Byte-Geheimnis. Damit wird der Hauptschlüssel im Schlüsselplatz
  ``fido2`` umhüllt (``core/crypto.py``). Funktioniert mit jedem Gerät, auf dem der Key steckt.
* **App-Sperre** – eine normale WebAuthn-Anmeldung; die Signatur wird mit dem bei der
  Einrichtung gespeicherten öffentlichen Schlüssel geprüft.

Linux: USB/NFC-Security-Keys (über hidraw, ggf. udev-Regel des Herstellers nötig).
Windows: über die WebAuthn-Schnittstelle des Systems – Security-Keys, Windows Hello und
Handy-Passkeys.

Die eigentliche Hardware-Ansprache steckt hinter ``Fido2Backend``; Tests setzen mit
``set_backend()`` einen Ersatz ein.
"""

from __future__ import annotations

import secrets
import sys
from typing import Callable, Protocol

from ..core.crypto import StoreKeys, b64d, b64e

RP_ID = "yaleno.wizard"
RP_NAME = "Yaleno Wizard"
ORIGIN = f"https://{RP_ID}"
SALT_LEN = 32


class Fido2Error(Exception):
    pass


class Fido2Backend(Protocol):
    def register(self, label: str, exclude: list[bytes], want_prf: bool) -> tuple[bytes, bool]:
        """Legt ein Credential an. Gibt (Credential-Daten, PRF unterstützt) zurück."""

    def authenticate(self, credentials: list[bytes], salts: dict[bytes, bytes] | None) -> tuple[bytes, bytes | None]:
        """Meldet sich mit einem der Credentials an (Signatur geprüft).

        ``salts``: Credential-Daten → Salz für PRF. Gibt (verwendete Credential-Daten, PRF-Ergebnis) zurück.
        """


# ---------------------------------------------------------------------- echte Hardware
class _UI:
    def __init__(self, ask_pin: Callable[[], str | None] | None, prompt: Callable[[str], None] | None):
        self._ask_pin = ask_pin
        self._prompt = prompt or (lambda _m: None)

    def prompt_up(self) -> None:
        self._prompt("Bitte den Security-Key berühren …")

    def request_pin(self, permissions, rp_id) -> str | None:
        if self._ask_pin is None:
            return None
        return self._ask_pin()

    def request_uv(self, permissions, rp_id) -> bool:
        self._prompt("Bitte am Security-Key bestätigen …")
        return True


def _prf_first(ext) -> bytes | None:
    if not ext:
        return None
    prf = ext.get("prf") if hasattr(ext, "get") else None
    if prf is None:
        return None
    results = getattr(prf, "results", None) if not isinstance(prf, dict) else prf.get("results")
    if results is None:
        return None
    first = getattr(results, "first", None) if not isinstance(results, dict) else results.get("first")
    if isinstance(first, str):
        from fido2.utils import websafe_decode
        first = websafe_decode(first)
    return bytes(first) if first else None


def _prf_enabled(ext) -> bool:
    if not ext or not hasattr(ext, "get"):
        return False
    prf = ext.get("prf")
    if prf is None:
        return False
    enabled = getattr(prf, "enabled", None) if not isinstance(prf, dict) else prf.get("enabled")
    return bool(enabled) or _prf_first(ext) is not None


class HardwareBackend:
    """Spricht Security-Keys über python-fido2 an (Windows: WebAuthn-API des Systems)."""

    def __init__(self, ask_pin: Callable[[], str | None] | None = None,
                 prompt: Callable[[str], None] | None = None):
        self.ask_pin = ask_pin
        self.prompt = prompt

    def _client(self):
        try:
            from fido2.client import DefaultClientDataCollector, Fido2Client
        except ImportError as exc:  # pragma: no cover - fehlt nur bei kaputter Installation
            raise Fido2Error("Die FIDO2-Unterstützung (Paket „fido2“) ist nicht installiert.") from exc
        collector = DefaultClientDataCollector(ORIGIN)
        if sys.platform.startswith("win"):  # pragma: no cover - nur Windows
            from fido2.client.windows import WindowsClient
            if WindowsClient.is_available():
                return WindowsClient(collector, allow_hmac_secret=True)
        from fido2.hid import CtapHidDevice
        devices = list(CtapHidDevice.list_devices())
        if not devices:
            raise Fido2Error("Kein Security-Key gefunden. Bitte einstecken (unter Linux ggf. die udev-Regel "
                             "des Herstellers installieren) und erneut versuchen.")
        return Fido2Client(devices[0], collector, user_interaction=_UI(self.ask_pin, self.prompt))

    def _server(self):
        from fido2.server import Fido2Server
        from fido2.webauthn import PublicKeyCredentialRpEntity
        return Fido2Server(PublicKeyCredentialRpEntity(id=RP_ID, name=RP_NAME))

    def register(self, label: str, exclude: list[bytes], want_prf: bool) -> tuple[bytes, bool]:
        from fido2.webauthn import (
            AttestedCredentialData, PublicKeyCredentialUserEntity, ResidentKeyRequirement,
            UserVerificationRequirement,
        )
        server = self._server()
        user = PublicKeyCredentialUserEntity(id=secrets.token_bytes(16), name=label, display_name=label)
        options, state = server.register_begin(
            user, [AttestedCredentialData(c) for c in exclude],
            resident_key_requirement=ResidentKeyRequirement.DISCOURAGED,
            user_verification=UserVerificationRequirement.DISCOURAGED,
            extensions={"prf": {}} if want_prf else None,
        )
        try:
            resp = self._client().make_credential(options.public_key)
            auth = server.register_complete(state, resp)
        except Fido2Error:
            raise
        except Exception as exc:
            raise Fido2Error(f"Einrichten fehlgeschlagen: {exc}") from exc
        cred = auth.credential_data
        if cred is None:
            raise Fido2Error("Der Security-Key hat keine Zugangsdaten geliefert.")
        return bytes(cred), _prf_enabled(resp.client_extension_results)

    def authenticate(self, credentials: list[bytes], salts: dict[bytes, bytes] | None) -> tuple[bytes, bytes | None]:
        from fido2.utils import websafe_encode
        from fido2.webauthn import AttestedCredentialData, UserVerificationRequirement
        server = self._server()
        creds = [AttestedCredentialData(c) for c in credentials]
        ext = None
        if salts:
            ext = {"prf": {"evalByCredential": {
                websafe_encode(AttestedCredentialData(c).credential_id): {"first": websafe_encode(s)}
                for c, s in salts.items()}}}
        options, state = server.authenticate_begin(
            creds, user_verification=UserVerificationRequirement.DISCOURAGED, extensions=ext)
        try:
            sel = self._client().get_assertion(options.public_key)
            resp = sel.get_response(0)
            used = server.authenticate_complete(state, creds, resp)
        except Fido2Error:
            raise
        except Exception as exc:
            raise Fido2Error(f"Anmeldung mit dem Security-Key fehlgeschlagen: {exc}") from exc
        return bytes(used), _prf_first(resp.client_extension_results)


_backend_factory: Callable[[], Fido2Backend] = HardwareBackend


def set_backend(factory: Callable[[], Fido2Backend]) -> None:
    global _backend_factory
    _backend_factory = factory


def backend() -> Fido2Backend:
    return _backend_factory()


# ---------------------------------------------------------------------- Speicher entsperren
def add_store_slot(store, host: str, label: str, be: Fido2Backend | None = None):
    """Richtet einen Security-Key als Schlüsselplatz ein (Speicher muss entsperrt sein)."""
    from ..core import encryption
    be = be or backend()
    info = store.encryption
    exclude = [b64d(s.params["credential"]) for s in info.slots if s.type == "fido2"] if info else []
    cred, prf = be.register(label, exclude, want_prf=True)
    if not prf:
        raise Fido2Error("Dieser Security-Key/Passkey unterstützt keine Schlüsselableitung (PRF/hmac-secret). "
                         "Er taugt für die App-Sperre, aber nicht zum Entsperren des Speichers.")
    salt = secrets.token_bytes(SALT_LEN)
    used, secret = be.authenticate([cred], {cred: salt})
    if secret is None or used != cred:
        raise Fido2Error("Der Security-Key hat kein Geheimnis geliefert – bitte erneut versuchen.")
    return encryption.add_secret_slot(store, host, secret, "fido2", label,
                                      {"credential": b64e(cred), "salt": b64e(salt)})


def unlock_store(store, be: Fido2Backend | None = None) -> StoreKeys:
    info = store.encryption
    slots = [s for s in info.slots if s.type == "fido2"] if info else []
    if not slots:
        raise Fido2Error("Für diesen Speicher ist kein Security-Key eingerichtet.")
    be = be or backend()
    by_cred = {b64d(s.params["credential"]): s for s in slots}
    used, secret = be.authenticate(list(by_cred), {c: b64d(s.params["salt"]) for c, s in by_cred.items()})
    slot = by_cred.get(used)
    if slot is None or secret is None:
        raise Fido2Error("Der Security-Key hat kein passendes Geheimnis geliefert.")
    keys = info.verify(slot.open_secret(secret))
    store.keys = keys
    return keys
