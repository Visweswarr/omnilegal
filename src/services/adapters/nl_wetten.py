"""Dutch wetten.overheid.nl adapter — official Dutch legislation."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_SEARCH_URL = "https://wetten.overheid.nl/zoekresultaat.xhtml"
_BASE_URL = "https://wetten.overheid.nl"

_SEED_QUERIES = [
    "Wetboek van Strafrecht",
    "Wetboek van Burgerlijke Rechtsvordering",
    "Grondwet",
    "Algemene wet bestuursrecht",
    "Wet bescherming persoonsgegevens",
]


def _search_wetten(query: str, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"zoekterm": query})
    url = f"{_SEARCH_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "text/html", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read(204800).decode("utf-8", errors="ignore")
    # Extract law titles and links from the search result HTML
    matches = re.findall(r'href="(/BWBR\d+[^"]*)"[^>]*>([^<]+)<', content)
    return [{"url": m[0], "title": m[1].strip()} for m in matches[:limit]]


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
    """Fetch Dutch legislation metadata from wetten.overheid.nl."""
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
            items = _search_wetten(query, limit=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})

        seed_key = f"nl_wetten:{query}"
        if seed_key not in seen:
            seen.add(seed_key)
            source_url = f"{_SEARCH_URL}?{urllib.parse.urlencode({'zoekterm': query})}"
            text_parts = [
                f"Dutch Legislation (wetten.overheid.nl)",
                f"Query: {query}",
                f"Coverage: Dutch Acts, Orders in Council, ministerial regulations",
                f"Source: {_BASE_URL}",
            ]
            for item in items:
                title = str(item.get("title") or "").strip()
                href = str(item.get("url") or "").strip()
                if title:
                    text_parts.append(f"Document: {title}  {_BASE_URL}{href}")
            text = "\n".join(text_parts).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"nl_wetten:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": "wetten.overheid.nl (Dutch Legislation)",
                    "jurisdiction": "nl",
                    "citation": query,
                    "source_url": source_url,
                    "license_note": "Open Government Licence Netherlands",
                    "language": "nl",
                })
            chunks.extend(doc_chunks)
        time.sleep(0.2)

    events.append({"source": "wetten.overheid.nl", "status": "completed", "chunks": len(chunks)})
    return chunks, events
