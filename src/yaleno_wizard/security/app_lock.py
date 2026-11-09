"""App-Sperre: Der Wizard öffnet sich erst nach Passwort oder Security-Key/Passkey.

Schützt die **Bedienung** (z. B. am gemeinsam genutzten Rechner), nicht die Dateien auf der
Festplatte – den Schutz der Daten im Speicher leistet die Verschlüsselung. Aktiv nur, wenn das
Plugin „App-Sperre“ aktiviert ist. Einstellungen in ``yaleno.yml``::

    app_lock:
      enabled: true
      password_hash: scrypt$16384$8$1$<salt>$<hash>
      security_keys:
        - {label: YubiKey, credential: <base64>}
"""

from __future__ import annotations

import hmac
import secrets

from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from ..core.crypto import b64d, b64e
from ..settings import Profile
from . import fido2

HASH_N = 2 ** 15


class AppLockError(Exception):
    pass


def hash_password(password: str, n: int | None = None) -> str:
    n = n or HASH_N
    salt = secrets.token_bytes(16)
    digest = Scrypt(salt=salt, length=32, n=n, r=8, p=1).derive(password.encode("utf-8"))
    return f"scrypt${n}$8$1${b64e(salt)}${b64e(digest)}"


def check_password(stored: str, password: str) -> bool:
    try:
        kind, n, r, p, salt, digest = stored.split("$")
        if kind != "scrypt":
            return False
        got = Scrypt(salt=b64d(salt), length=32, n=int(n), r=int(r), p=int(p)).derive(password.encode("utf-8"))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got, b64d(digest))


def active(profile: Profile) -> bool:
    """Muss vor dem Öffnen entsperrt werden?"""
    if not profile.app_lock_enabled or not (profile.app_lock_password or profile.app_lock_keys):
        return False
    from ..plugins.registry import feature_enabled
    return feature_enabled("app_lock", profile)


def set_password(profile: Profile, password: str | None) -> None:
    if password is not None and len(password) < 6:
        raise AppLockError("Das Passwort muss mindestens 6 Zeichen lang sein.")
    profile.app_lock_password = hash_password(password) if password else ""
    profile.save()


def set_enabled(profile: Profile, on: bool) -> None:
    if on and not (profile.app_lock_password or profile.app_lock_keys):
        raise AppLockError("Bitte zuerst ein Passwort oder einen Security-Key einrichten.")
    profile.app_lock_enabled = on
    profile.save()


def add_key(profile: Profile, label: str, be: fido2.Fido2Backend | None = None) -> None:
    be = be or fido2.backend()
    exclude = [b64d(k["credential"]) for k in profile.app_lock_keys]
    cred, _prf = be.register(label, exclude, want_prf=False)
    profile.app_lock_keys.append({"label": label, "credential": b64e(cred)})
    profile.save()


def remove_key(profile: Profile, index: int) -> None:
    del profile.app_lock_keys[index]
    if not profile.app_lock_keys and not profile.app_lock_password:
        profile.app_lock_enabled = False
    profile.save()


def unlock_with_key(profile: Profile, be: fido2.Fido2Backend | None = None) -> bool:
    if not profile.app_lock_keys:
        raise AppLockError("Kein Security-Key eingerichtet.")
    be = be or fido2.backend()
    creds = [b64d(k["credential"]) for k in profile.app_lock_keys]
    used, _ = be.authenticate(creds, None)  # Signatur wird im Backend geprüft
    return used in creds
