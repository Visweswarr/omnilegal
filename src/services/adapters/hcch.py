"""HCCH adapter — Hague Conference on Private International Law.

URL: https://www.hcch.net/en/instruments/conventions
Coverage: Convention texts + status tables (small but irreplaceable).
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE = "https://www.hcch.net"
_LIST = f"{_BASE}/en/instruments/conventions"


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
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0

    try:
        index_html = _http(_LIST).decode("utf-8", errors="replace")
    except Exception as exc:
        return [], [{"status": "error", "reason": f"{type(exc).__name__}: {exc}"}]

    # Convention "full-text" pages
    links = re.findall(
        r'href=["\'](/en/instruments/conventions/full-text/\?cid=[0-9]+)', index_html
    )
    for path in dict.fromkeys(links):
        if items >= effective_max:
            break
        full_url = f"{_BASE}{path}"
        try:
            raw = _http(full_url, timeout=30)
        except Exception:
            continue
        text = _strip(raw)
        if len(text) < 1000:
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
            url=full_url,
            checksum=checksum,
            download_key=f"hcch:{checksum[:16]}",
            quality_gate=quality_gate,
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "hague_convention",
                    "legal_type": "treaty",
                    "source_name": "HCCH (Hague Conference)",
                    "jurisdiction": "international",
                    "court_or_body": "Hague Conference on Private International Law",
                    "license_note": "HCCH open access",
                    "language": "en",
                    "authority_tier": "primary_authority",
                }
            )
        chunks.extend(doc_chunks)
        items += 1
        time.sleep(0.3)

    events.append({"status": "completed", "source": "HCCH", "items": items, "chunks": len(chunks)})
    return chunks, events
