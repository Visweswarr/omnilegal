"""FAOLEX adapter — FAO national food, agriculture, and environment legislation."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_SEARCH_URL = "https://www.fao.org/faolex/results/en/c/"

_SEED_TOPICS = [
    ("food safety", "food_safety"),
    ("pesticides regulation", "environment"),
    ("water rights", "water_law"),
    ("land tenure", "agriculture"),
    ("fisheries management", "fisheries"),
]


def _search_faolex(query: str, max_rows: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query": query, "rows": str(max_rows), "wt": "json"})
    url = f"https://www.fao.org/faolex/results/en/c/?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    docs = (data.get("response") or {}).get("docs") or []
    return list(docs)[:max_rows]


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
    """Fetch FAOLEX document metadata for food, agriculture, and environment law."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query, domain in _SEED_TOPICS:
        if len(seen) >= effective_max:
            break
        try:
            docs = _search_faolex(query, max_rows=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            docs = []

        # Always create a topic-level seed even if API fails
        topic_key = f"faolex:{domain}"
        if topic_key not in seen:
            seen.add(topic_key)
            source_url = f"https://www.fao.org/faolex/collection/{domain}/en/"
            text_parts = [
                f"FAOLEX — {query.title()} legislation database",
                f"Domain: {domain}",
                f"Official source: {source_url}",
                "Coverage: National laws and international instruments on food, agriculture, environment, and natural resources.",
            ]
            for doc in docs:
                title = str(doc.get("title") or doc.get("titleOfText") or "").strip()
                if title:
                    country = str(doc.get("country") or "").strip()
                    year = str(doc.get("dateOfText") or doc.get("year") or "").strip()
                    text_parts.append(f"Document: {title} ({country}, {year})")
            text = "\n".join(text_parts).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"faolex:{domain}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "environmental_legislation_metadata",
                    "source_name": "FAOLEX",
                    "jurisdiction": "international",
                    "citation": f"FAOLEX {query.title()} collection",
                    "source_url": source_url,
                    "license_note": "FAO open access",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
        time.sleep(0.2)

    events.append({"source": "FAOLEX", "status": "completed", "chunks": len(chunks)})
    return chunks, events
