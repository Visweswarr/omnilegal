"""Semantic Scholar adapter — searches the S2 Academic Graph API for legal NLP papers.

No auth required for basic access (100 req/5min). Uses the ``/paper/search``
endpoint filtered for legal NLP topics. Maps to ``LEGAL_NLP_PAPERS``.
"""
from __future__ import annotations

import hashlib, json, logging, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_LEGAL_NLP_PAPERS, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)
_API = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = "title,abstract,year,citationCount,externalIds,authors"
_QUERIES = [
    "legal NLP judgment prediction",
    "legal information extraction named entity recognition",
    "court decision summarization",
    "statute interpretation language model",
    "legal reasoning artificial intelligence",
]


def _search(query: str, limit: int = 20) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"query": query, "limit": limit, "fields": _FIELDS})
    req = urllib.request.Request(f"{_API}?{params}", headers={"Accept": "application/json", "User-Agent": "OmniLegal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")).get("data", [])
    except Exception as exc:
        log.warning("S2 search failed: %s — %s", query, exc)
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
    seen: set[str] = set()
    per_q = max(1, effective_max // len(_QUERIES))

    for query in _QUERIES:
        for paper in _search(query, limit=per_q):
            if len(chunks) >= effective_max:
                break
            pid = paper.get("paperId", "")
            if pid in seen:
                continue
            seen.add(pid)
            title = paper.get("title", "") or ""
            abstract = paper.get("abstract", "") or ""
            if not abstract:
                continue
            year = paper.get("year")
            cited = paper.get("citationCount", 0)
            doi = (paper.get("externalIds") or {}).get("DOI", "")
            authors = [a.get("name", "") for a in (paper.get("authors") or [])[:5]]
            text = f"Title: {title}\nAuthors: {', '.join(authors)}\nAbstract: {abstract}\nYear: {year or 'unknown'}\nCitations: {cited}\nDOI: {doi}"
            cs = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(record, plan, text, url=doi or f"https://api.semanticscholar.org/graph/v1/paper/{pid}", checksum=cs, download_key=f"s2:{cs[:16]}")
            for c in doc_chunks:
                c["metadata"].update({"doc_type": "commentary", "source_name": "Semantic Scholar", "jurisdiction": "international", "collection": COLLECTION_LEGAL_NLP_PAPERS, "citation": f"{title} ({year})" if year else title, "source_url": doi, "year": int(year) if year else None, "license_note": "Semantic Scholar API (free academic use)", "language": "en", "cited_by_count": cited, "s2_paper_id": pid})
            chunks.extend(doc_chunks)
        time.sleep(1.0)  # S2 rate limit: 100 req/5min

    return chunks, [{"source": "semantic_scholar", "status": "completed", "chunks": len(chunks)}]
