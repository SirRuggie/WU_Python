"""Shared artwork metadata for the five recruiter-authored ticket flags.

Static R2 keys mirror the repository's ``assets/`` tree. Discord component
renderers use the local files, so publishing the same files to R2 does not add
a network request each time the ticket console redraws.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote


@dataclass(frozen=True, slots=True)
class FlagArt:
    label: str
    emoji: str
    filename: str
    color: str
    hub_label: str | None = None

    @property
    def local_path(self) -> Path:
        return Path(__file__).resolve().parents[1] / "assets" / "tickets" / self.filename

    @property
    def r2_key(self) -> str:
        return f"tickets/{self.filename}"

    def public_url(self) -> str | None:
        base = os.getenv("R2_PUBLIC_BASE_URL", "").strip().rstrip("/")
        return f"{base}/{quote(self.r2_key, safe='/')}" if base else None


FLAG_ART = MappingProxyType({
    "blacklisted": FlagArt("Blacklisted", "⛔", "flag_blacklisted.png", "#dd1c1d"),
    "denied_before": FlagArt("Previously denied", "⚠️", "flag_denied_before.png", "#ffcc00", "DENIED BEFORE"),
    "not_loyal": FlagArt("Not loyal to WU", "💔", "flag_not_loyal.png", "#f17511"),
    "ghosted": FlagArt("Ghosted", "👻", "flag_ghosted.png", "#08c3fa"),
    "flew_the_coop": FlagArt("Flew the Coop", "🐔", "flag_flew_the_coop.png", "#bd00df"),
})
