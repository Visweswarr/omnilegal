"""Indian Kanoon API adapter."""
from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import INDIAN_KANOON_API_TOKEN, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://api.indiankanoon.org"
_SEARCH_QUERIES = [
    "Bharatiya Nyaya Sanhita Section 69",
    "Motor Vehicles Act driving licence foreign tourist",
    "Supreme Court diplomatic immunity India",
    "Article 21 right to life criminal procedure",
]


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Authorization": f"Token {INDIAN_KANOON_API_TOKEN}",
    }


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _clean_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(html.unescape(text).split())


def _search(query: str, page: int = 0) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"formInput": query, "pagenum": str(page)})
    data = _get_json(f"{_BASE_URL}/search/?{params}")
    return list(data.get("docs") or data.get("results") or [])


def _doc(doc_id: str) -> str:
    try:
        data = _get_json(f"{_BASE_URL}/doc/{urllib.parse.quote(str(doc_id))}/")
    except Exception:
        return ""
    if isinstance(data, dict):
        for key in ("doc", "text", "content"):
            if data.get(key):
                return _clean_text(str(data[key]))
    return _clean_text(str(data))


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
    """Fetch a small, query-seeded Indian Kanoon corpus."""
    if not INDIAN_KANOON_API_TOKEN:
        return [], [{"status": "error", "reason": "INDIAN_KANOON_API_TOKEN not set"}]

    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 25)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    for query in _SEARCH_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            docs = _search(query)
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            continue

        for result in docs:
            if len(seen) >= effective_max:
                break
            doc_id = str(result.get("tid") or result.get("docid") or result.get("id") or "")
            if not doc_id or doc_id in seen:
                continue
            title = _clean_text(str(result.get("title") or result.get("docsource") or f"Indian Kanoon {doc_id}"))
            headline = _clean_text(str(result.get("headline") or result.get("fragment") or ""))
            body = _doc(doc_id)
            text = body if len(body) > len(headline) else headline
            if len(text) < 100:
                text = f"{title}\n{headline}".strip()
            if len(text) < 80:
                continue

            seen.add(doc_id)
            checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            from src.services.remote_sources import chunk_remote_text

            doc_chunks = chunk_remote_text(
                record,
                plan,
                text,
                url=f"https://indiankanoon.org/doc/{doc_id}/",
                checksum=checksum,
                download_key=f"indian_kanoon:{doc_id}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "case_law",
                        "source_name": f"Indian Kanoon: {title}",
                        "jurisdiction": "in",
                        "citation": title,
                        "source_url": f"https://indiankanoon.org/doc/{doc_id}/",
                        "indian_kanoon_doc_id": doc_id,
                        "search_query": query,
                        "license_note": "Indian Kanoon API terms apply",
                        "language": "en",
                    }
                )
            chunks.extend(doc_chunks)
            time.sleep(0.25)

    events.append({"source": "Indian Kanoon", "status": "completed", "documents": len(seen), "chunks": len(chunks)})
    return chunks, events
