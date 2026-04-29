"""India Supreme Court (AWS Open Data) adapter.

Fetches Indian Supreme Court judgments from the AWS Open Data registry
maintained by Dattam Labs: ~88,000 cases (1950–2025).

S3 bucket is public — no credentials required.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

# The AWS Open Data S3 bucket for Indian SC judgments
_S3_BASE = "https://indian-supreme-court-judgments.s3.ap-south-1.amazonaws.com"
_METADATA_URL = f"{_S3_BASE}/metadata/cases_metadata.json"
_PRIORITY_TERMS = [
    "d.k. basu",
    "joginder kumar",
    "arnesh kumar",
    "arrest",
    "detention",
    "custody",
    "bail",
    "criminal procedure",
    "motor vehicle",
    "driving licence",
    "driving license",
]


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get_text(url: str, max_bytes: int) -> str:
    """Download text content from URL."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(max_bytes)
        content_type = resp.headers.get("Content-Type", "")
        if "json" in content_type.lower():
            return raw.decode("utf-8", errors="replace")
        from src.services.remote_sources import parse_downloaded_content
        return parse_downloaded_content(raw, url=url, content_type=content_type)


def _priority_score(case: dict[str, Any]) -> int:
    haystack = " ".join(
        str(case.get(field, "") or "")
        for field in ["title", "case_name", "petitioner", "respondent", "subject", "keywords"]
    ).lower()
    score = 0
    for idx, term in enumerate(_PRIORITY_TERMS):
        if term in haystack:
            score += max(1, 20 - idx)
    return score


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
    """Fetch Indian SC judgments from AWS Open Data.

    Strategy: Try to get the metadata JSON first, then download
    individual judgment texts. Falls back to listing the S3 bucket
    if metadata is unavailable.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    # Step 1: Try to fetch the metadata index
    cases: list[dict[str, Any]] = []
    try:
        metadata = _get_json(_METADATA_URL)
        if isinstance(metadata, list):
            cases = metadata
        elif isinstance(metadata, dict):
            cases = metadata.get("cases", metadata.get("data", []))
        events.append({"status": "metadata_fetched", "cases_in_index": len(cases)})
    except Exception as exc:
        events.append({"status": "metadata_error", "reason": f"{type(exc).__name__}: {exc}"})

        # Fallback: Try S3 listing for a few recent judgments
        try:
            req = urllib.request.Request(
                f"{_S3_BASE}/?list-type=2&max-keys=50&prefix=judgments/",
                headers={"User-Agent": "OmniLegalResearchAssistant/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                from xml.etree import ElementTree as ET
                xml_root = ET.fromstring(resp.read())
                ns = "http://s3.amazonaws.com/doc/2006-03-01/"
                for content in xml_root.iter(f"{{{ns}}}Contents"):
                    key_elem = content.find(f"{{{ns}}}Key")
                    if key_elem is not None and key_elem.text:
                        cases.append({"key": key_elem.text, "title": key_elem.text.split("/")[-1]})
            events.append({"status": "s3_listing_fallback", "keys": len(cases)})
        except Exception as exc2:
            events.append({"status": "s3_listing_error", "reason": str(exc2)})
            return [], events

    if cases:
        cases = sorted(cases, key=_priority_score, reverse=True)

    # Step 2: Download and ingest case texts
    items_total = 0
    for case in cases[:effective_max * 5]:  # Scan more, but only ingest up to max
        if items_total >= effective_max:
            break

        # Build download URL
        case_key = case.get("key") or case.get("s3_key") or ""
        case_title = case.get("title") or case.get("case_name") or case.get("petitioner", "")
        case_date = case.get("date") or case.get("judgment_date") or ""

        if case_key:
            text_url = f"{_S3_BASE}/{case_key}"
        elif case_title:
            # Search for the file
            text_url = None
        else:
            continue

        if text_url is None:
            continue

        # Download the judgment
        try:
            text = _get_text(text_url, max_bytes)
        except Exception as exc:
            continue

        if not text or len(text.strip()) < 200:
            continue

        text_bytes = len(text.encode("utf-8"))
        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted"})
            break
        budget.reserve(text_bytes)

        # Extract year
        year = None
        if case_date:
            year_match = re.search(r"(19|20)\d{2}", str(case_date))
            if year_match:
                year = int(year_match.group(0))

        title = case_title or case_key.split("/")[-1].replace(".pdf", "").replace("_", " ")
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=text_url,
            checksum=checksum,
            download_key=f"india_sc:{checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "case_law",
                "source_name": f"Indian Supreme Court: {title}",
                "jurisdiction": "indian",
                "year": year,
                "date": case_date,
                "case_name": title,
                "court": "Supreme Court of India",
                "citation": title,
                "license_note": "CC BY 4.0 (AWS Open Data)",
                "language": "en",
            })

        chunks.extend(doc_chunks)
        items_total += 1
        time.sleep(0.2)

    events.append({
        "status": "completed",
        "source": "India SC (AWS Open Data)",
        "total_judgments": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
