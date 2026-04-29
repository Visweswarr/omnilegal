"""GovInfo API adapter.

Fetches US federal court opinions and legislation from the GovInfo API
(api.govinfo.gov) using the GOVINFO_API_KEY.

Collections targeted:
  - USCOURTS (federal court opinions)
  - PLAW (public laws)
  - USCODE (US Code)

API docs: https://api.govinfo.gov/docs/
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import GOVINFO_API_KEY, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

_BASE_URL = "https://api.govinfo.gov"

# Target the most relevant GovInfo collections
_COLLECTIONS = [
    ("USCOURTS", "case_law"),
    ("PLAW", "statute"),
    ("USCODE", "statute"),
    ("BILLS", "legislation"),
]


def _api_url(path: str, **params: str) -> str:
    """Build a GovInfo API URL with the API key."""
    params["api_key"] = GOVINFO_API_KEY
    qs = urllib.parse.urlencode(params)
    return f"{_BASE_URL}{path}?{qs}"


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_collection_items(
    collection_code: str,
    doc_type: str,
    *,
    max_items: int,
    budget: Any,
    max_bytes: int,
    record: Any,
    plan: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch items from one GovInfo collection."""
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    # Step 1: List packages in collection
    url = _api_url(
        f"/collections/{collection_code}/2020-01-01T00:00:00Z",
        pageSize="20",
        offsetMark="*",
    )

    try:
        data = _get_json(url)
    except Exception as exc:
        events.append({
            "collection": collection_code, "status": "error",
            "reason": f"{type(exc).__name__}: {exc}",
        })
        return chunks, events

    packages = data.get("packages", [])
    if not packages:
        events.append({"collection": collection_code, "status": "no_packages"})
        return chunks, events

    items_ingested = 0
    for pkg in packages:
        if items_ingested >= max_items:
            break

        package_id = pkg.get("packageId", "")
        package_link = pkg.get("packageLink", "")
        title = pkg.get("title", package_id)
        date_issued = pkg.get("dateIssued", "")

        if not package_link:
            continue

        # Step 2: Get package summary (which has the content links)
        summary_url = f"{package_link}?api_key={urllib.parse.quote(GOVINFO_API_KEY)}"
        try:
            summary = _get_json(summary_url)
        except Exception as exc:
            events.append({
                "package": package_id, "status": "summary_error",
                "reason": f"{type(exc).__name__}: {exc}",
            })
            time.sleep(0.5)
            continue

        # Step 3: Get the text content (prefer htm → txt → xml)
        download_url = None
        for fmt_key in ["txtLink", "htmLink", "xmlLink"]:
            link = summary.get("download", {}).get(fmt_key)
            if link:
                download_url = f"{link}?api_key={urllib.parse.quote(GOVINFO_API_KEY)}"
                break

        if not download_url:
            # Try to get content from the package summary text fields
            text = summary.get("collectionName", "") + "\n" + title
            if len(text.strip()) < 100:
                continue
        else:
            try:
                req = urllib.request.Request(download_url, headers={
                    "User-Agent": "OmniLegalResearchAssistant/1.0",
                })
                with urllib.request.urlopen(req, timeout=30) as resp:
                    raw = resp.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        continue
                    content_type = resp.headers.get("Content-Type", "")

                if not budget.can_store(len(raw)):
                    events.append({"status": "budget_exhausted"})
                    break
                budget.reserve(len(raw))

                from src.services.remote_sources import parse_downloaded_content
                text = parse_downloaded_content(raw, url=download_url, content_type=content_type)
            except Exception as exc:
                events.append({
                    "package": package_id, "status": "download_error",
                    "reason": f"{type(exc).__name__}: {exc}",
                })
                time.sleep(0.5)
                continue

        if not text or len(text.strip()) < 100:
            continue

        # Extract year
        year = None
        if date_issued:
            year_match = re.search(r"(19|20)\d{2}", str(date_issued))
            if year_match:
                year = int(year_match.group(0))

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=download_url or summary_url,
            checksum=checksum,
            download_key=f"govinfo:{package_id}:{checksum[:16]}",
        )

        # Enrich metadata
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": doc_type,
                "source_name": f"GovInfo: {title}",
                "jurisdiction": "us",
                "year": year,
                "date": date_issued,
                "govinfo_package_id": package_id,
                "govinfo_collection": collection_code,
                "citation": title,
                "license_note": "Public domain (17 U.S.C. §105)",
                "language": "en",
            })

        chunks.extend(doc_chunks)
        items_ingested += 1
        time.sleep(0.3)  # Rate limiting

    events.append({
        "collection": collection_code,
        "status": "completed",
        "packages_available": len(packages),
        "items_ingested": items_ingested,
        "chunks": len(chunks),
    })
    return chunks, events


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
    """Fetch legal documents from GovInfo API.

    Returns (chunks, events).
    """
    if not GOVINFO_API_KEY:
        return [], [{"status": "error", "reason": "GOVINFO_API_KEY not set"}]

    effective_max_per_collection = (max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP) // max(len(_COLLECTIONS), 1)
    all_chunks: list[dict[str, Any]] = []
    all_events: list[dict[str, Any]] = []

    for collection_code, doc_type in _COLLECTIONS:
        chunks, events = _fetch_collection_items(
            collection_code, doc_type,
            max_items=max(effective_max_per_collection, 3),
            budget=budget,
            max_bytes=max_bytes,
            record=record,
            plan=plan,
        )
        all_chunks.extend(chunks)
        all_events.extend(events)

    all_events.append({
        "status": "completed",
        "source": "GovInfo",
        "total_chunks": len(all_chunks),
    })
    return all_chunks, all_events
