"""ILO NATLEX adapter — national labour and social-security legislation metadata."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_BASE_URL = "https://www.ilo.org/dyn/natlex/natlex4.byCountry"

# Seed country codes with significant ILO NATLEX coverage
_SEED_COUNTRIES = [
    ("IN", "India"),
    ("US", "United States"),
    ("GB", "United Kingdom"),
    ("DE", "Germany"),
    ("FR", "France"),
    ("BR", "Brazil"),
    ("ZA", "South Africa"),
    ("AU", "Australia"),
]


def _fetch_country(iso2: str, limit: int = 5) -> list[dict[str, Any]]:
    # ILO NATLEX public XML/HTML endpoint — retrieve document list by country
    params = urllib.parse.urlencode({"p_lang": "E", "p_country": iso2, "p_count": str(limit)})
    url = f"https://www.ilo.org/dyn/natlex/natlex4.byCountry?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        content = resp.read(204800).decode("utf-8", errors="ignore")
    # Extract document titles from the HTML list (basic scraping)
    import re
    titles = re.findall(r'<td[^>]*class="[^"]*title[^"]*"[^>]*>(.*?)</td>', content, re.I | re.S)
    cleaned = [re.sub(r'<[^>]+>', ' ', t).strip() for t in titles[:limit]]
    return [{"title": t} for t in cleaned if t]


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
    """Fetch ILO NATLEX labour legislation metadata by country."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 40)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for iso2, country in _SEED_COUNTRIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _fetch_country(iso2, limit=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"country": country, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            items = []

        # Always create at least a country-level seed record
        country_key = f"ilo_natlex:{iso2}"
        if country_key not in seen:
            seen.add(country_key)
            source_url = f"https://www.ilo.org/dyn/natlex/natlex4.byCountry?p_lang=E&p_country={iso2}"
            text = (
                f"ILO NATLEX — {country} national labour legislation\n"
                f"Country ISO: {iso2}\n"
                f"Coverage: National labour laws, social security, employment legislation\n"
                f"Official source: {source_url}"
            ).strip()
            for item in items:
                title = str(item.get("title") or "").strip()
                if title:
                    text += f"\nDocument: {title}"
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"ilo_natlex:{iso2}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "labour_legislation_metadata",
                    "source_name": f"ILO NATLEX: {country}",
                    "jurisdiction": iso2.lower(),
                    "citation": f"ILO NATLEX — {country} ({iso2})",
                    "source_url": source_url,
                    "license_note": "ILO public access",
                    "language": "en",
                })
            chunks.extend(doc_chunks)
        time.sleep(0.2)

    events.append({"source": "ILO NATLEX", "status": "completed", "chunks": len(chunks)})
    return chunks, events
