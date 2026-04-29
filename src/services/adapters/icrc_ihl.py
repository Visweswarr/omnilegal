"""ICRC IHL databases adapter — treaty and customary IHL seed records."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from src.config import COLLECTION_INTL_TREATIES, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://ihl-databases.icrc.org"

_IHL_TREATIES = [
    ("Geneva Convention I", "1949", "Protection of wounded and sick in armed forces in the field", "75 UNTS 31"),
    ("Geneva Convention II", "1949", "Protection of wounded, sick and shipwrecked at sea", "75 UNTS 85"),
    ("Geneva Convention III", "1949", "Treatment of prisoners of war", "75 UNTS 135"),
    ("Geneva Convention IV", "1949", "Protection of civilian persons in time of war", "75 UNTS 287"),
    ("Additional Protocol I", "1977", "International armed conflicts", "1125 UNTS 3"),
    ("Additional Protocol II", "1977", "Non-international armed conflicts", "1125 UNTS 609"),
    ("Additional Protocol III", "2005", "Additional distinctive emblem", "2404 UNTS 261"),
    ("Hague Regulations", "1907", "Laws and customs of war on land", "Annex to Hague Convention IV"),
    ("Convention on Certain Conventional Weapons", "1980", "CCW framework and protocols", "1342 UNTS 137"),
    ("Ottawa Treaty", "1997", "Anti-Personnel Mine Ban Convention", "2056 UNTS 211"),
]

_CUSTOMARY_IHL_URL = "https://ihl-databases.icrc.org/en/customary-ihl/v1/rule1"


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
    """Create seed records for IHL treaties and customary IHL."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, len(_IHL_TREATIES))
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    from src.services.remote_sources import chunk_remote_text

    for name, year, scope, unts in _IHL_TREATIES[:effective_max]:
        source_url = f"{_BASE_URL}/en/ihl-treaties/gci-1949"
        text = (
            f"ICRC IHL Database\n"
            f"Treaty: {name} ({year})\n"
            f"Scope: {scope}\n"
            f"UN Treaty Series: {unts}\n"
            f"Official source: {_BASE_URL}"
        ).strip()
        checksum = hashlib.sha256(text.encode()).hexdigest()
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=source_url, checksum=checksum,
            download_key=f"icrc_ihl:{name.replace(' ', '_')[:30]}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "treaty",
                "source_name": "ICRC IHL Databases",
                "jurisdiction": "international",
                "citation": f"{name}, {unts}",
                "source_url": source_url,
                "year": int(year) if year.isdigit() else None,
                "license_note": "ICRC open access",
                "language": "en",
            })
        chunks.extend(doc_chunks)
        time.sleep(0.05)

    events.append({"source": "ICRC IHL Databases", "status": "completed", "chunks": len(chunks)})
    return chunks, events
