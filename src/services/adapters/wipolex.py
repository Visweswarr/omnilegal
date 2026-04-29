"""WIPO Lex adapter — intellectual property national laws and treaties."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://www.wipo.int/wipolex/en"

# Seed: major IP treaties accessible via WIPO Lex
_SEED_TREATIES = [
    ("TRIPS Agreement", "WTO", "Trade-Related Aspects of Intellectual Property Rights", "1994"),
    ("Berne Convention", "WIPO", "Protection of Literary and Artistic Works", "1886"),
    ("Paris Convention", "WIPO", "Protection of Industrial Property", "1883"),
    ("Patent Cooperation Treaty", "WIPO", "International patent filing", "1970"),
    ("Madrid Agreement (marks)", "WIPO", "International registration of marks", "1891"),
    ("WIPO Copyright Treaty", "WIPO", "Digital copyright protection", "1996"),
    ("Rome Convention", "WIPO/ILO/UNESCO", "Protection of performers, producers, broadcasters", "1961"),
]


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
    """Create seed records for key IP treaties from WIPO Lex."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, len(_SEED_TREATIES))
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    from src.services.remote_sources import chunk_remote_text

    for name, admin_body, description, year in _SEED_TREATIES[:effective_max]:
        source_url = f"{_BASE_URL}/treaties"
        text = (
            f"WIPO Lex — International IP Treaty\n"
            f"Treaty: {name} ({year})\n"
            f"Administered by: {admin_body}\n"
            f"Description: {description}\n"
            f"Official source: {source_url}"
        ).strip()
        checksum = hashlib.sha256(text.encode()).hexdigest()
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=source_url, checksum=checksum,
            download_key=f"wipolex:{name.replace(' ', '_')[:30]}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "treaty",
                "source_name": "WIPO Lex",
                "jurisdiction": "international",
                "citation": f"{name} ({year})",
                "source_url": source_url,
                "year": int(year) if year.isdigit() else None,
                "license_note": "WIPO open access",
                "language": "en",
            })
        chunks.extend(doc_chunks)
        time.sleep(0.05)

    events.append({"source": "WIPO Lex", "status": "completed", "chunks": len(chunks)})
    return chunks, events
