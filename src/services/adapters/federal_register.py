"""Federal Register API adapter."""
from __future__ import annotations

import hashlib
import json
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

_BASE_URL = "https://www.federalregister.gov/api/v1/articles.json"
_TERMS = ["legal", "regulation", "immigration", "securities", "transportation"]


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
    limit = max_items if max_items > 0 else 25
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    from src.services.remote_sources import chunk_remote_text, parse_downloaded_content

    per_term = max(1, min(5, limit))
    for term in _TERMS:
        if len(chunks) >= limit:
            break
        params = urllib.parse.urlencode({"per_page": str(per_term), "conditions[term]": term, "order": "newest"})
        req = urllib.request.Request(
            f"{_BASE_URL}?{params}",
            headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            events.append({"term": term, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            continue

        for row in data.get("results", []):
            title = row.get("title") or "Federal Register document"
            abstract = row.get("abstract") or ""
            url = row.get("html_url") or row.get("pdf_url") or ""
            text = f"Federal Register document\nTitle: {title}\nAbstract: {abstract}\nURL: {url}"
            if row.get("body_html_url"):
                try:
                    req2 = urllib.request.Request(row["body_html_url"], headers={"User-Agent": "OmniLegalResearchAssistant/1.0"})
                    with urllib.request.urlopen(req2, timeout=20) as resp:
                        raw = resp.read(min(max_bytes, 512_000))
                    parsed = parse_downloaded_content(raw, url=row["body_html_url"], content_type="text/html")
                    if parsed:
                        text = parsed[:8000]
                except Exception:
                    pass
            checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            doc_chunks = chunk_remote_text(
                record,
                plan,
                text,
                url=url,
                checksum=checksum,
                download_key=f"federal_register:{row.get('document_number') or checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "regulation",
                        "source_name": f"Federal Register: {title}",
                        "jurisdiction": "us",
                        "citation": row.get("citation") or title,
                        "source_url": url,
                        "date": row.get("publication_date"),
                        "language": "en",
                    }
                )
            chunks.extend(doc_chunks)

    events.append({"source": "Federal Register", "status": "completed", "chunks": len(chunks)})
    return chunks, events
