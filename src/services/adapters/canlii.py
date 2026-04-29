"""CanLII API adapter — Canadian case law and legislation (requires API key)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://api.canlii.org/v1"

_SEED_QUERIES = [
    "constitutional rights Charter",
    "criminal law sentencing",
    "immigration asylum",
    "labour employment",
    "privacy data protection",
]


def _api_key() -> str:
    return os.getenv("CANLII_API_KEY", "")


def _search(query: str, language: str = "en", results_per_page: int = 5) -> list[dict[str, Any]]:
    key = _api_key()
    if not key:
        return []
    params = urllib.parse.urlencode({
        "api_key": key,
        "fullText": query,
        "resultCount": str(results_per_page),
    })
    url = f"{_BASE_URL}/caseBrowse/{language}/?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return list(data.get("cases") or data.get("results") or [])[:results_per_page]


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
    """Fetch Canadian case law from CanLII API (requires CANLII_API_KEY)."""
    if not _api_key():
        return [], [{"source": "CanLII", "status": "error", "reason": "CANLII_API_KEY not set"}]

    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            results = _search(query, results_per_page=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            continue

        for item in results:
            case_id = str(item.get("caseId") or item.get("id") or "").strip()
            if not case_id or case_id in seen:
                continue
            seen.add(case_id)
            title = str(item.get("title") or item.get("style") or f"CanLII {case_id}").strip()
            citation = str(item.get("citation") or title).strip()
            db_id = str(item.get("databaseId") or "").strip()
            url = f"https://www.canlii.org/en/{db_id}/doc/{case_id}/" if db_id else "https://www.canlii.org/"
            text = (
                f"CanLII: {title}\n"
                f"Citation: {citation}\n"
                f"Database: {db_id}\n"
                f"Case ID: {case_id}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=url, checksum=checksum,
                download_key=f"canlii:{case_id}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "case_law",
                    "source_name": f"CanLII: {title}",
                    "jurisdiction": "ca",
                    "citation": citation,
                    "source_url": url,
                    "license_note": "CanLII API terms apply",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.15)

    events.append({"source": "CanLII", "status": "completed", "chunks": len(chunks)})
    return chunks, events
