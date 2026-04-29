"""UN Digital Library OAI-PMH adapter.

Harvests metadata and documents from the UN Digital Library via OAI-PMH
protocol at digitallibrary.un.org/oai2d.

No API key required.
"""
from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

_OAI_BASE = "https://digitallibrary.un.org/oai2d"
_DC_NS = "http://purl.org/dc/elements/1.1/"
_OAI_NS = "http://www.openarchives.org/OAI/2.0/"

# UN document sets relevant to international law
_SETS = [
    "UNDOC",       # UN documents
]


def _oai_request(verb: str, **params: str) -> ET.Element:
    """Make an OAI-PMH request and return the parsed XML root."""
    params["verb"] = verb
    url = f"{_OAI_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Accept": "application/xml",
    })
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read()
    return ET.fromstring(raw)


def _dc_values(record_elem: ET.Element, field: str) -> list[str]:
    """Extract Dublin Core field values from an OAI record."""
    values = []
    for elem in record_elem.iter(f"{{{_DC_NS}}}{field}"):
        if elem.text and elem.text.strip():
            values.append(elem.text.strip())
    return values


def _parse_records(root: ET.Element) -> list[dict[str, Any]]:
    """Parse OAI-PMH ListRecords response into dicts."""
    records: list[dict[str, Any]] = []
    for record in root.iter(f"{{{_OAI_NS}}}record"):
        header = record.find(f"{{{_OAI_NS}}}header")
        if header is None:
            continue

        # Skip deleted records
        status = header.get("status", "")
        if status == "deleted":
            continue

        identifier_elem = header.find(f"{{{_OAI_NS}}}identifier")
        identifier = identifier_elem.text.strip() if identifier_elem is not None and identifier_elem.text else ""

        metadata = record.find(f"{{{_OAI_NS}}}metadata")
        if metadata is None:
            continue

        titles = _dc_values(metadata, "title")
        descriptions = _dc_values(metadata, "description")
        dates = _dc_values(metadata, "date")
        subjects = _dc_values(metadata, "subject")
        doc_types = _dc_values(metadata, "type")
        creators = _dc_values(metadata, "creator")
        sources = _dc_values(metadata, "source")
        languages = _dc_values(metadata, "language")

        # Build document text from available fields
        text_parts = []
        if titles:
            text_parts.append(f"Title: {titles[0]}")
        if creators:
            text_parts.append(f"Creator: {'; '.join(creators)}")
        if dates:
            text_parts.append(f"Date: {dates[0]}")
        if subjects:
            text_parts.append(f"Subjects: {'; '.join(subjects)}")
        if descriptions:
            text_parts.extend(descriptions)

        text = "\n\n".join(text_parts)
        if len(text.strip()) < 100:
            continue

        # Extract year
        year = None
        for d in dates:
            year_match = re.search(r"(19|20)\d{2}", d)
            if year_match:
                year = int(year_match.group(0))
                break

        records.append({
            "identifier": identifier,
            "title": titles[0] if titles else "UN Document",
            "text": text,
            "date": dates[0] if dates else "",
            "year": year,
            "subjects": subjects,
            "doc_type": doc_types[0] if doc_types else "resolution",
            "language": languages[0] if languages else "en",
        })

    return records


def _get_resumption_token(root: ET.Element) -> str | None:
    """Extract resumption token for pagination."""
    for token_elem in root.iter(f"{{{_OAI_NS}}}resumptionToken"):
        if token_elem.text and token_elem.text.strip():
            return token_elem.text.strip()
    return None


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
    """Harvest documents from UN Digital Library via OAI-PMH.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_total = 0

    try:
        xml_root = _oai_request(
            "ListRecords",
            metadataPrefix="oai_dc",
            # Fetch recent documents
            **{"from": "2020-01-01"},
        )
    except Exception as exc:
        events.append({"status": "error", "reason": f"{type(exc).__name__}: {exc}"})
        return [], events

    parsed = _parse_records(xml_root)
    events.append({"status": "initial_harvest", "records": len(parsed)})

    for doc in parsed:
        if items_total >= effective_max:
            break

        text = doc["text"]
        text_bytes = len(text.encode("utf-8"))

        if not budget.can_store(text_bytes):
            events.append({"status": "budget_exhausted"})
            break
        budget.reserve(text_bytes)

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=f"https://digitallibrary.un.org/record/{doc['identifier'].split(':')[-1] if ':' in doc['identifier'] else doc['identifier']}",
            checksum=checksum,
            download_key=f"undl:{checksum[:16]}",
        )

        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "treaty" if "treaty" in doc.get("doc_type", "").lower() else "commentary",
                "source_name": f"UN Digital Library: {doc['title']}",
                "jurisdiction": "international",
                "year": doc["year"],
                "date": doc["date"],
                "un_identifier": doc["identifier"],
                "subjects": doc["subjects"][:5],
                "citation": doc["title"],
                "license_note": "UN documents; reuse with attribution",
                "language": doc["language"],
            })

        chunks.extend(doc_chunks)
        items_total += 1

    # Try to get more via resumption token (one more page)
    token = _get_resumption_token(xml_root)
    if token and items_total < effective_max:
        try:
            time.sleep(1)
            xml_root2 = _oai_request("ListRecords", resumptionToken=token)
            parsed2 = _parse_records(xml_root2)
            for doc in parsed2:
                if items_total >= effective_max:
                    break
                text = doc["text"]
                text_bytes = len(text.encode("utf-8"))
                if not budget.can_store(text_bytes):
                    break
                budget.reserve(text_bytes)
                checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

                from src.services.remote_sources import chunk_remote_text
                doc_chunks = chunk_remote_text(
                    record, plan, text,
                    url=f"https://digitallibrary.un.org/record/{doc['identifier'].split(':')[-1]}",
                    checksum=checksum,
                    download_key=f"undl:{checksum[:16]}",
                )
                for chunk in doc_chunks:
                    chunk["metadata"].update({
                        "doc_type": "commentary",
                        "source_name": f"UN Digital Library: {doc['title']}",
                        "jurisdiction": "international",
                        "year": doc["year"],
                        "date": doc["date"],
                        "un_identifier": doc["identifier"],
                        "citation": doc["title"],
                        "license_note": "UN documents; reuse with attribution",
                        "language": doc["language"],
                    })
                chunks.extend(doc_chunks)
                items_total += 1
        except Exception as exc:
            events.append({"status": "resumption_error", "reason": str(exc)})

    events.append({
        "status": "completed",
        "source": "UN Digital Library",
        "total_documents": items_total,
        "total_chunks": len(chunks),
    })
    return chunks, events
