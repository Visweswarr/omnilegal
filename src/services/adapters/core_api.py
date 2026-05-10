"""CORE API adapter — searches CORE (core.ac.uk) for open-access legal papers.

CORE aggregates 300M+ open-access research outputs. Uses the v3 API.
Requires a free API key (``CORE_API_KEY`` env var) for higher rate limits,
but works without auth at reduced throughput.

Maps to ``SCHOLARLY_WORKS`` collection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_SCHOLARLY_WORKS, CORE_API_KEY, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)

_API_BASE = "https://api.core.ac.uk/v3"
_USER_AGENT = "OmniLegalResearchAssistant/1.0"

_SEARCH_QUERIES = [
    "international law human rights",
    "legal informatics natural language processing",
    "constitutional law comparative",
    "treaty interpretation state sovereignty",
    "criminal justice legal reform",
]


def _api_search(query: str, limit: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "limit": limit})
    url = f"{_API_BASE}/search/works?{params}"
    headers: dict[str, str] = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    if CORE_API_KEY:
        headers["Authorization"] = f"Bearer {CORE_API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", [])
    except Exception as exc:
        log.warning("CORE API search failed: %s — %s", query, exc)
        return []


def fetch(
    record: Any, plan: Any, *, root: Path, budget: Any,
    max_items: int = 0, max_bytes: int = 10 * 1024 * 1024,
    mode: str = "licensed", checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True, ingest: bool = False, **_kw: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)
    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    per_q = max(1, effective_max // len(_SEARCH_QUERIES))

    for query in _SEARCH_QUERIES:
        for work in _api_search(query, limit=per_q):
            if len(chunks) >= effective_max:
                break
            cid = str(work.get("id", ""))
            if cid in seen:
                continue
            seen.add(cid)
            title = work.get("title", "") or ""
            abstract = work.get("abstract", "") or ""
            if not abstract and not title:
                continue
            year = work.get("yearPublished")
            doi = work.get("doi", "") or ""
            authors = [a.get("name", "") for a in (work.get("authors") or [])[:5]]
            text = f"Title: {title}\nAuthors: {', '.join(authors)}\nAbstract: {abstract}\nYear: {year or 'unknown'}\nDOI: {doi}"
            checksum = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(record, plan, text, url=doi or f"https://core.ac.uk/works/{cid}", checksum=checksum, download_key=f"core:{checksum[:16]}")
            for c in doc_chunks:
                c["metadata"].update({"doc_type": "commentary", "source_name": "CORE", "jurisdiction": "international", "collection": COLLECTION_SCHOLARLY_WORKS, "citation": f"{title} ({year})" if year else title, "source_url": doi, "year": int(year) if year else None, "license_note": "Open Access (CORE)", "language": "en", "core_id": cid})
            chunks.extend(doc_chunks)
        time.sleep(0.3)
    events.append({"source": "core_api", "status": "completed", "chunks": len(chunks)})
    return chunks, events
