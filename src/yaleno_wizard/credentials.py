"""Dauerhaft gespeicherte Anmeldedaten (App-Passwort, SSH-Key-Passphrase).

Bevorzugt im Schlüsselbund des Systems (KWallet/GNOME Keyring über Secret Service,
Windows-Anmeldeinformationsverwaltung). Ist keiner verfügbar, landet das Geheimnis in der
Einstellungsdatei (Rechte 0600).
"""

from __future__ import annotations

from .settings import Profile

SERVICE = "yaleno-wizard"


def account(p: Profile) -> str:
    if p.storage_type == "webdav":
        return f"webdav:{p.webdav_user}@{p.webdav_url.rstrip('/')}"
    if p.storage_type == "sftp":
        return f"sftp:{p.username}@{p.host}:{p.port}:{p.key_path}"
    return f"local:{p.local_dir}"


def _plain(p: Profile) -> str:
    return p.webdav_password if p.storage_type == "webdav" else p.sftp_passphrase if p.storage_type == "sftp" else ""


def _set_plain(p: Profile, value: str) -> None:
    if p.storage_type == "webdav":
        p.webdav_password = value
    elif p.storage_type == "sftp":
        p.sftp_passphrase = value


def keyring_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail
        kr = keyring.get_keyring()
        return not isinstance(kr, fail.Keyring) and getattr(kr, "priority", 1) > 0
    except Exception:
        return False


def load_secret(p: Profile) -> str | None:
    """Gespeichertes Passwort für die aktuelle Verbindung (Klartext in der Datei hat Vorrang)."""
    if _plain(p):
        return _plain(p)
    if p.password_store != "keyring":
        return None
    try:
        import keyring
        return keyring.get_password(SERVICE, account(p))
    except Exception:
        return None


def save_secret(p: Profile, value: str | None, store: str) -> str:
    """Speichert (oder löscht bei store="none"/leerem Wert) das Passwort. Gibt den tatsächlichen Ort zurück.

    Ändert nur das Profil im Speicher – danach ``p.save()`` aufrufen.
    """
    value = value or ""
    if store == "keyring" and value:
        try:
            import keyring
            keyring.set_password(SERVICE, account(p), value)
            _set_plain(p, "")
            p.password_store = "keyring"
            return "keyring"
        except Exception:
            store = "file"  # kein Schlüsselbund → Datei
    if store != "keyring":
        delete_keyring_secret(p)
    if store == "file" and value:
        _set_plain(p, value)
        p.password_store = "file"
        return "file"
    _set_plain(p, "")
    p.password_store = "none" if store == "none" else p.password_store
    return p.password_store


def delete_keyring_secret(p: Profile) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, account(p))
    except Exception:
        pass


# ---------------------------------------------------------------------- weitere Geheimnisse
def _secret_file(name: str):
    import hashlib
    from .settings import config_dir
    safe = hashlib.sha256(name.encode("utf-8")).hexdigest()[:32]
    return config_dir() / "keys" / f"{safe}.key"


def save_value(account_name: str, value: str) -> str:
    """Speichert ein Geheimnis im Schlüsselbund, sonst in ``keys/`` (nur für dich lesbar)."""
    import os
    if keyring_available():
        try:
            import keyring
            keyring.set_password(SERVICE, account_name, value)
            _secret_file(account_name).unlink(missing_ok=True)
            return "keyring"
        except Exception:
            pass
    f = _secret_file(account_name)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value)
    return "file"


def load_value(account_name: str) -> str | None:
    try:
        import keyring
        value = keyring.get_password(SERVICE, account_name)
        if value:
            return value
    except Exception:
        pass
    try:
        return _secret_file(account_name).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def delete_value(account_name: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, account_name)
    except Exception:
        pass
    _secret_file(account_name).unlink(missing_ok=True)


# ---------------------------------------------------------------------- Schlüssel verschlüsselter Speicher
def save_store_key(store_id: str, master: bytes) -> str:
    """Merkt den Hauptschlüssel eines verschlüsselten Speichers (für den Hintergrund-Abgleich)."""
    import base64
    return save_value(f"store:{store_id}", base64.b64encode(master).decode("ascii"))


def load_store_key(store_id: str) -> bytes | None:
    import base64
    value = load_value(f"store:{store_id}")
    if not value:
        return None
    try:
        return base64.b64decode(value)
    except ValueError:
        return None


def delete_store_key(store_id: str) -> None:
    delete_value(f"store:{store_id}")


# ---------------------------------------------------------------------- OIDC
def save_oidc_token(account_name: str, refresh_token: str) -> str:
    return save_value(account_name, refresh_token)


def load_oidc_token(account_name: str) -> str | None:
    return load_value(account_name)


def delete_oidc_token(account_name: str) -> None:
    delete_value(account_name)
