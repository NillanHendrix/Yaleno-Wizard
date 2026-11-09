"""Security-Keys/Passkeys (über einen Fake-Authenticator) und App-Sperre."""

from __future__ import annotations

import hashlib
import hmac
import secrets

import pytest

from yaleno_wizard.core import crypto, encryption
from yaleno_wizard.core.store import Store
from yaleno_wizard.plugins import manager
from yaleno_wizard.security import app_lock, fido2
from yaleno_wizard.settings import Profile
from yaleno_wizard.storage.local import LocalStorage


class FakeKey:
    """Ein Security-Key: kennt seine Credentials und liefert PRF wie hmac-secret."""

    def __init__(self, prf: bool = True):
        self.prf = prf
        self.creds: dict[bytes, bytes] = {}  # Credential -> internes Geheimnis
        self.touches = 0

    def register(self, label, exclude, want_prf):
        assert not any(c in self.creds for c in exclude), "Key schon eingerichtet"
        self.touches += 1
        cred = secrets.token_bytes(24)
        self.creds[cred] = secrets.token_bytes(32)
        return cred, self.prf and want_prf

    def authenticate(self, credentials, salts):
        self.touches += 1
        for c in credentials:
            if c in self.creds:
                out = None
                if salts and self.prf and c in salts:
                    out = hmac.new(self.creds[c], salts[c], hashlib.sha256).digest()
                return c, out
        raise fido2.Fido2Error("Kein passender Security-Key.")


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(crypto, "SCRYPT_N", 2 ** 10)
    monkeypatch.setattr(app_lock, "HASH_N", 2 ** 10)


@pytest.fixture
def key(monkeypatch):
    k = FakeKey()
    monkeypatch.setattr(fido2, "_backend_factory", lambda: k)
    return k


def test_store_slot_with_security_key(tmp_path, key):
    storage = LocalStorage(tmp_path / "server")
    store = Store(storage, ".")
    encryption.enable_encryption(store, "pc", "passwort-123")
    slot = fido2.add_store_slot(store, "pc", "YubiKey")
    assert slot.type == "fido2" and key.touches == 2
    other = Store(storage, ".")
    keys = fido2.unlock_store(other)
    assert other.unlocked and keys.master == store.keys.master

    stranger = FakeKey()
    with pytest.raises(fido2.Fido2Error):
        fido2.unlock_store(Store(storage, "."), stranger)
    # Security-Key allein darf nicht übrig bleiben
    by_type = {s.type: s.id for s in store.encryption.slots}
    encryption.remove_slot(store, "pc", by_type["password"])
    with pytest.raises(Exception, match="mindestens ein Passwort"):
        encryption.remove_slot(store, "pc", by_type["recovery"])


def test_key_without_prf_rejected_for_store(tmp_path, monkeypatch):
    k = FakeKey(prf=False)
    store = Store(LocalStorage(tmp_path / "server"), ".")
    encryption.enable_encryption(store, "pc", "passwort-123")
    with pytest.raises(fido2.Fido2Error, match="PRF"):
        fido2.add_store_slot(store, "pc", "Hello", k)


def test_app_lock_password_and_key(key):
    prof = Profile()
    assert not app_lock.active(prof)
    with pytest.raises(app_lock.AppLockError):
        app_lock.set_enabled(prof, True)
    app_lock.set_password(prof, "geheim1")
    app_lock.set_enabled(prof, True)
    assert not app_lock.active(prof)  # Plugin noch aus
    manager.set_enabled("app-sperre", True, prof)
    assert app_lock.active(Profile.load())
    loaded = Profile.load()
    assert "geheim1" not in loaded.to_yaml()
    assert app_lock.check_password(loaded.app_lock_password, "geheim1")
    assert not app_lock.check_password(loaded.app_lock_password, "falsch")

    app_lock.add_key(prof, "YubiKey")
    assert app_lock.unlock_with_key(Profile.load())
    with pytest.raises(fido2.Fido2Error):
        app_lock.unlock_with_key(Profile.load(), FakeKey())
    app_lock.set_password(prof, None)
    app_lock.remove_key(prof, 0)
    assert not Profile.load().app_lock_enabled


def test_prf_helpers():
    from fido2.ctap2.extensions import AuthenticatorExtensionsPRFOutputs, AuthenticatorExtensionsPRFValues
    out = {"prf": AuthenticatorExtensionsPRFOutputs(enabled=True, results=AuthenticatorExtensionsPRFValues(b"x" * 32))}
    assert fido2._prf_first(out) == b"x" * 32 and fido2._prf_enabled(out)
    assert fido2._prf_first({"prf": {"enabled": True}}) is None
    assert fido2._prf_enabled({"prf": {"enabled": True}})
    assert not fido2._prf_enabled({})
