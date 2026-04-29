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

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

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

        text = _cellar_content(work_uri)
        if not text:
            # Use the metadata as a minimal record
            text = f"EUR-Lex Legislation: {title}\nCELEX: {celex}\nDate: {date}\nURI: {work_uri}"

        text_bytes = len(text.encode("utf-8"))
        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted"})
            break
        budget.reserve(text_bytes)

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        year_match = re.search(r"(19|20)\d{2}", date)
        year = int(year_match.group(0)) if year_match else None

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=work_uri,
            checksum=checksum,
            download_key=f"eurlex:{celex or checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "statute",
                "source_name": f"EUR-Lex: {title}",
                "jurisdiction": "eu",
                "year": year,
                "date": date,
                "celex_id": celex,
                "citation": celex or title,
                "license_note": "CC BY 4.0 / CC0 1.0 (EUR-Lex reuse framework)",
                "language": "en",
            })

        chunks.extend(doc_chunks)
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

        text = _cellar_content(work_uri)
        if not text:
            text = f"CJEU Case: {title}\nECLI: {ecli}\nDate: {date}\nURI: {work_uri}"

        text_bytes = len(text.encode("utf-8"))
        if not budget.can_store(text_bytes):
            break
        budget.reserve(text_bytes)

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        year_match = re.search(r"(19|20)\d{2}", date)
        year = int(year_match.group(0)) if year_match else None

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=work_uri,
            checksum=checksum,
            download_key=f"cjeu:{ecli or checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "case_law",
                "source_name": f"CJEU: {title}",
                "jurisdiction": "eu",
                "year": year,
                "date": date,
                "ecli": ecli,
                "citation": ecli or title,
                "license_note": "Public domain (EU court decisions)",
                "language": "en",
            })

        chunks.extend(doc_chunks)
        items_total += 1
        time.sleep(0.3)

    events.append({
        "status": "completed",
        "source": "EUR-Lex / CELLAR",
        "total_documents": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
