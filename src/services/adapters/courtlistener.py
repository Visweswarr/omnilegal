"""CourtListener REST API v4 adapter.

Fetches US federal/state court opinions via the CourtListener API.
Requires COURTLISTENER_TOKEN in .env.

Flow:
  1. Search via /api/rest/v4/search/?type=o  → get cluster results
  2. For each result, get opinion IDs from the 'opinions' field
  3. Fetch full opinion text via /api/rest/v4/opinions/{id}/

API docs: https://www.courtlistener.com/help/api/rest/
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

from src.config import COURTLISTENER_TOKEN, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE


# ── Keyword seeds for international-law-relevant US cases ────────────────
_SEARCH_QUERIES = [
    "international law",
    "humanitarian intervention",
    "treaty interpretation",
    "use of force",
    "human rights",
    "diplomatic immunity",
    "jus cogens",
    "criminal procedure",
    "right to counsel",
    "consular notification",
    "traffic stop driving license",
]

_BASE_URL = "https://www.courtlistener.com/api/rest/v4"
_OPINIONS_SEARCH = f"{_BASE_URL}/search/"


def _headers() -> dict[str, str]:
    h = {
        "User-Agent": "OmniLegalResearchAssistant/1.0 (academic legal research)",
        "Accept": "application/json",
    }
    if COURTLISTENER_TOKEN:
        h["Authorization"] = f"Token {COURTLISTENER_TOKEN}"
    return h


def _get_json(url: str) -> dict[str, Any]:
    """GET a URL and return parsed JSON."""
    req = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_opinion_text(opinion_id: int) -> str:
    """Fetch the full text of a single opinion by ID."""
    url = f"{_BASE_URL}/opinions/{opinion_id}/"
    try:
        data = _get_json(url)
    except Exception:
        return ""

    # Try text fields in order of preference
    for field in ["plain_text", "html_with_citations", "html", "xml_harvard"]:
        val = data.get(field)
        if val and isinstance(val, str) and len(val.strip()) > 200:
            # Strip HTML/XML tags if present
            if "<" in val and ">" in val:
                val = re.sub(r"<[^>]+>", " ", val)
                val = " ".join(val.split())
            return val.strip()
    return ""


def _extract_citations(result: dict[str, Any]) -> list[str]:
    """Extract citation strings from a search result."""
    cites = []
    for cite_obj in result.get("citation", []) or []:
        if isinstance(cite_obj, dict):
            cite_str = cite_obj.get("cite", "") or cite_obj.get("volume", "")
            if cite_str:
                cites.append(str(cite_str))
        elif isinstance(cite_obj, str):
            cites.append(cite_obj)
    return cites


def _result_to_metadata(result: dict[str, Any], query: str) -> dict[str, Any]:
    """Build normalized metadata from a CourtListener search result."""
    case_name = result.get("caseName") or result.get("case_name") or "Unknown"
    date_filed = result.get("dateFiled") or result.get("date_filed") or ""
    court = result.get("court") or ""
    court_id = result.get("court_id") or ""
    absolute_url = result.get("absolute_url") or ""
    docket_number = result.get("docketNumber") or result.get("docket_number") or ""
    citations = _extract_citations(result)

    year = None
    if date_filed:
        year_match = re.search(r"(18|19|20)\d{2}", str(date_filed))
        if year_match:
            year = int(year_match.group(0))

    return {
        "source_name": f"CourtListener: {case_name}",
        "jurisdiction": "us",
        "doc_type": "case_law",
        "year": year,
        "date_filed": date_filed,
        "court": court or court_id,
        "docket_number": docket_number,
        "case_name": case_name,
        "citation": citations[0] if citations else f"{case_name} ({date_filed[:4] if date_filed else ''})",
        "citations_list": citations,
        "source_url": f"https://www.courtlistener.com{absolute_url}" if absolute_url else "",
        "search_query": query,
        "license_note": "Public domain (US government work)",
        "private_public": "public",
        "language": "en",
        "translation_status": "original",
    }


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
    """Fetch opinions from CourtListener API.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}
    if not COURTLISTENER_TOKEN:
        return [], [{"status": "error", "reason": "COURTLISTENER_TOKEN not set"}]

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_total = 0
    seen_opinion_ids: set[int] = set()

    for query in _SEARCH_QUERIES:
        if items_total >= effective_max:
            break

        params = urllib.parse.urlencode({
            "q": query,
            "type": "o",
            "order_by": "score desc",
            "stat_Precedential": "on",
        })
        url = f"{_OPINIONS_SEARCH}?{params}"

        try:
            data = _get_json(url)
        except Exception as exc:
            events.append({
                "query": query, "status": "error",
                "reason": f"{type(exc).__name__}: {exc}",
            })
            time.sleep(1)
            continue

        results = data.get("results", [])
        if not results:
            events.append({"query": query, "status": "no_results"})
            time.sleep(0.5)
            continue

        query_opinions_fetched = 0
        for result in results:
            if items_total >= effective_max:
                break

            # Get opinion IDs from the search result
            opinions_list = result.get("opinions", [])
            opinion_ids = []
            for op in opinions_list:
                if isinstance(op, dict):
                    op_id = op.get("id")
                    if op_id:
                        opinion_ids.append(int(op_id))
                elif isinstance(op, (int, str)):
                    opinion_ids.append(int(op))

            if not opinion_ids:
                # Try cluster_id as fallback
                cluster_id = result.get("cluster_id")
                if cluster_id:
                    opinion_ids = [int(cluster_id)]

            for opinion_id in opinion_ids:
                if opinion_id in seen_opinion_ids:
                    continue
                if items_total >= effective_max:
                    break
                seen_opinion_ids.add(opinion_id)

                # Fetch the full opinion text
                text = _fetch_opinion_text(opinion_id)
                if not text or len(text) < 200:
                    # Use snippet as fallback
                    snippet = ""
                    for op in opinions_list:
                        if isinstance(op, dict):
                            s = op.get("snippet", "")
                            if s:
                                snippet = re.sub(r"<[^>]+>", " ", s)
                                snippet = " ".join(snippet.split())
                    if snippet and len(snippet) > 100:
                        text = snippet
                    else:
                        continue

                # Check budget
                text_bytes = len(text.encode("utf-8"))
                if text_bytes > max_bytes:
                    continue
                if not budget.can_store(text_bytes):
                    events.append({"status": "budget_exhausted", "query": query})
                    break
                budget.reserve(text_bytes)

                metadata = _result_to_metadata(result, query)
                checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

                from src.services.remote_sources import chunk_remote_text
                opinion_chunks = chunk_remote_text(
                    record, plan, text,
                    url=metadata.get("source_url") or url,
                    checksum=checksum,
                    download_key=f"courtlistener:{opinion_id}:{checksum[:16]}",
                )

                for chunk in opinion_chunks:
                    chunk["metadata"].update({
                        "case_name": metadata["case_name"],
                        "court": metadata["court"],
                        "date_filed": metadata["date_filed"],
                        "year": metadata["year"],
                        "docket_number": metadata["docket_number"],
                        "citations_list": metadata["citations_list"],
                        "doc_type": "case_law",
                        "opinion_id": opinion_id,
                    })

                chunks.extend(opinion_chunks)
                items_total += 1
                query_opinions_fetched += 1
                time.sleep(0.5)  # Rate limiting

        events.append({
            "query": query, "status": "fetched",
            "results_in_page": len(results),
            "opinions_fetched": query_opinions_fetched,
            "total_so_far": items_total,
        })
        time.sleep(0.3)

    events.append({
        "status": "completed",
        "source": "CourtListener",
        "total_opinions": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
