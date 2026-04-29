"""German open legal data adapter (de.openlegaldata.io, open API)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://de.openlegaldata.io/api/v1"

_SEED_QUERIES = [
    "Strafgesetzbuch",
    "Grundgesetz",
    "Bürgerliches Gesetzbuch",
    "Strafprozessordnung",
    "Arbeitsrecht",
]


def _search(query: str, page_size: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"search": query, "page_size": str(page_size)})
    url = f"{_BASE_URL}/laws/?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("results") or (data if isinstance(data, list) else []))[:page_size]


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
    """Fetch German law metadata from de.openlegaldata.io."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 60)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _search(query, page_size=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            items = []

        seed_key = f"de_open:{query}"
        if not items and seed_key not in seen:
            seen.add(seed_key)
            source_url = f"https://de.openlegaldata.io/"
            text = (
                f"German Open Legal Data\n"
                f"Query: {query}\n"
                f"Coverage: German federal statutes, court decisions, and official legal texts\n"
                f"Source: {source_url}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"de_open:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": "German Open Legal Data",
                    "jurisdiction": "de",
                    "citation": query,
                    "source_url": source_url,
                    "license_note": "Open access German legal data",
                    "language": "de",
                })
            chunks.extend(doc_chunks)

        for item in items:
            title = str(item.get("name") or item.get("title") or query).strip()
            if title in seen:
                continue
            seen.add(title)
            slug = str(item.get("slug") or "").strip()
            source_url = (
                f"https://de.openlegaldata.io/law/{slug}/" if slug
                else "https://de.openlegaldata.io/"
            )
            abbreviation = str(item.get("abbreviation") or "").strip()
            text = (
                f"German law: {title}\n"
                f"Abbreviation: {abbreviation}\n"
                f"Source: {source_url}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"de_open:{slug or checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"German Open Legal Data: {title}",
                    "jurisdiction": "de",
                    "citation": abbreviation or title,
                    "source_url": source_url,
                    "license_note": "Open access German legal data",
                    "language": "de",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.1)

    events.append({"source": "German Open Legal Data", "status": "completed", "chunks": len(chunks)})
    return chunks, events
