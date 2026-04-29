"""SAFLII / AfricanLII stub adapter — terms-gated for automated/bulk use.

SAFLII and AfricanLII provide free public access to Southern African legal materials.
Automated or bulk use must comply with their terms of service.
Set SAFLII_BULK_CONFIRMED=1 in .env to enable once terms are confirmed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 10 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """SAFLII is terms-gated; returns error until bulk terms are confirmed."""
    return [], [{
        "source": "SAFLII",
        "status": "gated",
        "reason": (
            "SAFLII/AfricanLII automated/bulk use requires confirmation of compliance "
            "with published terms. Set SAFLII_BULK_CONFIRMED=1 in .env once confirmed."
        ),
    }]
