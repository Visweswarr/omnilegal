"""India Code / API Setu statutory adapter.

India Code does not expose a stable unauthenticated JSON API for every
deployment. This adapter therefore creates normalized statutory source records
from official India Code entry points and fetches public pages when available.
"""
from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path
from typing import Any

_SEED_STATUTES = [
    {
        "title": "Bharatiya Nyaya Sanhita, 2023",
        "citation": "BNS 2023",
        "url": "https://www.indiacode.nic.in/",
        "keywords": "criminal law offences punishment Bharatiya Nyaya Sanhita Section 69",
    },
    {
        "title": "Motor Vehicles Act, 1988",
        "citation": "Motor Vehicles Act 1988",
        "url": "https://www.indiacode.nic.in/",
        "keywords": "driving licence foreign licence international driving permit motor vehicles",
    },
    {
        "title": "Code of Criminal Procedure / Bharatiya Nagarik Suraksha Sanhita",
        "citation": "CrPC / BNSS",
        "url": "https://www.indiacode.nic.in/",
        "keywords": "arrest detention bail criminal procedure rights counsel",
    },
]


def _fetch_page(url: str, max_bytes: int) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "OmniLegalResearchAssistant/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                return ""
            text = raw.decode("utf-8", errors="ignore")
            text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
            text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
            return " ".join(text.split())
    except Exception:
        return ""


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
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    limit = max_items if max_items > 0 else len(_SEED_STATUTES)

    from src.services.remote_sources import chunk_remote_text

    for item in _SEED_STATUTES[:limit]:
        page_text = _fetch_page(item["url"], min(max_bytes, 512_000))
        text = (
            f"Official India Code statutory source seed\n"
            f"Title: {item['title']}\n"
            f"Citation: {item['citation']}\n"
            f"Official portal: {item['url']}\n"
            f"Coverage keywords: {item['keywords']}\n\n"
            f"{page_text[:4000]}"
        ).strip()
        checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        doc_chunks = chunk_remote_text(
            record,
            plan,
            text,
            url=item["url"],
            checksum=checksum,
            download_key=f"india_code:{item['citation']}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "statute",
                    "source_name": f"India Code: {item['title']}",
                    "jurisdiction": "in",
                    "citation": item["citation"],
                    "source_url": item["url"],
                    "license_note": "Official Government of India portal; verify current act text at source URL.",
                    "language": "en",
                }
            )
        chunks.extend(doc_chunks)

    events.append({"source": "India Code", "status": "completed", "chunks": len(chunks)})
    return chunks, events
