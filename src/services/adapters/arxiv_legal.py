"""arXiv + ACL Anthology adapter — fetches Legal NLP papers.

Uses the arXiv Atom API to search for papers in cs.CL / cs.AI that
relate to legal NLP. Maps to ``LEGAL_NLP_PAPERS``.
"""
from __future__ import annotations

import hashlib, logging, re, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_LEGAL_NLP_PAPERS, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)
_ARXIV_API = "http://export.arxiv.org/api/query"
_QUERIES = [
    "legal NLP",
    "court judgment prediction",
    "legal document summarization",
    "statute interpretation language model",
    "legal named entity recognition",
]


def _extract_entries(xml: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for block in re.findall(r"<entry>(.*?)</entry>", xml, re.DOTALL):
        title = re.search(r"<title>(.*?)</title>", block, re.DOTALL)
        summary = re.search(r"<summary>(.*?)</summary>", block, re.DOTALL)
        pub = re.search(r"<published>(.*?)</published>", block)
        arxiv_id = re.search(r"<id>(.*?)</id>", block)
        authors = re.findall(r"<name>(.*?)</name>", block)
        entries.append({
            "title": " ".join((title.group(1) if title else "").split()),
            "summary": " ".join((summary.group(1) if summary else "").split()),
            "published": (pub.group(1) if pub else "")[:10],
            "id": (arxiv_id.group(1) if arxiv_id else ""),
            "authors": ", ".join(authors[:5]),
        })
    return entries


def _search(query: str, max_results: int = 20) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({
        "search_query": f"all:{query} AND (cat:cs.CL OR cat:cs.AI)",
        "sortBy": "relevance", "max_results": max_results,
    })
    req = urllib.request.Request(f"{_ARXIV_API}?{params}", headers={"User-Agent": "OmniLegal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return _extract_entries(resp.read().decode("utf-8"))
    except Exception as exc:
        log.warning("arXiv search failed: %s — %s", query, exc)
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
        for entry in _search(query, max_results=per_q):
            if len(chunks) >= effective_max:
                break
            aid = entry["id"]
            if aid in seen:
                continue
            seen.add(aid)
            title, summary = entry["title"], entry["summary"]
            if not summary:
                continue
            year_str = entry["published"][:4]
            text = f"Title: {title}\nAuthors: {entry['authors']}\nAbstract: {summary}\nDate: {entry['published']}\narXiv: {aid}"
            cs = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(record, plan, text, url=aid, checksum=cs, download_key=f"arxiv:{cs[:16]}")
            for c in doc_chunks:
                c["metadata"].update({"doc_type": "commentary", "source_name": "arXiv", "jurisdiction": "international", "collection": COLLECTION_LEGAL_NLP_PAPERS, "citation": f"{title} ({year_str})", "source_url": aid, "year": int(year_str) if year_str.isdigit() else None, "license_note": "arXiv (CC-BY / open access)", "language": "en"})
            chunks.extend(doc_chunks)
        time.sleep(3.0)  # arXiv rate limit: 1 req/3s

    return chunks, [{"source": "arxiv_legal", "status": "completed", "chunks": len(chunks)}]
