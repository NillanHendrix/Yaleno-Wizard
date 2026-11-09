"""Eine einzelne Datei im Bestand (lokal gescannt oder aus einer Version des Speichers)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Entry:
    category: str
    logical: str          # "{DOCUMENTS}/a/b.pdf" oder "@cmd/<item>.txt"
    item: str = ""
    size: int = 0
    mtime: float = 0.0
    mode: int = 0o644
    sha256: str = ""
    scope: str = ""       # Bereich im Speicher: "all", "os:linux", "host:<name>"
    source: Path | None = field(default=None, compare=False)  # nur lokal, nicht serialisiert

    @property
    def key(self) -> tuple[str, str]:
        return (self.category, self.logical)

    @property
    def is_command(self) -> bool:
        return self.logical.startswith("@cmd/")

    def remote_relpath(self) -> str:
        """Relativer Ablagepfad: files/<kategorie>/<PLATZHALTER>/<rest> (für den Ablageordner)."""
        if self.is_command:
            rest = "_commands/" + self.logical[len("@cmd/"):]
        else:
            rest = self.logical.replace("{", "", 1).replace("}", "", 1)
        return f"files/{self.category}/{rest}"

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "logical": self.logical,
            "item": self.item,
            "size": self.size,
            "mtime": self.mtime,
            "mode": self.mode,
            "sha256": self.sha256,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Entry":
        return cls(
            category=d["category"],
            logical=d["logical"],
            item=d.get("item", ""),
            size=int(d.get("size", 0)),
            mtime=float(d.get("mtime", 0.0)),
            mode=int(d.get("mode", 0o644)),
            sha256=d.get("sha256", ""),
            scope=d.get("scope", ""),
        )


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
