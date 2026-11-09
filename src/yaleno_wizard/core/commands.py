"""Ausführen der Befehls-Items (dconf, reg, winget, Paketlisten)."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from ..catalog.model import Item

TIMEOUT = 600


def _run(argv: list[str], stdin: bytes | None = None) -> subprocess.CompletedProcess:
    kwargs: dict = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(argv, input=stdin, capture_output=True, timeout=TIMEOUT, check=False, **kwargs)


def _decode(b: bytes) -> str:
    return b.decode("utf-8", errors="replace").strip()


def run_backup_command(item: Item) -> bytes:
    argv = list(item.backup_cmd)
    if "{OUT}" in argv:
        with tempfile.TemporaryDirectory(prefix="yaleno-") as tmp:
            out = Path(tmp) / f"{item.id}.{item.output_ext}"
            argv = [str(out) if a == "{OUT}" else a for a in argv]
            proc = _run(argv)
            if out.exists():
                return out.read_bytes()
            raise RuntimeError(_decode(proc.stderr) or _decode(proc.stdout) or f"Exit-Code {proc.returncode}")
    proc = _run(argv)
    if proc.returncode != 0 and not proc.stdout:
        err = _decode(proc.stderr)
        if err:
            raise RuntimeError(err)
    return proc.stdout


def run_restore_command(item: Item, data: bytes) -> str:
    argv = list(item.restore_cmd)
    if not argv:
        raise RuntimeError("Für diesen Eintrag gibt es keinen Wiederherstellungs-Befehl.")
    if "{IN}" in argv:
        with tempfile.TemporaryDirectory(prefix="yaleno-") as tmp:
            inp = Path(tmp) / f"{item.id}.{item.output_ext}"
            inp.write_bytes(data)
            argv = [str(inp) if a == "{IN}" else a for a in argv]
            proc = _run(argv)
    else:
        proc = _run(argv, stdin=data)
    output = "\n".join(x for x in (_decode(proc.stdout), _decode(proc.stderr)) if x)
    if proc.returncode != 0:
        raise RuntimeError(output or f"Exit-Code {proc.returncode}")
    return output
