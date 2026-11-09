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


def open_storage(
    p: Profile, secret: str | None, confirm_host_key: HostKeyConfirm = reject_unknown_host,
) -> tuple[Storage, str]:
    """Gibt (Speicher, Basisordner) zurück."""
    if p.storage_type == "local":
        if not p.local_dir.strip():
            raise StorageError("Kein Ordner für den lokalen Speicher angegeben.")
        return LocalStorage(p.local_dir.strip()), "."
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
