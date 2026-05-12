"""EUR-Lex / CELLAR SPARQL adapter.

Fetches EU legislation and CJEU case law via the EU Publications Office
SPARQL endpoint at publications.europa.eu.

No API key required (open access).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import (
    COLLECTION_CASE_LAW_EU,
    COLLECTION_STATUTES_EU,
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
    OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE,
)

_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"

# SPARQL query to find recent EU legislation
_LEGISLATION_QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?work ?title ?date ?celex
WHERE {{
  ?work cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/REG> .
  ?work cdm:resource_legal_date_entry-into-force ?date .
  ?work cdm:resource_legal_id_celex ?celex .
  ?exp cdm:expression_belongs_to_work ?work .
  ?exp cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  ?exp cdm:expression_title ?title .
  FILTER(xsd:date(?date) >= "2020-01-01"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT {limit}
"""

# SPARQL query for CJEU case law
_CASELAW_QUERY = """
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT DISTINCT ?work ?title ?date ?ecli
WHERE {{
  ?work cdm:work_has_resource-type <http://publications.europa.eu/resource/authority/resource-type/JUDG> .
  ?work cdm:resource_legal_date_document ?date .
  ?exp cdm:expression_belongs_to_work ?work .
  ?exp cdm:expression_uses_language <http://publications.europa.eu/resource/authority/language/ENG> .
  ?exp cdm:expression_title ?title .
  OPTIONAL {{ ?work cdm:resource_legal_id_sector ?ecli }}
  FILTER(xsd:date(?date) >= "2020-01-01"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT {limit}
"""

_SEED_DOCUMENTS = [
    {"kind": "statute", "title": "Treaty on European Union", "celex": "12016M/TXT", "date": "2016-06-07"},
    {"kind": "statute", "title": "Treaty on the Functioning of the European Union", "celex": "12016E/TXT", "date": "2016-06-07"},
    {"kind": "statute", "title": "Charter of Fundamental Rights of the European Union", "celex": "12012P/TXT", "date": "2012-10-26"},
    {"kind": "statute", "title": "General Data Protection Regulation", "celex": "32016R0679", "date": "2016-04-27"},
    {"kind": "statute", "title": "Digital Services Act", "celex": "32022R2065", "date": "2022-10-19"},
    {"kind": "statute", "title": "Digital Markets Act", "celex": "32022R1925", "date": "2022-09-14"},
    {"kind": "statute", "title": "Artificial Intelligence Act", "celex": "32024R1689", "date": "2024-06-13"},
    {"kind": "statute", "title": "Consumer Rights Directive", "celex": "32011L0083", "date": "2011-10-25"},
    {"kind": "statute", "title": "Unfair Commercial Practices Directive", "celex": "32005L0029", "date": "2005-05-11"},
    {"kind": "statute", "title": "Consumer Protection Cooperation Regulation", "celex": "32017R2394", "date": "2017-12-12"},
    {"kind": "statute", "title": "General Product Safety Regulation", "celex": "32023R0988", "date": "2023-05-10"},
    {"kind": "case_law", "title": "Van Gend en Loos", "celex": "61962CJ0026", "date": "1963-02-05", "ecli": "ECLI:EU:C:1963:1"},
    {"kind": "case_law", "title": "Costa v ENEL", "celex": "61964CJ0006", "date": "1964-07-15", "ecli": "ECLI:EU:C:1964:66"},
    {"kind": "case_law", "title": "Google Spain", "celex": "62012CJ0131", "date": "2014-05-13", "ecli": "ECLI:EU:C:2014:317"},
    {"kind": "case_law", "title": "Schrems II", "celex": "62018CJ0311", "date": "2020-07-16", "ecli": "ECLI:EU:C:2020:559"},
]


def _sparql_query(query: str) -> list[dict[str, Any]]:
    """Execute a SPARQL query and return bindings."""
    encoded = urllib.parse.urlencode({"query": query})
    req = urllib.request.Request(
        _SPARQL_ENDPOINT,
        data=encoded.encode("utf-8"),
        headers={
            "User-Agent": "OmniLegalResearchAssistant/1.0",
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("results", {}).get("bindings", [])


def _cellar_content(work_uri: str) -> str:
    """Try to fetch the text content of a Cellar work."""
    # Try HTML rendition first
    for accept in ["text/html", "application/xhtml+xml", "text/plain"]:
        try:
            req = urllib.request.Request(work_uri, headers={
                "User-Agent": "OmniLegalResearchAssistant/1.0",
                "Accept": accept,
            })
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read(5 * 1024 * 1024)
                from src.services.remote_sources import parse_downloaded_content
                content_type = resp.headers.get("Content-Type", "")
                text = parse_downloaded_content(raw, url=work_uri, content_type=content_type)
                if len(text.strip()) > 200:
                    return text
        except Exception:
            continue
    return ""


def _binding_value(binding: dict[str, Any], key: str) -> str:
    return (binding.get(key) or {}).get("value", "")


def _eurlex_url(celex: str) -> str:
    return f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}"


def _year_from_date(date: str) -> int | None:
    year_match = re.search(r"(19|20)\d{2}", date or "")
    return int(year_match.group(0)) if year_match else None


def _add_document_chunks(
    *,
    record: Any,
    plan: Any,
    budget: Any,
    chunks: list[dict[str, Any]],
    title: str,
    date: str,
    identifier: str,
    doc_type: str,
    url: str,
    text: str,
    ecli: str = "",
) -> bool:
    if not text:
        label = "CJEU Case" if doc_type == "case_law" else "EUR-Lex Legislation"
        text = f"{label}: {title}\nCELEX: {identifier}\nDate: {date}\nURI: {url}"

    text_bytes = len(text.encode("utf-8", errors="ignore"))
    if not budget.can_store(text_bytes):
        return False
    budget.reserve(text_bytes)

    checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    from src.services.remote_sources import chunk_remote_text
    doc_chunks = chunk_remote_text(
        record,
        plan,
        text,
        url=url,
        checksum=checksum,
        download_key=f"eurlex:{identifier or checksum[:16]}",
    )
    year = _year_from_date(date)
    for chunk in doc_chunks:
        meta = {
            "doc_type": doc_type,
            "source_name": f"{'CJEU' if doc_type == 'case_law' else 'EUR-Lex'}: {title}",
            "jurisdiction": "eu",
            "year": year,
            "date": date,
            "celex_id": identifier,
            "citation": ecli or identifier or title,
            "license_note": "CC BY 4.0 / CC0 1.0 (EUR-Lex reuse framework)",
            "language": "en",
            "collection": COLLECTION_CASE_LAW_EU if doc_type == "case_law" else COLLECTION_STATUTES_EU,
            "source_role": "case_law" if doc_type == "case_law" else "local_statute",
            "authority_tier": "case_law" if doc_type == "case_law" else "primary_authority",
            "canonical_doc_id": f"eurlex:{re.sub(r'[^A-Za-z0-9_.:-]+', '_', identifier or checksum[:16])}",
            "source_fingerprint": identifier or checksum[:16],
            "source_version": date or "undated",
            "version_date": date or "undated",
        }
        if ecli:
            meta["ecli"] = ecli
        chunk["metadata"].update(meta)
    chunks.extend(doc_chunks)
    return True


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
    """Fetch EU legislation and case law via SPARQL.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_total = 0
    seen_doc_keys: set[str] = set()

    # Seed landmark instruments and cases first so the EU KB is useful even
    # when live SPARQL returns sparse or recently skewed results.
    for doc in _SEED_DOCUMENTS[:effective_max]:
        celex = str(doc.get("celex") or "")
        if not celex or celex in seen_doc_keys:
            continue
        url = _eurlex_url(celex)
        text = _cellar_content(url)
        ok = _add_document_chunks(
            record=record,
            plan=plan,
            budget=budget,
            chunks=chunks,
            title=str(doc.get("title") or celex),
            date=str(doc.get("date") or ""),
            identifier=celex,
            doc_type=str(doc.get("kind") or "statute"),
            url=url,
            text=text,
            ecli=str(doc.get("ecli") or ""),
        )
        if not ok:
            events.append({"query": "seed_documents", "status": "budget_exhausted"})
            break
        seen_doc_keys.add(celex)
        items_total += 1
        time.sleep(0.15)
    events.append({"query": "seed_documents", "results": len(seen_doc_keys)})

    # Fetch legislation
    try:
        leg_bindings = _sparql_query(_LEGISLATION_QUERY.format(limit=effective_max))
        events.append({"query": "legislation", "results": len(leg_bindings)})
    except Exception as exc:
        leg_bindings = []
        events.append({"query": "legislation", "status": "error", "reason": str(exc)})

    for binding in leg_bindings:
        if items_total >= effective_max:
            break

        work_uri = _binding_value(binding, "work")
        title = _binding_value(binding, "title")
        date = _binding_value(binding, "date")
        celex = _binding_value(binding, "celex")

        if not work_uri or not title:
            continue
        if celex and celex in seen_doc_keys:
            continue

        text = _cellar_content(work_uri)
        ok = _add_document_chunks(
            record=record,
            plan=plan,
            budget=budget,
            chunks=chunks,
            title=title,
            date=date,
            identifier=celex,
            doc_type="statute",
            url=work_uri,
            text=text,
        )
        if not ok:
            events.append({"status": "budget_exhausted"})
            break
        seen_doc_keys.add(celex or work_uri)
        items_total += 1
        time.sleep(0.3)

    # Fetch CJEU case law
    try:
        case_bindings = _sparql_query(_CASELAW_QUERY.format(limit=effective_max))
        events.append({"query": "cjeu_caselaw", "results": len(case_bindings)})
    except Exception as exc:
        case_bindings = []
        events.append({"query": "cjeu_caselaw", "status": "error", "reason": str(exc)})

    for binding in case_bindings:
        if items_total >= effective_max * 2:
            break

        work_uri = _binding_value(binding, "work")
        title = _binding_value(binding, "title")
        date = _binding_value(binding, "date")
        ecli = _binding_value(binding, "ecli")

        if not work_uri or not title:
            continue
        doc_key = ecli or work_uri
        if doc_key in seen_doc_keys:
            continue

        text = _cellar_content(work_uri)
        ok = _add_document_chunks(
            record=record,
            plan=plan,
            budget=budget,
            chunks=chunks,
            title=title,
            date=date,
            identifier=ecli or work_uri,
            doc_type="case_law",
            url=work_uri,
            text=text,
            ecli=ecli,
        )
        if not ok:
            break
        seen_doc_keys.add(doc_key)
        items_total += 1
        time.sleep(0.3)

    events.append({
        "status": "completed",
        "source": "EUR-Lex / CELLAR",
        "total_documents": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
