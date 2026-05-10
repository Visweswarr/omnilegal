"""India High Courts (AWS Open Data) adapter — 25 High Courts, CC-BY-4.0.

Companion to india_aws_sc.py for the High Court bulk:
   s3://indian-high-court-judgments  (anonymous, CC-BY-4.0)
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_S3_BASE = "https://indian-high-court-judgments.s3.ap-south-1.amazonaws.com"
_NS = "http://s3.amazonaws.com/doc/2006-03-01/"

# 25 HC codes. Sampling order = commercial-law density first.
_HC_CODES = [
    "delhi", "bombay", "madras", "kolkata", "karnataka",
    "telangana", "kerala", "gujarat", "punjab_haryana", "allahabad",
    "andhra_pradesh", "rajasthan", "madhya_pradesh", "patna",
    "orissa", "chhattisgarh", "uttarakhand", "jharkhand",
    "himachal_pradesh", "jammu_kashmir", "tripura", "meghalaya",
    "manipur", "sikkim", "guwahati",
]


def _http(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OmniLegalResearch/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _list_keys(prefix: str, max_keys: int = 50) -> list[str]:
    url = f"{_S3_BASE}/?list-type=2&max-keys={max_keys}&prefix={prefix}"
    try:
        raw = _http(url, timeout=30)
    except Exception:
        return []
    try:
        xml = ET.fromstring(raw)
    except ET.ParseError:
        return []
    keys: list[str] = []
    for c in xml.iter(f"{{{_NS}}}Contents"):
        ke = c.find(f"{{{_NS}}}Key")
        if ke is not None and ke.text:
            keys.append(ke.text)
    return keys


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
    per_hc = max(1, effective_max // max(1, len(_HC_CODES)))
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0

    for hc in _HC_CODES:
        if items >= effective_max:
            break
        # Try common prefixes for HC bulk dumps
        keys: list[str] = []
        for prefix in (f"data/{hc}/", f"{hc}/judgments/", f"judgments/{hc}/", f"{hc}/"):
            keys = _list_keys(prefix, max_keys=per_hc * 4)
            if keys:
                break
        if not keys:
            events.append({"hc": hc, "status": "no_keys"})
            continue
        for key in keys[:per_hc]:
            if items >= effective_max:
                break
            text_url = f"{_S3_BASE}/{key}"
            try:
                raw = _http(text_url, timeout=30)
            except Exception:
                continue
            from src.services.remote_sources import parse_downloaded_content

            text = parse_downloaded_content(raw, url=text_url, content_type="")
            if not text or len(text) < 400:
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
                url=text_url,
                checksum=checksum,
                download_key=f"india_hc:{hc}:{checksum[:16]}",
                quality_gate=quality_gate,
            )
            year_match = re.search(r"(19|20)\d{2}", key)
            year = int(year_match.group(0)) if year_match else None
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "case_law",
                        "legal_type": "case_law",
                        "source_name": f"Indian HC ({hc.replace('_', ' ').title()})",
                        "jurisdiction": "in",
                        "court_or_body": f"{hc.replace('_', ' ').title()} High Court",
                        "indian_high_court": hc,
                        "year": year,
                        "license_note": "CC BY 4.0 (AWS Open Data — Indian HC judgments)",
                        "language": "en",
                        "authority_tier": "case_law",
                    }
                )
            chunks.extend(doc_chunks)
            items += 1
            time.sleep(0.2)

    events.append({"status": "completed", "source": "India HC AWS", "items": items, "chunks": len(chunks)})
    return chunks, events
