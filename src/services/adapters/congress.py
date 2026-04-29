"""Congress.gov API adapter."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import CONGRESS_API_KEY, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://api.congress.gov/v3"


def _get_json(path: str, **params: str) -> dict[str, Any]:
    params["api_key"] = CONGRESS_API_KEY
    url = f"{_BASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "OmniLegalResearchAssistant/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    """Fetch recent bill metadata from Congress.gov.

    Congress.gov is primarily a legislative-tracking API. This adapter ingests
    normalized bill metadata and latest-action summaries; full text can be added
    later through the bill text endpoint for targeted bills.
    """
    if not CONGRESS_API_KEY:
        return [], [{"status": "error", "reason": "CONGRESS_API_KEY not set"}]

    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    try:
        data = _get_json("/bill", limit=str(min(effective_max, 250)), sort="updateDate+desc")
    except Exception as exc:
        return [], [{"status": "error", "reason": f"{type(exc).__name__}: {exc}"}]

    bills = data.get("bills") or []
    for bill in bills[:effective_max]:
        title = str(bill.get("title") or "").strip()
        congress = bill.get("congress")
        bill_type = bill.get("type")
        number = bill.get("number")
        latest = bill.get("latestAction") or {}
        latest_text = latest.get("text") if isinstance(latest, dict) else ""
        update_date = bill.get("updateDate") or bill.get("updateDateIncludingText")
        url = bill.get("url") or ""
        text = (
            f"Congress.gov bill record\n"
            f"Congress: {congress}\n"
            f"Bill: {bill_type} {number}\n"
            f"Title: {title}\n"
            f"Latest action: {latest_text}\n"
            f"Updated: {update_date}\n"
            f"API URL: {url}"
        ).strip()
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        from src.services.remote_sources import chunk_remote_text

        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=url,
            checksum=checksum,
            download_key=f"congress:{congress}:{bill_type}:{number}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "legislation",
                    "source_name": f"Congress.gov: {bill_type} {number}",
                    "jurisdiction": "us",
                    "citation": f"{bill_type} {number}, {congress}th Congress",
                    "source_url": url,
                    "date": update_date,
                    "license_note": "Public domain US legislative metadata",
                    "language": "en",
                }
            )
        chunks.extend(doc_chunks)
        time.sleep(0.15)

    events.append({"source": "Congress.gov", "status": "completed", "items": len(chunks)})
    return chunks, events
