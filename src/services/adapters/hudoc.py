"""HUDOC ECHR case-law search adapter (public, no auth required)."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_CASE_LAW_EU, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_QUERY_URL = "https://hudoc.echr.coe.int/app/query/results"

_SEED_QUERIES = [
    "right to fair trial Article 6",
    "right to life Article 2",
    "freedom of expression Article 10",
    "prohibition of torture Article 3",
    "right to liberty Article 5",
]


def _search(query: str, start: int = 0, length: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "query": f"contentsitename=ECHR AND (simpletext=\"{query}\")",
        "select": "sharepointid,Identifier,languagenumber,ECHRDate,doctypebranch,appno,importance,conclusion",
        "sort": "ECHRDate Descending",
        "start": str(start),
        "length": str(length),
    })
    req = urllib.request.Request(
        f"{_QUERY_URL}?{params}",
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or {}
    return list((results.get("Result") or []))


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
    """Fetch ECHR case-law records from HUDOC."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _search(query, length=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            continue

        for item in items:
            cols = item.get("columns") or {}
            identifier = str(cols.get("Identifier") or "").strip()
            if not identifier or identifier in seen:
                continue
            seen.add(identifier)
            app_no = str(cols.get("appno") or "").strip()
            date = str(cols.get("ECHRDate") or "").strip()
            conclusion = str(cols.get("conclusion") or "").strip()
            doc_url = f"https://hudoc.echr.coe.int/eng#{urllib.parse.quote(identifier)}"
            text = (
                f"ECHR: {identifier}\n"
                f"Application no.: {app_no}\n"
                f"Date: {date}\n"
                f"Conclusion: {conclusion}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=doc_url, checksum=checksum,
                download_key=f"hudoc:{identifier}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "case_law",
                    "source_name": f"HUDOC (ECHR): {identifier}",
                    "jurisdiction": "eu",
                    "citation": f"ECtHR, {identifier}, App. No. {app_no}",
                    "source_url": doc_url,
                    "date": date,
                    "license_note": "Open access ECtHR jurisprudence",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.15)

    events.append({"source": "HUDOC", "status": "completed", "chunks": len(chunks)})
    return chunks, events
