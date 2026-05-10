"""Tamil Nadu OGD adapter — queries the CKAN API at tn.data.gov.in.

Ingests **metadata and descriptions only** (per design decision: raw
tabular CSV/XLS data is poorly suited for dense vector embeddings).
Targets judiciary and legal-aid datasets. Maps to ``STATUTES_IN``.
"""
from __future__ import annotations

import hashlib, json, logging, time, urllib.parse, urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_STATUTES_IN, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

log = logging.getLogger(__name__)
_API = "https://tn.data.gov.in/api/3/action/package_search"
_QUERIES = ["judiciary", "legal aid", "court", "law", "justice"]


def _search(query: str, rows: int = 20) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({"q": query, "rows": rows})
    req = urllib.request.Request(f"{_API}?{params}", headers={"Accept": "application/json", "User-Agent": "OmniLegal/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return (data.get("result", {}) or {}).get("results", [])
    except Exception as exc:
        log.warning("TN OGD search failed: %s — %s", query, exc)
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
        for pkg in _search(query, rows=per_q):
            if len(chunks) >= effective_max:
                break
            pid = pkg.get("id", "")
            if pid in seen:
                continue
            seen.add(pid)
            title = pkg.get("title", "") or pkg.get("name", "")
            notes = pkg.get("notes", "") or ""
            org = (pkg.get("organization") or {}).get("title", "")
            resources = pkg.get("resources", [])
            resource_names = ", ".join(r.get("name", "") or r.get("format", "") for r in resources[:5])
            # Metadata-only: describe the dataset, don't ingest raw rows
            text = (
                f"Dataset: {title}\n"
                f"Organisation: {org}\n"
                f"Description: {notes}\n"
                f"Resources: {resource_names}\n"
                f"Source: Tamil Nadu Open Government Data Portal"
            ).strip()
            if len(text) < 80:
                continue
            cs = hashlib.sha256(text[:4096].encode()).hexdigest()
            url = f"https://tn.data.gov.in/dataset/{pid}"
            doc_chunks = chunk_remote_text(record, plan, text, url=url, checksum=cs, download_key=f"tn_ogd:{cs[:16]}")
            for c in doc_chunks:
                c["metadata"].update({"doc_type": "statute", "source_name": "TN Open Government Data", "jurisdiction": "in", "collection": COLLECTION_STATUTES_IN, "citation": title, "source_url": url, "year": None, "license_note": "Government Open Data License - India", "language": "en", "metadata_only": True})
            chunks.extend(doc_chunks)
        time.sleep(0.2)

    return chunks, [{"source": "tn_ogd", "status": "completed", "chunks": len(chunks)}]
