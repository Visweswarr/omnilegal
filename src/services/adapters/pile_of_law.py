"""Pile of Law adapter — streams the HuggingFace dataset ``pile-of-law/pile-of-law``.

Only the ``_Commercial`` subsets are used (safe for any downstream use).
Targets high-value US legal subsets: BVA decisions, SCOTUS filings,
Federal Register, CFR, and state statutes.

Requires ``datasets`` (``pip install datasets``) and optionally ``HF_TOKEN``.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from src.config import (
    COLLECTION_CASE_LAW_US,
    COLLECTION_STATUTES_US,
    HF_TOKEN,
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
)

log = logging.getLogger(__name__)

_DATASET_ID = "pile-of-law/pile-of-law"

# Subset → (collection, doc_type, jurisdiction)
_SUBSET_MAP: dict[str, tuple[str, str, str]] = {
    "bva_opinions":         (COLLECTION_CASE_LAW_US, "case_law", "us"),
    "scotus_oral_arguments": (COLLECTION_CASE_LAW_US, "case_law", "us"),
    "federal_register":     (COLLECTION_STATUTES_US, "statute", "us"),
    "cfr":                  (COLLECTION_STATUTES_US, "statute", "us"),
    "state_codes":          (COLLECTION_STATUTES_US, "statute", "us"),
    "scotus_filings":       (COLLECTION_CASE_LAW_US, "case_law", "us"),
}


def _try_load_dataset() -> Any:
    """Import ``datasets`` and open the streaming iterator."""
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
        return load_dataset
    except ImportError:
        log.warning("'datasets' library not installed — pip install datasets")
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
    """Stream Pile of Law samples from HuggingFace and return (chunks, events)."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)
    load_dataset = _try_load_dataset()
    if load_dataset is None:
        return [], [{"source": "pile_of_law", "status": "error", "reason": "datasets library not installed"}]

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_per_subset = max(1, effective_max // len(_SUBSET_MAP))

    for subset_name, (collection, doc_type, jurisdiction) in _SUBSET_MAP.items():
        try:
            ds = load_dataset(
                _DATASET_ID,
                subset_name,
                split="train",
                streaming=True,
                trust_remote_code=True,
                token=HF_TOKEN or None,
            )
        except Exception as exc:
            log.warning("Pile of Law subset %s failed: %s", subset_name, exc)
            events.append({"source": f"pile_of_law/{subset_name}", "status": "error", "reason": str(exc)})
            continue

        count = 0
        for example in ds:
            if count >= items_per_subset:
                break
            text = str(example.get("text", "")).strip()
            if len(text) < 100:
                continue

            # Truncate very large documents to stay within budget
            if len(text) > max_bytes:
                text = text[:max_bytes]

            checksum = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=f"https://huggingface.co/datasets/{_DATASET_ID}",
                checksum=checksum,
                download_key=f"pile_of_law:{subset_name}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": doc_type,
                    "source_name": f"Pile of Law / {subset_name}",
                    "jurisdiction": jurisdiction,
                    "collection": collection,
                    "source_url": f"https://huggingface.co/datasets/{_DATASET_ID}",
                    "license_note": "CC-BY-4.0 (Commercial subset)",
                    "language": "en",
                    "hf_subset": subset_name,
                })
            chunks.extend(doc_chunks)
            count += 1
            time.sleep(0.01)

        events.append({
            "source": f"pile_of_law/{subset_name}",
            "status": "completed",
            "chunks": count,
        })

    events.append({"source": "pile_of_law", "status": "completed", "total_chunks": len(chunks)})
    return chunks, events
