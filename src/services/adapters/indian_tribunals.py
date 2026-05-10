"""Indian tribunals consolidated adapter — ITAT, CESTAT, NCLAT, NGT, CAT, TDSAT, SAT, IBBI, AFT, DRT, CCI.

Each tribunal hosts orders/judgments at varying URL schemes; we use polite, low-volume
sampling: their landing pages + a few index pages each. For deep ingest, this can be
expanded per-tribunal.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_TRIBUNALS = [
    {
        "name": "ITAT",
        "label": "Income Tax Appellate Tribunal",
        "topic": "tax",
        "seeds": [
            "https://itat.gov.in/judicial/tribunalorders",
            "https://itat.gov.in/judicial/tribunalorders?page=1",
            "https://itat.gov.in/judicial/tribunalorders?page=2",
        ],
    },
    {
        "name": "CESTAT",
        "label": "Customs Excise and Service Tax Appellate Tribunal",
        "topic": "indirect_tax",
        "seeds": [
            "https://cestat.gov.in/",
            "https://www.cbic.gov.in/htdocs-cbec/cestat/cestat-judgements",
        ],
    },
    {
        "name": "NCLAT",
        "label": "National Company Law Appellate Tribunal",
        "topic": "company_law_ibc",
        "seeds": [
            "https://nclat.nic.in/judgement-data",
        ],
    },
    {
        "name": "NGT",
        "label": "National Green Tribunal",
        "topic": "environment",
        "seeds": [
            "https://greentribunal.gov.in/",
            "https://greentribunal.gov.in/judgments",
        ],
    },
    {
        "name": "CAT",
        "label": "Central Administrative Tribunal",
        "topic": "service_law",
        "seeds": [
            "https://cgat.gov.in/",
        ],
    },
    {
        "name": "TDSAT",
        "label": "Telecom Disputes Settlement and Appellate Tribunal",
        "topic": "telecom",
        "seeds": ["https://tdsat.gov.in/"],
    },
    {
        "name": "SAT",
        "label": "Securities Appellate Tribunal",
        "topic": "securities",
        "seeds": ["https://sat.gov.in/"],
    },
    {
        "name": "IBBI",
        "label": "Insolvency and Bankruptcy Board of India",
        "topic": "insolvency",
        "seeds": [
            "https://ibbi.gov.in/",
            "https://ibbi.gov.in/en/orders",
        ],
    },
    {
        "name": "AFT",
        "label": "Armed Forces Tribunal",
        "topic": "defence",
        "seeds": ["https://aftdelhi.nic.in/"],
    },
    {
        "name": "DRT",
        "label": "Debt Recovery Tribunal",
        "topic": "banking",
        "seeds": ["https://drt.gov.in/"],
    },
    {
        "name": "CCI",
        "label": "Competition Commission of India",
        "topic": "competition",
        "seeds": [
            "https://www.cci.gov.in/",
            "https://www.cci.gov.in/antitrust/orders",
        ],
    },
]


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
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 60)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items = 0

    for trib in _TRIBUNALS:
        if items >= effective_max:
            break
        for url in trib["seeds"]:
            if items >= effective_max:
                break
            try:
                raw = _http(url, timeout=30)
            except Exception as exc:
                events.append({"tribunal": trib["name"], "url": url, "status": "error", "reason": str(exc)})
                continue
            text = _strip(raw)
            if len(text) < 400:
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
                url=url,
                checksum=checksum,
                download_key=f"intrib:{trib['name']}:{checksum[:16]}",
                quality_gate=quality_gate,
            )
            for chunk in doc_chunks:
                chunk["metadata"].update(
                    {
                        "doc_type": "tribunal_order",
                        "legal_type": "case_law",
                        "source_name": f"{trib['name']} ({trib['label']})",
                        "jurisdiction": "in",
                        "court_or_body": trib["label"],
                        "indian_tribunal": trib["name"],
                        "topic": trib["topic"],
                        "license_note": "Public domain (Indian government work)",
                        "language": "en",
                        "authority_tier": "case_law",
                    }
                )
            chunks.extend(doc_chunks)
            items += 1
            time.sleep(0.4)

    events.append({"status": "completed", "source": "Indian Tribunals", "items": items, "chunks": len(chunks)})
    return chunks, events
