"""UNCITRAL CLOUT adapter — Case Law on UNCITRAL Texts.

URL: https://uncitral.un.org/en/case_law  (open public)
Density: HIGH — only authoritative international commercial-law case database.
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

_BASE = "https://uncitral.un.org"
_SEARCH = f"{_BASE}/en/case_law"


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
    max_bytes: int = 3 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    quality_gate: str = "standard",
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 200)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0

    for page in range(0, 10):
        if items >= effective_max:
            break
        params = urllib.parse.urlencode({"page": page})
        url = f"{_SEARCH}?{params}"
        try:
            html = _http(url).decode("utf-8", errors="replace")
        except Exception as exc:
            events.append({"page": page, "status": "error", "reason": str(exc)})
            break
        # CLOUT abstract pages: /en/case_law/abstracts/clout/2024/...
        links = re.findall(r'href=["\'](/en/case_law/abstracts/[A-Za-z0-9_/-]+)', html)
        if not links:
            break
        for path in dict.fromkeys(links)[:30]:
            if items >= effective_max:
                break
            full_url = f"{_BASE}{path}"
            try:
                raw = _http(full_url, timeout=30)
            except Exception:
                continue
            text = _strip(raw)
            if len(text) < 500:
                continue
            text_bytes = len(text.encode("utf-8"))
            if text_bytes > max_bytes:
                text = text[: max_bytes // 4]
                text_bytes = len(text.encode("utf-8"))
            if not budget.can_store(text_bytes):
                events.append({"status": "budget_exhausted"})
                return chunks, events
            budget.reserve(text_bytes)
            checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
            from src.services.remote_sources import chunk_remote_text

            doc_chunks = chunk_remote_text(
                record,
                plan,
                text,
                url=full_url,
                checksum=checksum,
                download_key=f"clout:{checksum[:16]}",
                quality_gate=quality_gate,
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "uncitral_case_abstract",
                        "legal_type": "case_law",
                        "source_name": "UNCITRAL CLOUT",
                        "jurisdiction": "international",
                        "court_or_body": "national courts applying UNCITRAL texts",
                        "license_note": "UNCITRAL open access — UN re-use",
                        "language": "en",
                        "authority_tier": "case_law",
                    }
                )
            chunks.extend(doc_chunks)
            items += 1
            time.sleep(0.25)
        time.sleep(0.4)

    events.append({"status": "completed", "source": "UNCITRAL CLOUT", "items": items, "chunks": len(chunks)})
    return chunks, events
