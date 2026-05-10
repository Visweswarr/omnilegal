"""OpenAlex adapter — searches the OpenAlex REST API for legal scholarly works.

OpenAlex is completely free with no auth required (polite pool with mailto).
Searches for works matching the Law concept (C138885662) and returns
title + abstract + citation metadata.

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

from src.config import COLLECTION_SCHOLARLY_WORKS, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)

_API_BASE = "https://api.openalex.org/works"
_USER_AGENT = "OmniLegalResearchAssistant/1.0 (mailto:omnilegal@research.dev)"

# OpenAlex concept ID for "Law"
_LAW_CONCEPT = "C138885662"

_SEARCH_QUERIES = [
    "international law treaty interpretation",
    "human rights constitutional law",
    "legal NLP natural language processing",
    "comparative law jurisdiction",
    "public international law state responsibility",
]


def _api_request(query: str, per_page: int = 25, page: int = 1) -> list[dict[str, Any]]:
    """Query OpenAlex works API and return parsed results."""
    params = urllib.parse.urlencode({
        "search": query,
        "filter": f"concepts.id:{_LAW_CONCEPT},has_abstract:true",
        "sort": "cited_by_count:desc",
        "per_page": per_page,
        "page": page,
    })
    req = urllib.request.Request(
        f"{_API_BASE}?{params}",
        headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("results", [])
    except Exception as exc:
        log.warning("OpenAlex query failed: %s — %s", query, exc)
        return []


def _abstract_from_inverted(inverted_index: dict[str, list[int]] | None) -> str:
    """Reconstruct abstract text from OpenAlex's inverted index format."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort(key=lambda x: x[0])
    return " ".join(w for _, w in word_positions)


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
    """Fetch legal scholarly works from OpenAlex and return (chunks, events)."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    items_per_query = max(1, effective_max // len(_SEARCH_QUERIES))

    for query in _SEARCH_QUERIES:
        results = _api_request(query, per_page=items_per_query)
        for work in results:
            if len(chunks) >= effective_max:
                break
            openalex_id = work.get("id", "")
            if openalex_id in seen_ids:
                continue
            seen_ids.add(openalex_id)

            title = work.get("title", "") or ""
            abstract = _abstract_from_inverted(work.get("abstract_inverted_index"))
            if not abstract and not title:
                continue

            doi = work.get("doi", "") or ""
            year = work.get("publication_year")
            cited_by = work.get("cited_by_count", 0)
            source_info = work.get("primary_location", {}) or {}
            journal = (source_info.get("source") or {}).get("display_name", "")

            concepts = [c.get("display_name", "") for c in (work.get("concepts") or [])[:5]]

            text = (
                f"Title: {title}\n"
                f"Abstract: {abstract}\n"
                f"Journal: {journal}\n"
                f"Year: {year or 'unknown'}\n"
                f"DOI: {doi}\n"
                f"Citations: {cited_by}\n"
                f"Concepts: {', '.join(concepts)}"
            ).strip()

            checksum = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=doi or openalex_id,
                checksum=checksum,
                download_key=f"openalex:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "commentary",
                    "source_name": "OpenAlex",
                    "jurisdiction": "international",
                    "collection": COLLECTION_SCHOLARLY_WORKS,
                    "citation": f"{title} ({year})" if year else title,
                    "source_url": doi or openalex_id,
                    "year": int(year) if year else None,
                    "license_note": "CC0 (OpenAlex metadata)",
                    "language": "en",
                    "cited_by_count": cited_by,
                    "openalex_id": openalex_id,
                })
            chunks.extend(doc_chunks)
        time.sleep(0.2)  # polite rate limiting

    events.append({"source": "openalex", "status": "completed", "chunks": len(chunks)})
    return chunks, events
