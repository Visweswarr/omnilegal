"""RusLawOD adapter (Russian federal legislation corpus).

Downloads the RusLawOD dataset from GitHub or HuggingFace.
Dataset: irlspbru/RusLawOD — Akoma-Ntoso-inspired XML of Russian federal law.

Phase 4 — optional, lower priority.
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

from src.config import HF_TOKEN, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

_HF_DATASET = "irlspbru/RusLawOD"
_GITHUB_API = "https://api.github.com/repos/irlcode/RusLawOD/releases/latest"
_TARGETED_ACTS = [
    {
        "match": ["кодекс российской федерации об административных правонарушениях", "коап", "коап рф"],
        "english_title": "Code of Administrative Offences of the Russian Federation",
        "keyword_aliases": "administrative offence, administrative fine, traffic offence, driving without licence",
    },
    {
        "match": ["уголовно-процессуальный кодекс российской федерации", "упк", "упк рф"],
        "english_title": "Criminal Procedure Code of the Russian Federation",
        "keyword_aliases": "criminal procedure, detention, defence counsel, interpreter, suspect rights",
    },
    {
        "match": ["о безопасности дорожного движения", "196-фз", "дорожного движения"],
        "english_title": "Federal Law on Road Traffic Safety",
        "keyword_aliases": "road traffic safety, driving licence, foreign driving licence, international driving permit",
    },
    {
        "match": ["о полиции", "3-фз"],
        "english_title": "Federal Law on Police",
        "keyword_aliases": "police powers, detention, identity check, delivery to police station",
    },
]


def _targeted_enrichment(title: str, text: str) -> dict[str, str]:
    haystack = f"{title}\n{text}".lower()
    for hint in _TARGETED_ACTS:
        if any(token in haystack for token in hint["match"]):
            return {
                "english_title": hint["english_title"],
                "keyword_aliases": hint["keyword_aliases"],
            }
    return {}


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
    """Fetch Russian legislation from RusLawOD via HuggingFace streaming.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    try:
        from datasets import load_dataset
        dataset = load_dataset(_HF_DATASET, split="train", streaming=True, token=HF_TOKEN or None)
    except Exception as exc:
        events.append({"status": "error", "reason": f"Could not load HF dataset: {exc}"})
        return [], events

    items_total = 0
    for idx, row in enumerate(dataset):
        if items_total >= effective_max:
            break

        text = json.dumps(row, ensure_ascii=False) if isinstance(row, dict) else str(row)

        # Extract meaningful fields
        if isinstance(row, dict):
            title = row.get("title") or row.get("name") or f"Russian Law #{idx}"
            date = row.get("date") or row.get("publication_date") or ""
            doc_text = row.get("text") or row.get("content") or text
        else:
            title = f"Russian Law #{idx}"
            date = ""
            doc_text = text

        if len(doc_text.strip()) < 100:
            continue

        text_bytes = len(doc_text.encode("utf-8"))
        if text_bytes > max_bytes:
            continue
        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted"})
            break
        budget.reserve(text_bytes)

        year = None
        if date:
            year_match = re.search(r"(19|20)\d{2}", str(date))
            if year_match:
                year = int(year_match.group(0))
        enrichment = _targeted_enrichment(title, doc_text)
        source_name = f"RusLawOD: {title}"
        if enrichment.get("english_title"):
            source_name = f"RusLawOD: {enrichment['english_title']} / {title}"

        checksum = hashlib.sha256(doc_text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, doc_text,
            url=f"hf://datasets/{_HF_DATASET}",
            checksum=checksum,
            download_key=f"ruslawod:{checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "statute",
                "source_name": source_name,
                "jurisdiction": "russia",
                "year": year,
                "date": date,
                "citation": title,
                "license_note": "Open; verify LICENSE file before redistribution",
                "language": "ru",
                "english_title": enrichment.get("english_title", ""),
                "keyword_aliases": enrichment.get("keyword_aliases", ""),
            })

        chunks.extend(doc_chunks)
        items_total += 1

    events.append({
        "status": "completed",
        "source": "RusLawOD",
        "total_documents": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
