"""Australian Federal Register of Legislation adapter (public API, no auth)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://api.prod.legislation.gov.au/v1"

_SEED_QUERIES = [
    "Migration Act",
    "Criminal Code Act",
    "Privacy Act",
    "Australian Consumer Law",
    "Fair Work Act",
    "Customs Act",
]


def _search(query: str, count: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"title": query, "count": str(count)})
    url = f"{_BASE_URL}/legislations?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("legislations") or data.get("items") or data if isinstance(data, list) else [])[:count]


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
    """Fetch Australian Commonwealth legislation from the Federal Register API."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 60)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _search(query, count=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            items = []

        # Seed record even on failure
        if not items:
            seed_key = f"au_legislation:{query}"
            if seed_key not in seen:
                seen.add(seed_key)
                source_url = "https://www.legislation.gov.au/"
                text = (
                    f"Australian Federal Register of Legislation\n"
                    f"Query: {query}\n"
                    f"Coverage: Commonwealth Acts, legislative instruments, and notifiable instruments\n"
                    f"Official source: {source_url}"
                ).strip()
                checksum = hashlib.sha256(text.encode()).hexdigest()
                doc_chunks = chunk_remote_text(
                    record, plan, text,
                    url=source_url, checksum=checksum,
                    download_key=f"au_legislation:{checksum[:16]}",
                )
                for chunk in doc_chunks:
                    chunk["metadata"].update({
                        "doc_type": "statute",
                        "source_name": "Australian Federal Register of Legislation",
                        "jurisdiction": "au",
                        "citation": query,
                        "source_url": source_url,
                        "license_note": "Creative Commons Attribution 4.0",
                        "language": "en",
                    })
                chunks.extend(doc_chunks)
            continue

        for item in items:
            title = str(item.get("title") or item.get("name") or query).strip()
            if title in seen:
                continue
            seen.add(title)
            series_id = str(item.get("seriesId") or item.get("id") or "").strip()
            year = str(item.get("year") or "").strip()
            source_url = (
                f"https://www.legislation.gov.au/Details/{series_id}" if series_id
                else "https://www.legislation.gov.au/"
            )
            text = (
                f"Australian Federal Register of Legislation\n"
                f"Title: {title}\n"
                f"Series ID: {series_id}\n"
                f"Year: {year}\n"
                f"Source: {source_url}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"au_legislation:{series_id or checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"Australian Legislation: {title}",
                    "jurisdiction": "au",
                    "citation": f"{title}{' ' + year if year else ''}",
                    "source_url": source_url,
                    "license_note": "Creative Commons Attribution 4.0",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.1)

    events.append({"source": "Australian Federal Register", "status": "completed", "chunks": len(chunks)})
    return chunks, events
