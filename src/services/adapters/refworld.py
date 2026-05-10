"""Refworld (UNHCR) adapter — global refugee, country-of-origin & legal-policy database.

URL: https://www.refworld.org  (open access; ToS allows non-commercial research)
Density: HIGH — country reports, legal policy, asylum/refugee jurisprudence.
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

_BASE = "https://www.refworld.org"
_SEEDS = [
    "non-refoulement",
    "well-founded fear",
    "internal flight alternative",
    "particular social group",
    "country of origin information",
    "credibility assessment",
    "exclusion clause",
    "stateless",
    "asylum procedure",
    "best interests of the child",
]


def _http(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OmniLegalResearch/1.0 (academic)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _strip(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
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
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()
    items = 0

    for seed in _SEEDS:
        if items >= effective_max:
            break
        url = f"{_BASE}/search?query={urllib.parse.quote(seed)}"
        try:
            html = _http(url).decode("utf-8", errors="replace")
        except Exception as exc:
            events.append({"seed": seed, "status": "error", "reason": str(exc)})
            time.sleep(1)
            continue

        # Doc URLs typically /docid/<id> or /document/<id>
        links = re.findall(r'href=["\'](/(?:docid|document)/[A-Za-z0-9]+(?:\.html)?)', html)
        for path in dict.fromkeys(links)[:25]:
            if items >= effective_max:
                break
            full_url = f"{_BASE}{path}"
            if full_url in seen:
                continue
            seen.add(full_url)
            try:
                raw = _http(full_url, timeout=30)
            except Exception:
                continue
            text = _strip(raw)
            if len(text) < 800:
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
                download_key=f"refworld:{checksum[:16]}",
                quality_gate=quality_gate,
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "refugee_law",
                        "legal_type": "commentary",
                        "source_name": "Refworld (UNHCR)",
                        "jurisdiction": "international",
                        "court_or_body": "UNHCR / various",
                        "license_note": "Refworld open access — UNHCR re-use",
                        "language": "en",
                        "search_query": seed,
                    }
                )
            chunks.extend(doc_chunks)
            items += 1
            time.sleep(0.3)
        time.sleep(0.5)

    events.append({"status": "completed", "source": "Refworld", "items": items, "chunks": len(chunks)})
    return chunks, events
