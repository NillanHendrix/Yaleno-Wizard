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


# ---------------------------------------------------------------------- Schlüssel verschlüsselter Speicher
def _store_account(store_id: str) -> str:
    return f"store:{store_id}"


def _store_key_file(store_id: str):
    from .settings import config_dir
    return config_dir() / "keys" / f"{store_id}.key"


def save_store_key(store_id: str, master: bytes) -> str:
    """Merkt den Hauptschlüssel eines verschlüsselten Speichers (für den Hintergrund-Abgleich).

    Bevorzugt im Schlüsselbund, sonst in ``~/.config/yaleno-wizard/keys/<id>.key`` (nur für dich
    lesbar). Gibt den Ort zurück (``keyring`` | ``file``).
    """
    import base64
    import os
    value = base64.b64encode(master).decode("ascii")
    if keyring_available():
        try:
            import keyring
            keyring.set_password(SERVICE, _store_account(store_id), value)
            _store_key_file(store_id).unlink(missing_ok=True)
            return "keyring"
        except Exception:
            pass
    f = _store_key_file(store_id)
    f.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as fh:
        fh.write(value)
    return "file"


def load_store_key(store_id: str) -> bytes | None:
    import base64
    value = None
    try:
        import keyring
        value = keyring.get_password(SERVICE, _store_account(store_id))
    except Exception:
        pass
    if not value:
        try:
            value = _store_key_file(store_id).read_text(encoding="ascii").strip()
        except OSError:
            return None
    try:
        return base64.b64decode(value)
    except ValueError:
        return None


def delete_store_key(store_id: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, _store_account(store_id))
    except Exception:
        pass
    _store_key_file(store_id).unlink(missing_ok=True)
