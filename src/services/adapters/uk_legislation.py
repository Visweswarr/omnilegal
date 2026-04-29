"""Legislation.gov.uk REST/Atom adapter (free, no auth required)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_STATUTES_UK, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_SEARCH_URL = "https://www.legislation.gov.uk/search"

_SEED_QUERIES = [
    "Human Rights Act 1998",
    "Companies Act 2006",
    "Criminal Justice Act 2003",
    "Equality Act 2010",
    "Data Protection Act 2018",
    "Immigration Act 1971",
]


def _search_json(query: str, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"text": query, "type": "UnitedKingdomPublicGeneralAct"})
    url = f"{_SEARCH_URL}.json?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    items = data if isinstance(data, list) else data.get("items") or data.get("results") or []
    return list(items)[:limit]


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
    """Fetch UK primary legislation metadata from legislation.gov.uk."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 60)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _search_json(query, limit=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            # Fallback: create a seed record from the known title
            items = []
            title = query
            source_url = f"https://www.legislation.gov.uk/"
            text = (
                f"UK Primary Legislation\n"
                f"Title: {title}\n"
                f"Official portal: {source_url}\n"
                f"Coverage: UK primary and secondary legislation as enacted and in force."
            )
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"uk_legislation:{hashlib.md5(title.encode()).hexdigest()[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"Legislation.gov.uk: {title}",
                    "jurisdiction": "gb",
                    "citation": title,
                    "source_url": source_url,
                    "license_note": "Open Government Licence v3.0",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
            seen.add(title)
            continue

        for item in items:
            title = str(item.get("title") or item.get("name") or query).strip()
            if title in seen:
                continue
            seen.add(title)
            uri = str(item.get("uri") or item.get("href") or "").strip()
            source_url = f"https://www.legislation.gov.uk{uri}" if uri.startswith("/") else uri or "https://www.legislation.gov.uk/"
            year = str(item.get("year") or "").strip()
            number = str(item.get("number") or "").strip()
            citation = f"{title}" + (f" {year}" if year else "") + (f" c.{number}" if number else "")
            text = (
                f"UK Primary Legislation\n"
                f"Title: {title}\n"
                f"Year: {year}\n"
                f"Number: {number}\n"
                f"URI: {source_url}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"uk_legislation:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"Legislation.gov.uk: {title}",
                    "jurisdiction": "gb",
                    "citation": citation,
                    "source_url": source_url,
                    "license_note": "Open Government Licence v3.0",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.1)

    events.append({"source": "Legislation.gov.uk", "status": "completed", "chunks": len(chunks)})
    return chunks, events
