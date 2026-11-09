"""Abstraktes Speicher-Interface. Remote-Pfade sind immer POSIX-Strings ("a/b/c")."""

from __future__ import annotations

import hashlib
import posixpath
from abc import ABC, abstractmethod
from typing import BinaryIO, Callable

CHUNK = 256 * 1024

ProgressCallback = Callable[[int], None]  # erhält die Anzahl neu übertragener Bytes


class StorageError(Exception):
    pass


class Storage(ABC):
    """Minimaler Satz an Operationen, den Sicherung und Wiederherstellung brauchen."""

    @abstractmethod
    def listdir(self, path: str) -> list[str]: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...

    @abstractmethod
    def is_dir(self, path: str) -> bool: ...

    @abstractmethod
    def mkdir(self, path: str) -> None:
        """Legt genau ein Verzeichnis an (Eltern müssen existieren)."""

    @abstractmethod
    def open_read(self, path: str) -> BinaryIO: ...

    @abstractmethod
    def open_write(self, path: str) -> BinaryIO: ...

    @abstractmethod
    def rename(self, src: str, dst: str) -> None:
        """Ersetzt dst atomar, falls vorhanden."""

    @abstractmethod
    def remove(self, path: str) -> None: ...

    def chmod(self, path: str, mode: int) -> None:  # optional
        pass

    def close(self) -> None:
        pass

    @property
    def description(self) -> str:
        return self.__class__.__name__

    # ------------------------------------------------------------------ helpers
    def makedirs(self, path: str, mode: int = 0o700) -> None:
        path = path.rstrip("/")
        if not path or self.exists(path):
            return
        parent = posixpath.dirname(path)
        if parent and parent != path:
            self.makedirs(parent, mode)
        try:
            self.mkdir(path)
            self.chmod(path, mode)
        except Exception:
            if not self.is_dir(path):
                raise

    def read_bytes(self, path: str) -> bytes:
        with self.open_read(path) as fh:
            return fh.read()

    def write_bytes_atomic(self, path: str, data: bytes) -> None:
        part = path + ".part"
        with self.open_write(part) as fh:
            fh.write(data)
        self.chmod(part, 0o600)
        self.rename(part, path)

    def upload_stream(
        self, src: BinaryIO, path: str, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        """Kopiert einen lokalen Stream atomar nach path, gibt sha256 zurück."""
        part = path + ".part"
        digest = hashlib.sha256()
        try:
            with self.open_write(part) as dst:
                while True:
                    if cancelled and cancelled():
                        raise InterruptedError("abgebrochen")
                    chunk = src.read(CHUNK)
                    if not chunk:
                        break
                    digest.update(chunk)
                    dst.write(chunk)
                    if progress:
                        progress(len(chunk))
            self.chmod(part, 0o600)
            self.rename(part, path)
        except BaseException:
            try:
                self.remove(part)
            except Exception:
                pass
            raise
        return digest.hexdigest()

    def download_stream(
        self, path: str, dst: BinaryIO, progress: ProgressCallback | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> str:
        digest = hashlib.sha256()
        with self.open_read(path) as src:
            while True:
                if cancelled and cancelled():
                    raise InterruptedError("abgebrochen")
                chunk = src.read(CHUNK)
                if not chunk:
                    break
                digest.update(chunk)
                dst.write(chunk)
                if progress:
                    progress(len(chunk))
        return digest.hexdigest()
