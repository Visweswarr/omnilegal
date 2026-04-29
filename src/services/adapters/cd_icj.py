"""CD-ICJ (Corpus of Decisions: International Court of Justice) adapter.

Downloads the CD-ICJ dataset from Zenodo (DOI: 10.5281/zenodo.3826444)
and ingests ICJ judgments, advisory opinions, and orders.

This is a bulk-file download adapter: one ZIP → many TXT files.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE

# Zenodo API endpoint to get the latest version's download links
_ZENODO_API = "https://zenodo.org/api/records/3826444"
_FALLBACK_URL = "https://zenodo.org/records/3826444/files/CD-ICJ_EN.zip"


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": "OmniLegalResearchAssistant/1.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _find_english_zip_url() -> str:
    """Query Zenodo API to find the English ZIP download URL."""
    try:
        data = _get_json(_ZENODO_API)
        for file_info in data.get("files", []):
            name = file_info.get("key", "").lower()
            if "en" in name and name.endswith(".zip"):
                links = file_info.get("links", {})
                return links.get("self") or file_info.get("download") or _FALLBACK_URL
    except Exception:
        pass
    return _FALLBACK_URL


def _parse_icj_filename(name: str) -> dict[str, Any]:
    """Extract metadata from ICJ document filename.

    Typical patterns:
      ICJ_01_ABC_ABC_1950-01-01_JUD_01_EN.txt
      ICJ_01_ABC_ABC_1950-01-01_AO_01_EN.txt
    """
    metadata: dict[str, Any] = {"year": None, "doc_subtype": "unknown", "case_name": name}

    # Try to extract date
    date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", name)
    if date_match:
        metadata["year"] = int(date_match.group(1))
        metadata["date"] = date_match.group(0)

    # Try to extract document type
    if "_JUD_" in name.upper() or "_JUDGMENT_" in name.upper():
        metadata["doc_subtype"] = "judgment"
    elif "_AO_" in name.upper() or "_ADVISORY_" in name.upper():
        metadata["doc_subtype"] = "advisory_opinion"
    elif "_ORD_" in name.upper() or "_ORDER_" in name.upper():
        metadata["doc_subtype"] = "order"
    elif "_SEP_" in name.upper() or "_DIS_" in name.upper():
        metadata["doc_subtype"] = "separate_opinion"
    elif "_PLEA_" in name.upper():
        metadata["doc_subtype"] = "pleading"

    # Clean up case name from filename
    clean_name = name.replace(".txt", "").replace("_", " ").strip()
    metadata["case_name"] = clean_name

    return metadata


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 50 * 1024 * 1024,  # ICJ ZIP can be ~30MB
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Download CD-ICJ from Zenodo and chunk all English TXT files.

    Returns (chunks, events).
    """
    if checkpoint is None:
        checkpoint = {}

    effective_max = max_items if max_items > 0 else OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    # Step 1: Find the download URL
    zip_url = _find_english_zip_url()
    events.append({"status": "resolved_url", "url": zip_url})

    # Step 2: Download the ZIP
    try:
        req = urllib.request.Request(zip_url, headers={
            "User-Agent": "OmniLegalResearchAssistant/1.0",
        })
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    except Exception as exc:
        events.append({"status": "download_error", "reason": f"{type(exc).__name__}: {exc}"})
        return [], events

    zip_size = len(raw)
    if not budget.can_store(zip_size):
        events.append({"status": "budget_exhausted", "bytes": zip_size})
        return [], events
    budget.reserve(zip_size)

    # Save raw ZIP
    raw_dir = root / "raw" / "cd_icj"
    raw_dir.mkdir(parents=True, exist_ok=True)
    zip_hash = hashlib.sha256(raw).hexdigest()
    zip_path = raw_dir / f"cd_icj_{zip_hash[:16]}.zip"
    if not zip_path.exists():
        zip_path.write_bytes(raw)

    events.append({"status": "downloaded", "bytes": zip_size, "sha256": zip_hash[:32]})

    # Step 3: Extract and process TXT files
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as exc:
        events.append({"status": "bad_zip", "reason": str(exc)})
        return [], events

    txt_files = [
        name for name in zf.namelist()
        if name.lower().endswith(".txt") and not name.startswith("__MACOSX")
    ]

    items_ingested = 0
    for txt_name in sorted(txt_files):
        if items_ingested >= effective_max:
            break

        try:
            text = zf.read(txt_name).decode("utf-8", errors="replace").strip()
        except Exception:
            continue

        if len(text) < 200:
            continue

        file_meta = _parse_icj_filename(Path(txt_name).name)
        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()

        from src.services.remote_sources import chunk_remote_text
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=zip_url,
            checksum=checksum,
            download_key=f"cd_icj:{checksum[:16]}",
        )

        # Enrich with ICJ-specific metadata
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": "case_law",
                "case_name": file_meta["case_name"],
                "year": file_meta["year"],
                "doc_subtype": file_meta["doc_subtype"],
                "date": file_meta.get("date", ""),
                "source_name": f"ICJ: {file_meta['case_name']}",
                "jurisdiction": "international",
                "citation": f"ICJ, {file_meta['case_name']} ({file_meta.get('year', '')})",
                "license_note": "CC0 1.0 (CD-ICJ dataset); ICJ decisions UN public domain",
            })

        chunks.extend(doc_chunks)
        items_ingested += 1

    events.append({
        "status": "completed",
        "source": "CD-ICJ (Zenodo)",
        "total_files_in_zip": len(txt_files),
        "documents_ingested": items_ingested,
        "total_chunks": len(chunks),
    })
    return chunks, events
