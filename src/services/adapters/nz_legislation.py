"""New Zealand Legislation API adapter (public, subject to NZ Legislation API terms)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://api.legislation.govt.nz/v1"

_SEED_QUERIES = [
    "Crimes Act",
    "Immigration Act",
    "Resource Management Act",
    "Bill of Rights Act",
    "Privacy Act",
]


def _search(query: str, count: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "count": str(count)})
    url = f"{_BASE_URL}/legislation?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("feed") or data.get("items") or (data if isinstance(data, list) else []))[:count]


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
    """Fetch New Zealand legislation from the official Legislation API."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        items: list[dict[str, Any]] = []
        try:
            items = _search(query, count=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})

        seed_key = f"nz_legislation:{query}"
        if seed_key not in seen:
            seen.add(seed_key)
            source_url = f"https://www.legislation.govt.nz/"
            item_titles = [str(i.get("title") or "").strip() for i in items if i.get("title")]
            text = (
                f"New Zealand Legislation\n"
                f"Query: {query}\n"
                f"Coverage: New Zealand Acts, regulations, and secondary legislation\n"
                f"Official source: {source_url}"
                + ("\nDocuments: " + "; ".join(item_titles[:5]) if item_titles else "")
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"nz_legislation:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": "New Zealand Legislation",
                    "jurisdiction": "nz",
                    "citation": query,
                    "source_url": source_url,
                    "license_note": "NZ Crown copyright; NZ Legislation API terms apply",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
        time.sleep(0.15)

    events.append({"source": "NZ Legislation API", "status": "completed", "chunks": len(chunks)})
    return chunks, events
