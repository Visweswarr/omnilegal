"""Israel Versa (Cardozo) adapter.

Fetches English translations of Israeli Supreme Court decisions
from the Versa/Cardozo Israeli SC Project.

Phase 4 — optional, lower priority.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

_VERSA_BASE = "https://versa.cardozo.yu.edu"


def _get_html(url: str) -> str:
    """Fetch HTML content."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0 (academic research)",
        "Accept": "text/html",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read(5 * 1024 * 1024)
        content_type = resp.headers.get("Content-Type", "")
        from src.services.remote_sources import parse_downloaded_content
        return parse_downloaded_content(raw, url=url, content_type=content_type)


def _extract_case_links(html_text: str) -> list[dict[str, str]]:
    """Extract case links from the Versa directory page."""
    links: list[dict[str, str]] = []
    # Look for href patterns pointing to case pages
    for match in re.finditer(r'href="(/[^"]*?(?:case|decision|judgment)[^"]*)"', html_text, re.IGNORECASE):
        href = match.group(1)
        if href not in [l["href"] for l in links]:
            links.append({"href": href})
    return links


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 5 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch Israeli SC decisions from Versa/Cardozo.

    This is a lightweight adapter that fetches the directory page
    and then individual case pages. Limited to avoid overloading
    the academic server.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    # Step 1: Fetch the main directory page
    try:
        directory_html = _get_html(_VERSA_BASE)
    except Exception as exc:
        events.append({"status": "error", "reason": f"{type(exc).__name__}: {exc}"})
        return [], events

    # If the directory itself contains useful content (case listings, abstracts)
    if len(directory_html.strip()) > 500:
        text_bytes = len(directory_html.encode("utf-8"))
        if budget.can_store(text_bytes):
            budget.reserve(text_bytes)
            checksum = hashlib.sha256(directory_html.encode("utf-8")).hexdigest()

            from src.services.remote_sources import chunk_remote_text
            dir_chunks = chunk_remote_text(
                record, plan, directory_html,
                url=_VERSA_BASE,
                checksum=checksum,
                download_key=f"versa:directory:{checksum[:16]}",
            )

            for chunk in dir_chunks:
                chunk["metadata"].update({
                    "doc_type": "case_law",
                    "source_name": "Versa - Israeli SC Project (directory)",
                    "jurisdiction": "israel",
                    "citation": "Versa Israeli Supreme Court Project",
                    "license_note": "Academic reuse with attribution",
                    "language": "en",
                })
            chunks.extend(dir_chunks)

    # Step 2: Follow individual case links
    case_links = _extract_case_links(directory_html)
    events.append({"status": "directory_fetched", "case_links_found": len(case_links)})

    items_total = 0
    for link_info in case_links:
        if items_total >= effective_max:
            break

        href = link_info["href"]
        case_url = f"{_VERSA_BASE}{href}" if href.startswith("/") else href

        try:
            case_text = _get_html(case_url)
        except Exception:
            time.sleep(1)
            continue

        if not case_text or len(case_text.strip()) < 200:
            continue

        text_bytes = len(case_text.encode("utf-8"))
        if text_bytes > max_bytes:
            continue
        if not budget.can_store(text_bytes):
            break
        budget.reserve(text_bytes)

        # Try to extract a title from the text
        title_match = re.search(r"(?:HCJ|CA|CrimA|LCA)\s+\d+/\d+", case_text)
        title = title_match.group(0) if title_match else f"Israeli SC Decision ({href.split('/')[-1]})"

        checksum = hashlib.sha256(case_text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, case_text,
            url=case_url,
            checksum=checksum,
            download_key=f"versa:{checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "case_law",
                "source_name": f"Versa: {title}",
                "jurisdiction": "israel",
                "citation": title,
                "license_note": "Academic reuse with attribution (Cardozo/Nevo)",
                "language": "en",
            })

        chunks.extend(doc_chunks)
        items_total += 1
        time.sleep(2)  # Be respectful to academic server

    events.append({
        "status": "completed",
        "source": "Versa (Cardozo Israeli SC Project)",
        "total_cases": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
