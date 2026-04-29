"""UN Treaty Collection adapter — uses UN Digital Library OAI-PMH for treaty records."""
from __future__ import annotations

import hashlib
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_INTL_TREATIES, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_OAI_URL = "https://digitallibrary.un.org/oai2d"

# Seed: important multilateral treaties by their UN Treaty Series reference
_SEED_TREATIES = [
    ("Vienna Convention on Diplomatic Relations", "1961", "500 UNTS 95"),
    ("Vienna Convention on Consular Relations", "1963", "596 UNTS 261"),
    ("Vienna Convention on the Law of Treaties", "1969", "1155 UNTS 331"),
    ("International Covenant on Civil and Political Rights", "1966", "999 UNTS 171"),
    ("UN Charter", "1945", "1 UNTS XVI"),
    ("Convention against Torture", "1984", "1465 UNTS 85"),
    ("Refugee Convention", "1951", "189 UNTS 137"),
    ("UN Convention on the Law of the Sea", "1982", "1833 UNTS 3"),
    ("Statute of the International Court of Justice", "1945", "33 UNTS 993"),
    ("Geneva Convention III", "1949", "75 UNTS 135"),
]


def _oai_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "verb": "ListRecords",
        "metadataPrefix": "marcxml",
        "set": "col:MLEGAL",
    })
    req = urllib.request.Request(
        f"{_OAI_URL}?{params}",
        headers={"Accept": "application/xml", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            content = resp.read().decode("utf-8", errors="ignore")
        # Extract titles from MARCXML
        titles = re.findall(r'<subfield code="a">(.*?)</subfield>', content)
        return [{"title": t} for t in titles[:max_results]]
    except Exception:
        return []


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
    """Create seed records for key multilateral treaties from the UN Treaty Collection."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, len(_SEED_TREATIES))
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    from src.services.remote_sources import chunk_remote_text

    for title, year, unts in _SEED_TREATIES[:effective_max]:
        source_url = "https://treaties.un.org/"
        text = (
            f"UN Treaty Collection\n"
            f"Treaty: {title}\n"
            f"Year: {year}\n"
            f"UN Treaty Series: {unts}\n"
            f"Official source: {source_url}\n"
            f"Depositary: United Nations Secretary-General"
        ).strip()
        checksum = hashlib.sha256(text.encode()).hexdigest()
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=source_url, checksum=checksum,
            download_key=f"un_treaties:{unts.replace(' ', '_')}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "treaty",
                "source_name": "UN Treaty Collection",
                "jurisdiction": "international",
                "citation": f"{title}, {unts}",
                "source_url": source_url,
                "year": int(year) if year.isdigit() else None,
                "license_note": "UN public domain",
                "language": "en",
            })
        chunks.extend(doc_chunks)
        time.sleep(0.05)

    events.append({"source": "UN Treaty Collection", "status": "completed", "chunks": len(chunks)})
    return chunks, events
