"""SEC EDGAR submissions adapter."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Any

from src.config import SEC_USER_AGENT

_COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


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
    if not SEC_USER_AGENT:
        return [], [{"source": "SEC EDGAR", "status": "error", "reason": "SEC_USER_AGENT not set"}]
    limit = max_items if max_items > 0 else 25
    try:
        req = urllib.request.Request(
            _COMPANY_TICKERS_URL,
            headers={"Accept": "application/json", "User-Agent": SEC_USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return [], [{"source": "SEC EDGAR", "status": "error", "reason": f"{type(exc).__name__}: {exc}"}]

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    for row in list(data.values())[:limit]:
        cik = str(row.get("cik_str") or "").zfill(10)
        ticker = row.get("ticker") or ""
        title = row.get("title") or ticker or cik
        text = (
            f"SEC EDGAR company metadata\n"
            f"CIK: {cik}\n"
            f"Ticker: {ticker}\n"
            f"Company: {title}\n"
            f"Submissions endpoint: https://data.sec.gov/submissions/CIK{cik}.json"
        )
        checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=f"https://data.sec.gov/submissions/CIK{cik}.json",
            checksum=checksum,
            download_key=f"sec_edgar:{cik}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "securities_filing_metadata",
                    "source_name": f"SEC EDGAR: {title}",
                    "jurisdiction": "us",
                    "citation": f"CIK {cik}",
                    "source_url": f"https://data.sec.gov/submissions/CIK{cik}.json",
                    "language": "en",
                }
            )
        chunks.extend(doc_chunks)

    return chunks, [{"source": "SEC EDGAR", "status": "completed", "chunks": len(chunks)}]
