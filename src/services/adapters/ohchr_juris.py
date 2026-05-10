"""OHCHR JURIS adapter — UN Treaty Body Jurisprudence.

URL: https://juris.ohchr.org/  (open public access)
Coverage: Decisions of UN Treaty Bodies (HRC, CESCR, CERD, CEDAW, CAT, CRC, CRPD, CMW)
Density: HIGH — international human rights jurisprudence, irreplaceable by other sources.

Strategy: query the public search HTML; we land on lightweight summaries first, only
deep-fetch full views for landmark/recent decisions.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE = "https://juris.ohchr.org"
_SEARCH = f"{_BASE}/search"

# Seed queries — high-density human rights topics
_SEEDS = [
    "torture",
    "right to life",
    "discrimination",
    "freedom of expression",
    "fair trial",
    "minority rights",
    "non-refoulement",
    "indigenous peoples",
    "gender violence",
    "disability",
    "child detention",
    "asylum",
]


def _http(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "OmniLegalResearch/1.0 (academic)", "Accept": "text/html,application/xhtml+xml"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip_html(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;|&amp;|&quot;|&#\d+;", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_decision_links(html: str) -> list[str]:
    return list(
        dict.fromkeys(  # dedupe preserving order
            re.findall(r'href=["\'](?:https?://juris\.ohchr\.org)?(/(?:Search/Detail/|search/detail/|Documents/)[^"\'#?]+)', html)
        )
    )


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
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 120)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = 0

    for seed in _SEEDS:
        if items >= effective_max:
            break
        params = urllib.parse.urlencode({"q": seed, "lang": "en"})
        url = f"{_SEARCH}?{params}"
        try:
            html = _http(url).decode("utf-8", errors="replace")
        except Exception as exc:
            events.append({"seed": seed, "status": "error", "reason": str(exc)})
            time.sleep(1)
            continue
        links = _extract_decision_links(html)
        for path in links[:30]:
            if items >= effective_max:
                break
            full_url = path if path.startswith("http") else f"{_BASE}{path}"
            if full_url in seen:
                continue
            seen.add(full_url)
            try:
                raw = _http(full_url, timeout=30)
            except Exception:
                continue
            text = _strip_html(raw)
            if len(text) < 600:
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
                download_key=f"ohchr:{checksum[:16]}",
                quality_gate=quality_gate,
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "treaty_body_decision",
                        "legal_type": "case_law",
                        "source_name": "OHCHR JURIS",
                        "jurisdiction": "international",
                        "court_or_body": "UN Treaty Body",
                        "license_note": "OHCHR open access; UN re-use",
                        "language": "en",
                        "search_query": seed,
                        "authority_tier": "case_law",
                    }
                )
            chunks.extend(doc_chunks)
            items += 1
            time.sleep(0.3)
        time.sleep(0.5)

    events.append({"status": "completed", "source": "OHCHR JURIS", "items": items, "chunks": len(chunks)})
    return chunks, events
