"""eCFR API adapter."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

_TITLES_URL = "https://www.ecfr.gov/api/versioner/v1/titles.json"


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
    limit = max_items if max_items > 0 else 50
    try:
        req = urllib.request.Request(
            _TITLES_URL,
            headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return [], [{"source": "eCFR", "status": "error", "reason": f"{type(exc).__name__}: {exc}"}]

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    for title in (data.get("titles") or [])[:limit]:
        title_num = title.get("number")
        title_name = title.get("name") or title.get("latest_issue_date") or f"Title {title_num}"
        text = (
            f"eCFR title metadata\n"
            f"Title {title_num}: {title_name}\n"
            f"Reserved: {title.get('reserved')}\n"
            f"Latest amendment date: {title.get('latest_amended_on')}\n"
            f"Latest issue date: {title.get('latest_issue_date')}"
        )
        checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=_TITLES_URL,
            checksum=checksum,
            download_key=f"ecfr:title:{title_num}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "regulation",
                    "source_name": f"eCFR Title {title_num}: {title_name}",
                    "jurisdiction": "us",
                    "citation": f"Title {title_num} CFR",
                    "source_url": "https://www.ecfr.gov/",
                    "language": "en",
                }
            )
        chunks.extend(doc_chunks)

    return chunks, [{"source": "eCFR", "status": "completed", "chunks": len(chunks)}]
