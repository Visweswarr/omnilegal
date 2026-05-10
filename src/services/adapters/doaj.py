"""DOAJ adapter — searches the Directory of Open Access Journals for legal articles.

DOAJ API is completely free, no auth required. Searches for open-access
legal journal articles. Maps to ``SCHOLARLY_WORKS``.
"""
from __future__ import annotations

import hashlib, json, logging, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_SCHOLARLY_WORKS, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)
_API = "https://doaj.org/api/search/articles"
_QUERIES = [
    "international law",
    "human rights law review",
    "comparative constitutional law",
    "legal theory jurisprudence",
    "criminal law reform",
]


def _search(query: str, page_size: int = 20) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "pageSize": page_size})
    req = urllib.request.Request(f"{_API}/{urllib.parse.quote(query)}?pageSize={page_size}", headers={"Accept": "application/json", "User-Agent": "OmniLegal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")).get("results", [])
    except Exception as exc:
        log.warning("DOAJ search failed: %s — %s", query, exc)
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
        for result in _search(query, page_size=per_q):
            if len(chunks) >= effective_max:
                break
            bibjson = result.get("bibjson", {})
            title = bibjson.get("title", "") or ""
            did = result.get("id", "")
            if did in seen or not title:
                continue
            seen.add(did)
            abstract = bibjson.get("abstract", "") or ""
            year = bibjson.get("year", "")
            journal_title = (bibjson.get("journal", {}) or {}).get("title", "")
            authors = [a.get("name", "") for a in (bibjson.get("author") or [])[:5]]
            ids = bibjson.get("identifier", [])
            doi = next((i.get("id", "") for i in ids if i.get("type") == "doi"), "")
            link = next((l.get("url", "") for l in (bibjson.get("link") or []) if l.get("url")), "")
            text = f"Title: {title}\nAuthors: {', '.join(authors)}\nJournal: {journal_title}\nAbstract: {abstract}\nYear: {year}\nDOI: {doi}"
            cs = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(record, plan, text, url=doi or link, checksum=cs, download_key=f"doaj:{cs[:16]}")
            for c in doc_chunks:
                c["metadata"].update({"doc_type": "commentary", "source_name": "DOAJ", "jurisdiction": "international", "collection": COLLECTION_SCHOLARLY_WORKS, "citation": f"{title} ({year})" if year else title, "source_url": doi or link, "year": int(year) if str(year).isdigit() else None, "license_note": "Open Access (DOAJ)", "language": "en"})
            chunks.extend(doc_chunks)
        time.sleep(0.3)

    return chunks, [{"source": "doaj", "status": "completed", "chunks": len(chunks)}]
