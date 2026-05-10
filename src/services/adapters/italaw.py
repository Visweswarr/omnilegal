"""Italaw adapter — investment-treaty arbitration awards.

URL: https://www.italaw.com/  (open access)
Coverage: ICSID, UNCITRAL ad-hoc, ICC, PCA, SCC investment awards.
ToS: free for research and academic use; attribution required.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE = "https://www.italaw.com"


def _http(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OmniLegalResearch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 4 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    quality_gate: str = "standard",
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 80)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0
    seen: set[str] = set()

    # Italaw cases live at /cases/<n>; iterate by id
    for case_id in range(1, 4000):
        if items >= effective_max:
            break
        url = f"{_BASE}/cases/{case_id}"
        if url in seen:
            continue
        seen.add(url)
        try:
            raw = _http(url, timeout=30)
        except Exception:
            continue
        text = _strip(raw)
        if "page not found" in text.lower() or len(text) < 800:
            continue
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > max_bytes:
            text = text[: max_bytes // 4]
            text_bytes = len(text.encode("utf-8"))
        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted"})
            break
        budget.reserve(text_bytes)
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        from src.services.remote_sources import chunk_remote_text

        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=url,
            checksum=checksum,
            download_key=f"italaw:{case_id}:{checksum[:16]}",
            quality_gate=quality_gate,
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "investment_arbitration",
                    "legal_type": "case_law",
                    "source_name": f"Italaw case {case_id}",
                    "jurisdiction": "international",
                    "court_or_body": "ICSID/UNCITRAL/ICC/PCA/SCC",
                    "license_note": "Italaw — academic use, attribution required",
                    "language": "en",
                    "authority_tier": "case_law",
                }
            )
        chunks.extend(doc_chunks)
        items += 1
        time.sleep(0.4)

    events.append({"status": "completed", "source": "Italaw", "items": items, "chunks": len(chunks)})
    return chunks, events
