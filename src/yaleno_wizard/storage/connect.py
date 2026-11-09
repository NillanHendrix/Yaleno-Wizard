"""Speicher anhand der Einstellungen öffnen (gemeinsam für Wizard und Hintergrund-Abgleich)."""

from __future__ import annotations

from ..settings import Profile, known_hosts_file
from .base import Storage, StorageError
from .local import LocalStorage
from .sftp import ConnectionSettings, HostKeyConfirm, SFTPStorage
from .webdav import WebDAVSettings, WebDAVStorage


def reject_unknown_host(host: str, key_type: str, fp: str) -> bool:
    raise StorageError(f"Der Server {host} ist noch nicht bekannt ({key_type} {fp}). "
                       "Bitte einmal im Wizard verbinden und den Fingerprint bestätigen.")


def oidc_auth(p: Profile, tokens=None):
    """Bearer-Authentifizierung mit dem gemerkten Refresh-Token (wird bei Erneuerung neu gemerkt)."""
    from ..credentials import load_oidc_token, save_oidc_token
    from .auth import OIDCBearerAuth, TokenSet
    cfg = p.oidc_config()
    if tokens is None:
        refresh_token = load_oidc_token(cfg.account)
        if not refresh_token:
            raise StorageError("OIDC: nicht angemeldet – bitte im Wizard „Mit OIDC anmelden …“.")
        tokens = TokenSet(refresh_token=refresh_token)

    def remember(new) -> None:
        if new.refresh_token:
            try:
                save_oidc_token(cfg.account, new.refresh_token)
            except OSError:
                pass
    return OIDCBearerAuth(cfg, tokens, on_refresh=remember)


def open_storage(
    p: Profile, secret: str | None, confirm_host_key: HostKeyConfirm = reject_unknown_host, auth=None,
) -> tuple[Storage, str]:
    """Gibt (Speicher, Basisordner) zurück. ``auth`` ersetzt bei OIDC das gemerkte Token."""
    if p.storage_type == "local":
        if not p.local_dir.strip():
            raise StorageError("Kein Ordner für den lokalen Speicher angegeben.")
        return LocalStorage(p.local_dir.strip()), "."
    if p.storage_type == "webdav" and p.webdav_auth == "oidc":
        if not (p.webdav_url and p.oidc_issuer and p.oidc_client_id):
            raise StorageError("OIDC: Server, Anbieter (issuer) und Client-ID fehlen.")
        return WebDAVStorage.connect(WebDAVSettings(p.webdav_url, p.webdav_user, p.webdav_folder), "",
                                     auth=auth or oidc_auth(p)), "."
    if p.storage_type == "webdav":
        if not (p.webdav_url and p.webdav_user):
            raise StorageError("Nextcloud/WebDAV: Server und Benutzer fehlen.")
        if not secret:
            raise StorageError("Nextcloud/WebDAV: kein App-Passwort gespeichert.")
        return WebDAVStorage.connect(WebDAVSettings(p.webdav_url, p.webdav_user, p.webdav_folder), secret), "."
    if not (p.host and p.username and p.key_path):
        raise StorageError("SFTP: Server, Benutzer und SSH-Key fehlen.")
    base = p.base_path or "."
    storage = SFTPStorage.connect(ConnectionSettings(p.host, p.port, p.username, p.key_path, base),
                                  known_hosts_file(), confirm_host_key, passphrase=secret or None)
    if not storage.is_dir(base):
        storage.close()
        raise StorageError(f"Der Ordner '{base}' existiert auf dem Server nicht.")
    return storage, base
