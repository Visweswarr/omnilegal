"""Constitute Project adapter — 200+ constitutions, structured JSON.

Listing API: https://www.constituteproject.org/service/constitutions?lang=en
Doc API:     https://www.constituteproject.org/constitution/<id>.json?lang=en

Each constitution returns a tree of nested `section` nodes; `content` fields hold
the article text. We flatten the tree depth-first into a single document so it
chunks naturally.

Licence: Constitute Project terms — academic re-use; attribution required.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE = "https://www.constituteproject.org"
_LIST_URL = f"{_BASE}/service/constitutions?lang=en"

# Priority country_id substrings — index these first.
_PRIORITY_COUNTRIES = {
    "India", "United_States_of_America", "United_Kingdom", "Russia", "Israel",
    "French", "France", "German", "Italy", "Spain", "Brazil", "South_Africa",
    "Canada", "Australia", "Japan", "China",
}


def _get_json(url: str, timeout: int = 30) -> Any:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "OmniLegalResearch/1.0 (academic legal research)",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _flatten_section(node: Any, lines: list[str], depth: int = 0) -> None:
    """Depth-first walk over the constitution tree producing readable Markdown."""
    if isinstance(node, dict):
        title = node.get("title") or node.get("heading") or ""
        content = node.get("content")
        if title:
            lines.append(f"\n{'#' * min(6, depth + 1)} {title}")
        if isinstance(content, str) and content.strip():
            lines.append(content.strip())
        children = node.get("section") or node.get("sections") or []
        if isinstance(children, list):
            for child in children:
                _flatten_section(child, lines, depth + 1)
    elif isinstance(node, list):
        for item in node:
            _flatten_section(item, lines, depth)


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
    quality_gate: str = "standard",
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if checkpoint is None:
        checkpoint = {}
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 250)

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    try:
        listings = _get_json(_LIST_URL)
    except Exception as exc:
        return [], [{"status": "error", "reason": f"{type(exc).__name__}: {exc}"}]

    if not isinstance(listings, list):
        return [], [{"status": "error", "reason": "unexpected listing payload"}]

    # Filter to in-force, public constitutions; sort priority countries first.
    candidates: list[dict[str, Any]] = [
        c for c in listings
        if isinstance(c, dict) and c.get("in_force") and c.get("public") and c.get("id")
    ]

    def _sort_key(entry: dict[str, Any]) -> tuple[int, int]:
        cid = (entry.get("country_id") or "")
        prio = 0 if any(p in cid for p in _PRIORITY_COUNTRIES) else 1
        year = -1 * int(entry.get("year_enacted") or entry.get("year_revised") or 0)
        return prio, year

    candidates.sort(key=_sort_key)

    items_total = 0
    for entry in candidates:
        if items_total >= effective_max:
            break
        cons_id = entry.get("id") or ""
        country = entry.get("country") or entry.get("country_id") or "Unknown"
        title = entry.get("title") or f"Constitution: {country}"
        title_long = entry.get("title_long") or title
        year = entry.get("year_enacted") or entry.get("year_revised") or 0

        text_url = f"{_BASE}/constitution/{cons_id}.json?lang=en"
        try:
            doc = _get_json(text_url, timeout=30)
        except Exception:
            continue
        document = (doc or {}).get("document") if isinstance(doc, dict) else None
        if not document:
            continue
        lines: list[str] = [f"# {title_long}", f"Country: {country}", f"Year: {year}"]
        _flatten_section(document, lines, depth=0)
        text = "\n".join(line for line in lines if line.strip())
        if len(text) < 600:
            continue
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > max_bytes:
            text = text[: max_bytes // 4]
            text_bytes = len(text.encode("utf-8"))
        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted", "country": country})
            break
        budget.reserve(text_bytes)

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        from src.services.remote_sources import chunk_remote_text

        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=f"{_BASE}/constitution/{cons_id}",
            checksum=checksum,
            download_key=f"constitute:{cons_id}:{checksum[:16]}",
            quality_gate=quality_gate,
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "constitution",
                    "legal_type": "constitutional_text",
                    "source_name": f"Constitute: {title_long}",
                    "jurisdiction": country.lower().replace(" ", "_"),
                    "country": country,
                    "country_id": cons_id,
                    "year": year,
                    "citation": title_long,
                    "license_note": "Constitute Project — academic re-use, attribution required",
                    "language": "en",
                    "authority_tier": "primary_authority",
                }
            )
        chunks.extend(doc_chunks)
        items_total += 1
        time.sleep(0.2)

    events.append(
        {"status": "completed", "source": "Constitute Project", "constitutions": items_total, "chunks": len(chunks)}
    )
    return chunks, events
