"""UK Find Case Law adapter (The National Archives).

Fetches UK court judgments via the TNA Find Case Law REST API.
Requires UK_FIND_CASE_LAW_LICENSE_CONFIRMED=1 for computational analysis.

API docs: https://nationalarchives.github.io/ds-find-caselaw-docs/public
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
from xml.etree import ElementTree as ET

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE, REMOTE_LICENSE_GATES

_BASE_URL = "https://caselaw.nationalarchives.gov.uk"
_SEARCH_URL = f"{_BASE_URL}/judgments/search"
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Search terms for international-law-relevant UK cases
_SEARCH_TERMS = [
    "international law",
    "treaty",
    "human rights",
    "diplomatic immunity",
    "extradition",
    "police and criminal evidence arrest detention",
    "road traffic driving licence",
]


def _is_licensed() -> bool:
    """Check if the computational analysis licence is confirmed."""
    return str(REMOTE_LICENSE_GATES.get("UK_FIND_CASE_LAW_LICENSE_CONFIRMED", "")).lower() in {"1", "true", "yes"}


def _get_atom_feed(query: str, page: int = 1) -> ET.Element:
    """Fetch Atom search results."""
    params = urllib.parse.urlencode({"query": query, "page": str(page)})
    url = f"{_SEARCH_URL}?{params}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Accept": "application/atom+xml,application/xml",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    return ET.fromstring(raw)


def _get_judgment_content(uri: str) -> str:
    """Fetch the full text of a judgment in LegalDocML or HTML."""
    # Try data.xml (LegalDocML) first
    for suffix in ["/data.xml", "/data.html", ""]:
        try:
            url = f"{_BASE_URL}{uri}{suffix}"
            req = urllib.request.Request(url, headers={
                "User-Agent": "OmniLegalResearchAssistant/1.0",
                "Accept": "text/html,application/xml",
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read(5 * 1024 * 1024)
                content_type = resp.headers.get("Content-Type", "")
                from src.services.remote_sources import parse_downloaded_content
                text = parse_downloaded_content(raw, url=url, content_type=content_type)
                if len(text.strip()) > 200:
                    return text
        except Exception:
            continue
    return ""


def _parse_atom_entries(root: ET.Element) -> list[dict[str, Any]]:
    """Parse Atom feed entries into document metadata."""
    entries: list[dict[str, Any]] = []
    for entry in root.iter(f"{{{_ATOM_NS}}}entry"):
        title_elem = entry.find(f"{{{_ATOM_NS}}}title")
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else "UK Judgment"

        # Get the URI (link to the judgment)
        uri = ""
        for link in entry.iter(f"{{{_ATOM_NS}}}link"):
            href = link.get("href", "")
            if href:
                uri = href
                break

        # Get date
        updated_elem = entry.find(f"{{{_ATOM_NS}}}updated")
        date = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else ""

        # Get summary
        summary_elem = entry.find(f"{{{_ATOM_NS}}}summary")
        summary = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""

        year = None
        if date:
            year_match = re.search(r"(19|20)\d{2}", date)
            if year_match:
                year = int(year_match.group(0))

        entries.append({
            "title": title,
            "uri": uri,
            "date": date,
            "year": year,
            "summary": summary,
        })
    return entries


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
    """Fetch UK judgments from Find Case Law API.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    if not _is_licensed():
        return [], [{
            "status": "license_required",
            "reason": "Set UK_FIND_CASE_LAW_LICENSE_CONFIRMED=1 after obtaining computational analysis licence",
        }]

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_total = 0

    for query in _SEARCH_TERMS:
        if items_total >= effective_max:
            break

        try:
            atom_root = _get_atom_feed(query)
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": str(exc)})
            time.sleep(1)
            continue

        entries = _parse_atom_entries(atom_root)
        events.append({"query": query, "entries": len(entries)})

        for entry in entries:
            if items_total >= effective_max:
                break

            uri = entry["uri"]
            if not uri:
                continue

            text = _get_judgment_content(uri)
            if not text or len(text) < 200:
                # Use summary as minimal record
                text = f"UK Judgment: {entry['title']}\nDate: {entry['date']}\n\n{entry['summary']}"
                if len(text.strip()) < 100:
                    continue

            text_bytes = len(text.encode("utf-8"))
            if text_bytes > max_bytes:
                continue
            if not budget.can_store(text_bytes):
                events.append({"status": "budget_exhausted"})
                break
            budget.reserve(text_bytes)

            checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

            from src.services.remote_sources import chunk_remote_text
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=f"{_BASE_URL}{uri}",
                checksum=checksum,
                download_key=f"uk_caselaw:{checksum[:16]}",
            )

            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "case_law",
                    "source_name": f"UK Find Case Law: {entry['title']}",
                    "jurisdiction": "uk",
                    "year": entry["year"],
                    "date": entry["date"],
                    "citation": entry["title"],
                    "license_note": "Open Justice Licence (computational analysis licence required)",
                    "language": "en",
                })

            chunks.extend(doc_chunks)
            items_total += 1
            time.sleep(0.5)

    events.append({
        "status": "completed",
        "source": "UK Find Case Law",
        "total_judgments": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
