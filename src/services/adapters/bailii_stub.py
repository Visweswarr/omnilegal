"""BAILII stub adapter — terms-gated; bulk use disabled until terms confirmed.

BAILII provides free public access to UK and Ireland case law.
Automated or bulk use must comply with BAILII's terms of service.
Set UK_FIND_CASE_LAW_LICENSE_CONFIRMED or a dedicated BAILII_BULK_CONFIRMED
env var to enable bulk ingestion once terms are confirmed with BAILII.
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
    """BAILII is terms-gated; returns error until bulk terms are confirmed."""
    return [], [{
        "source": "BAILII",
        "status": "gated",
        "reason": (
            "BAILII bulk/automated use requires confirmation of compliance with BAILII terms. "
            "Set BAILII_BULK_CONFIRMED=1 in .env once confirmed to enable this adapter."
        ),
    }]
