"""Doctrinal canon adapter — public-domain treatises via Internet Archive.

Anchors OmniLegal's doctrinal reasoning layer: Blackstone, Coke, Story,
Federalist Papers, Pollock & Maitland, Maine, Holdsworth, Bentham, Austin,
Salmond, Grotius, Vattel, Oppenheim, Justinian Institutes/Digest, Wigmore.

Strategy: ingest the Internet Archive plain-text endpoint
   https://archive.org/download/<itemid>/<itemid>_djvu.txt
which gives clean OCR'd public-domain text. If the canonical item 503/404s,
we fall back to IA's advancedsearch.php to locate a working alternative.
"""
from __future__ import annotations

import hashlib
import json as _json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

# (item_id, citation_label, jurisdiction, year)
# IDs verified via IA advancedsearch — fallback search activates if the primary 503s.
_CANON: list[tuple[str, str, str, int]] = [
    # English common law
    ("cu31924064829710",                          "Blackstone, Commentaries on the Laws of England",            "uk",       1769),
    ("commentariesonla00sharuoft",                "Blackstone, Commentaries on the Laws (Sharswood ed.)",      "uk",       1893),
    ("ancientlawitscon01main",                    "Maine, Ancient Law (1888 ed.)",                              "uk",       1888),
    ("historyofenglish01poll",                    "Pollock & Maitland, History of English Law (Vol. 1)",        "uk",       1899),
    ("historyofenglish02poll",                    "Pollock & Maitland, History of English Law (Vol. 2)",        "uk",       1899),

    # United States
    ("federalist00hami",                          "The Federalist Papers (Hamilton, Madison, Jay)",              "us",       1788),
    ("commentariesonc01stor",                     "Story, Commentaries on the Constitution",                     "us",       1833),
    ("treatiseonconst00cool",                     "Cooley, Constitutional Limitations",                          "us",       1868),

    # Jurisprudence / theory
    ("worksofjeremybentham01bent",                "Bentham, Collected Works (Bowring ed., Vol. 1)",              "uk",       1838),
    ("provinceofjurisp00aust",                    "Austin, The Province of Jurisprudence Determined",            "uk",       1832),
    ("jurisprudence00salm",                       "Salmond on Jurisprudence",                                    "uk",       1902),

    # International law
    ("internationallaw00oppe",                    "Oppenheim, International Law (Vol. 1: Peace)",                "international", 1905),
    ("dejurebellipacis01grot",                    "Grotius, De Jure Belli ac Pacis",                            "international", 1625),
    ("droitdesgensoupr01vatt",                    "Vattel, Le Droit des Gens (Law of Nations)",                 "international", 1758),

    # Roman law
    ("institutesofjust00just",                    "Justinian's Institutes (Sandars trans.)",                     "international", 533),
    ("digestofjustinia01just",                    "Justinian's Digest (Monro trans., Vol. 1)",                  "international", 533),

    # Evidence / Procedure
    ("treatiseonsystem01wigm",                    "Wigmore, A Treatise on the System of Evidence",              "us",       1904),
]


def _http(url: str, timeout: int = 60) -> bytes:
    """HTTP GET with tolerant retries on 503/429."""
    last_exc: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "OmniLegalResearch/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code in (503, 429):
                time.sleep(2 ** attempt)
                continue
            raise
        except Exception as exc:
            last_exc = exc
            time.sleep(1 + attempt)
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


def _ia_search_for(item: str) -> str | None:
    """When the canonical item 503s/404s, search IA for a working alternative."""
    title_terms = item.replace("_", " ").replace("0", " ")
    try:
        url = (
            "https://archive.org/advancedsearch.php?"
            f"q=title%3A%28{urllib.parse.quote(title_terms)}%29+AND+mediatype%3Atexts"
            "&fl[]=identifier&output=json&rows=3"
        )
        raw = _http(url, timeout=15)
        data = _json.loads(raw.decode("utf-8", errors="replace"))
        for d in data.get("response", {}).get("docs", []):
            ident = d.get("identifier")
            if ident and ident != item:
                return ident
    except Exception:
        pass
    return None


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 6 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    quality_gate: str = "standard",
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, len(_CANON))
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0

    for item_id, citation, jurisdiction, year in _CANON[:effective_max]:
        url = f"https://archive.org/download/{item_id}/{item_id}_djvu.txt"
        try:
            raw = _http(url)
        except Exception as exc:
            alt = _ia_search_for(item_id)
            if alt:
                try:
                    raw = _http(f"https://archive.org/download/{alt}/{alt}_djvu.txt")
                    item_id = alt
                except Exception as exc2:
                    events.append({"item": item_id, "status": "error_after_fallback", "reason": str(exc2)})
                    continue
            else:
                events.append({"item": item_id, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
                continue
        text = raw.decode("utf-8", errors="replace")
        text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(text) < 5000:
            continue
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > max_bytes:
            text = text[:max_bytes]
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
            download_key=f"canon:{item_id}:{checksum[:16]}",
            quality_gate=quality_gate,
        )
        for chunk in doc_chunks:
            chunk["metadata"].update(
                {
                    "doc_type": "treatise",
                    "legal_type": "commentary",
                    "source_name": citation,
                    "citation": citation,
                    "jurisdiction": jurisdiction,
                    "year": year,
                    "court_or_body": "doctrinal canon",
                    "license_note": "Public domain (pre-1928 imprint via Internet Archive)",
                    "language": "en",
                    "authority_tier": "doctrinal_canon",
                    "doctrinal_priority": 1.0,
                }
            )
        chunks.extend(doc_chunks)
        items += 1
        time.sleep(0.5)

    events.append({"status": "completed", "source": "Doctrinal canon", "items": items, "chunks": len(chunks)})
    return chunks, events
