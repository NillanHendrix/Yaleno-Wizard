"""Ende-zu-Ende-Verschlüsselung des Speichers.

Ein zufälliger 32-Byte-**Hauptschlüssel** verschlüsselt alles. Er liegt im Speicher nur
**umhüllt** in Schlüsselplätzen (``store.json``), die sich mit Passwort, Wiederherstellungsschlüssel
oder Security-Key (FIDO2 hmac-secret) öffnen lassen. Aus dem Hauptschlüssel werden per HKDF
abgeleitet:

* ``data`` – AES-256-GCM für Inhalte und Versionen
* ``name`` – HMAC-SHA256 für Objektnamen (der Server sieht keine Prüfsummen bekannter Dateien)

Datenformat (Strom)::

    "YLE1" | Nonce-Präfix (8 Byte) | Block 0 | Block 1 | … | letzter Block

Jeder Block = AES-GCM(1 MiB Klartext) mit Nonce = Präfix + Blockzähler (4 Byte) und
AAD = Kontext | Zähler | Endblock-Kennung. Vertauschen, Kürzen oder Verlängern fällt auf.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import secrets
import tempfile
from dataclasses import dataclass, field
from typing import BinaryIO, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SCHEME = "yaleno-aes256gcm-1"
MAGIC = b"YLE1"
BLOCK = 1024 * 1024
TAG = 16
KEY_LEN = 32
SCRYPT_N = 2 ** 17   # ~128 MiB Speicher, ca. 0,3–1 s
SCRYPT_R = 8
SCRYPT_P = 1
SPOOL_MAX = 8 * 1024 * 1024


class CryptoError(ValueError):
    pass


class WrongKey(CryptoError):
    pass


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hkdf(key: bytes, info: bytes, length: int = KEY_LEN) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info).derive(key)


def new_master_key() -> bytes:
    return secrets.token_bytes(KEY_LEN)


def spooled() -> tempfile.SpooledTemporaryFile:
    return tempfile.SpooledTemporaryFile(max_size=SPOOL_MAX)


# ---------------------------------------------------------------------- Schlüssel des Speichers
class StoreKeys:
    def __init__(self, master: bytes):
        if len(master) != KEY_LEN:
            raise CryptoError("Ungültiger Schlüssel.")
        self.master = master
        self._aead = AESGCM(hkdf(master, b"yaleno data"))
        self._name_key = hkdf(master, b"yaleno names")

    def check_value(self) -> str:
        """Prüfwert, um den richtigen Hauptschlüssel zu erkennen (verrät nichts über ihn)."""
        return b64e(hkdf(self.master, b"yaleno key check", 16))

    def object_name(self, sha: str) -> str:
        return hmac.new(self._name_key, sha.encode("ascii"), hashlib.sha256).hexdigest()

    def name(self, kind: str, value: str) -> str:
        return hmac.new(self._name_key, f"{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()[:32]

    # ---------------------------------------------------------------- Blöcke
    @staticmethod
    def _nonce(prefix: bytes, n: int) -> bytes:
        return prefix + n.to_bytes(4, "big")

    @staticmethod
    def _aad(context: bytes, n: int, final: bool) -> bytes:
        return context + b"|" + n.to_bytes(4, "big") + (b"F" if final else b"-")

    def encrypt_stream(
        self, src: BinaryIO, dst: BinaryIO, context: bytes,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Verschlüsselt ``src`` nach ``dst``; gibt den SHA-256 des Klartexts zurück."""
        prefix = secrets.token_bytes(8)
        dst.write(MAGIC + prefix)
        h = hashlib.sha256()
        n = 0
        cur = src.read(BLOCK)
        while True:
            if cancelled and cancelled():
                raise InterruptedError("abgebrochen")
            nxt = src.read(BLOCK)
            final = not nxt
            h.update(cur)
            dst.write(self._aead.encrypt(self._nonce(prefix, n), cur, self._aad(context, n, final)))
            if final:
                break
            n += 1
            if n >= 2 ** 32:
                raise CryptoError("Datei zu groß.")
            cur = nxt
        return h.hexdigest()

    def decrypt_stream(
        self, src: BinaryIO, dst: BinaryIO, context: bytes,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Entschlüsselt ``src`` nach ``dst``; gibt den SHA-256 des Klartexts zurück."""
        head = src.read(len(MAGIC) + 8)
        if len(head) != len(MAGIC) + 8 or head[:4] != MAGIC:
            raise CryptoError("Keine verschlüsselten Yaleno-Daten.")
        prefix = head[4:]
        h = hashlib.sha256()
        n = 0
        cur = src.read(BLOCK + TAG)
        while True:
            if cancelled and cancelled():
                raise InterruptedError("abgebrochen")
            nxt = src.read(BLOCK + TAG)
            final = not nxt
            try:
                plain = self._aead.decrypt(self._nonce(prefix, n), cur, self._aad(context, n, final))
            except InvalidTag as exc:
                raise CryptoError("Entschlüsseln fehlgeschlagen – Daten beschädigt oder falscher Schlüssel.") from exc
            h.update(plain)
            dst.write(plain)
            if final:
                break
            n += 1
            cur = nxt
        return h.hexdigest()

    def encrypt_bytes(self, data: bytes, context: bytes) -> bytes:
        out = io.BytesIO()
        self.encrypt_stream(io.BytesIO(data), out, context)
        return out.getvalue()

    def decrypt_bytes(self, data: bytes, context: bytes) -> bytes:
        out = io.BytesIO()
        self.decrypt_stream(io.BytesIO(data), out, context)
        return out.getvalue()


# ---------------------------------------------------------------------- Schlüsselplätze
def _wrap(kek: bytes, master: bytes, slot_id: str) -> str:
    nonce = secrets.token_bytes(12)
    return b64e(nonce + AESGCM(kek).encrypt(nonce, master, b"yaleno-slot:" + slot_id.encode()))


def _unwrap(kek: bytes, wrapped: str, slot_id: str) -> bytes:
    raw = b64d(wrapped)
    try:
        return AESGCM(kek).decrypt(raw[:12], raw[12:], b"yaleno-slot:" + slot_id.encode())
    except InvalidTag as exc:
        raise WrongKey("Falsches Passwort bzw. falscher Schlüssel.") from exc


def _scrypt(secret: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=KEY_LEN, n=n, r=r, p=p).derive(secret.encode("utf-8"))


@dataclass
class KeySlot:
    """Ein Weg, den Hauptschlüssel zu öffnen."""

    id: str
    type: str                 # password | recovery | fido2
    label: str
    wrapped: str
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"id": self.id, "type": self.type, "label": self.label, "wrapped": self.wrapped, **self.params}

    @classmethod
    def from_dict(cls, d: dict) -> "KeySlot":
        known = {"id", "type", "label", "wrapped"}
        return cls(id=str(d["id"]), type=str(d["type"]), label=str(d.get("label", "")),
                   wrapped=str(d["wrapped"]), params={k: v for k, v in d.items() if k not in known})

    # ---------------------------------------------------------------- Passwort
    @classmethod
    def for_password(cls, master: bytes, password: str, label: str = "Passwort") -> "KeySlot":
        if len(password) < 8:
            raise CryptoError("Das Passwort muss mindestens 8 Zeichen lang sein.")
        sid = secrets.token_hex(4)
        salt = secrets.token_bytes(16)
        params = {"kdf": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P, "salt": b64e(salt)}
        kek = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
        return cls(sid, "password", label, _wrap(kek, master, sid), params)

    def open_password(self, password: str) -> bytes:
        p = self.params
        kek = _scrypt(password, b64d(p["salt"]), int(p["n"]), int(p["r"]), int(p["p"]))
        return _unwrap(kek, self.wrapped, self.id)

    # ---------------------------------------------------------------- Wiederherstellungsschlüssel
    @classmethod
    def for_recovery(cls, master: bytes, label: str = "Wiederherstellungsschlüssel") -> tuple["KeySlot", str]:
        raw = secrets.token_bytes(KEY_LEN)
        sid = secrets.token_hex(4)
        return cls(sid, "recovery", label, _wrap(hkdf(raw, b"yaleno recovery"), master, sid)), format_recovery(raw)

    def open_recovery(self, code: str) -> bytes:
        return _unwrap(hkdf(parse_recovery(code), b"yaleno recovery"), self.wrapped, self.id)

    # ---------------------------------------------------------------- FIDO2 (hmac-secret)
    @classmethod
    def for_secret(cls, master: bytes, secret: bytes, type_: str, label: str, params: dict) -> "KeySlot":
        """Platz für ein Geheimnis aus einem Gerät (z. B. FIDO2 hmac-secret)."""
        sid = secrets.token_hex(4)
        return cls(sid, type_, label, _wrap(hkdf(secret, b"yaleno device"), master, sid), dict(params))

    def open_secret(self, secret: bytes) -> bytes:
        return _unwrap(hkdf(secret, b"yaleno device"), self.wrapped, self.id)


def format_recovery(raw: bytes) -> str:
    text = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(text[i:i + 4] for i in range(0, len(text), 4))


def parse_recovery(code: str) -> bytes:
    text = "".join(c for c in code.upper() if c.isalnum())
    text = text.replace("0", "O").replace("1", "I").replace("8", "B")  # häufige Verwechslungen
    try:
        raw = base64.b32decode(text + "=" * (-len(text) % 8))
    except (ValueError, base64.binascii.Error) as exc:
        raise WrongKey("Der Wiederherstellungsschlüssel ist ungültig.") from exc
    if len(raw) != KEY_LEN:
        raise WrongKey("Der Wiederherstellungsschlüssel ist unvollständig.")
    return raw


@dataclass
class EncryptionInfo:
    """Der ``encryption``-Abschnitt in ``store.json``."""

    check: str
    slots: list[KeySlot] = field(default_factory=list)
    scheme: str = SCHEME

    def to_dict(self) -> dict:
        return {"scheme": self.scheme, "check": self.check, "slots": [s.to_dict() for s in self.slots]}

    @classmethod
    def from_dict(cls, d: dict) -> "EncryptionInfo":
        if d.get("scheme") != SCHEME:
            raise CryptoError(f"Unbekanntes Verschlüsselungsverfahren „{d.get('scheme')}“ – "
                              "bitte den Yaleno Wizard aktualisieren.")
        return cls(check=str(d["check"]), slots=[KeySlot.from_dict(s) for s in d.get("slots", [])])

    def verify(self, master: bytes) -> StoreKeys:
        keys = StoreKeys(master)
        if not hmac.compare_digest(keys.check_value(), self.check):
            raise WrongKey("Der Schlüssel passt nicht zu diesem Speicher.")
        return keys

    def unlock_password(self, password: str) -> StoreKeys:
        for s in self.slots:
            if s.type == "password":
                try:
                    return self.verify(s.open_password(password))
                except WrongKey:
                    continue
        raise WrongKey("Falsches Passwort.")

    def unlock_recovery(self, code: str) -> StoreKeys:
        raw_ok = False
        for s in self.slots:
            if s.type == "recovery":
                raw_ok = True
                try:
                    return self.verify(s.open_recovery(code))
                except WrongKey:
                    continue
        raise WrongKey("Falscher Wiederherstellungsschlüssel." if raw_ok
                       else "Für diesen Speicher gibt es keinen Wiederherstellungsschlüssel.")

