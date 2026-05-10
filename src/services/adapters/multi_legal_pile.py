"""MultiLegalPile adapter — streams ``joelniklaus/Multi_Legal_Pile`` from HuggingFace.

Only the ``_Commercial`` variant is used (safe for downstream use).
Focuses on English + EU caselaw and legislation subsets. Maps each document
to the appropriate jurisdiction-specific Qdrant collection.

Requires ``datasets`` (``pip install datasets``) and optionally ``HF_TOKEN``.
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Any

from src.config import (
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_UK,
    HF_TOKEN,
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
)

log = logging.getLogger(__name__)

_DATASET_ID = "joelniklaus/Multi_Legal_Pile"

# (language, type_filter) → (collection, doc_type, jurisdiction)
_SUBSET_MAP: dict[tuple[str, str], tuple[str, str, str]] = {
    ("en", "caselaw"):      (COLLECTION_CASE_LAW_UK, "case_law", "uk"),
    ("en", "legislation"):  (COLLECTION_STATUTES_UK, "statute", "uk"),
    ("eu", "caselaw"):      (COLLECTION_CASE_LAW_EU, "case_law", "eu"),
    ("eu", "legislation"):  (COLLECTION_STATUTES_EU, "statute", "eu"),
}


def _try_load_dataset() -> Any:
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
    """Stream MultiLegalPile samples and return (chunks, events)."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)
    load_dataset = _try_load_dataset()
    if load_dataset is None:
        return [], [{"source": "multi_legal_pile", "status": "error", "reason": "datasets library not installed"}]

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_per_subset = max(1, effective_max // len(_SUBSET_MAP))

    for (lang, type_filter), (collection, doc_type, jurisdiction) in _SUBSET_MAP.items():
        subset_label = f"{lang}_{type_filter}"
        try:
            ds = load_dataset(
                _DATASET_ID,
                lang,
                split="train",
                streaming=True,
                trust_remote_code=True,
                token=HF_TOKEN or None,
            )
        except Exception as exc:
            log.warning("MultiLegalPile %s failed: %s", subset_label, exc)
            events.append({"source": f"multi_legal_pile/{subset_label}", "status": "error", "reason": str(exc)})
            continue

        count = 0
        for example in ds:
            if count >= items_per_subset:
                break
            # Filter by document type within the language split
            example_type = str(example.get("type", "")).lower()
            if type_filter and example_type != type_filter:
                continue

            text = str(example.get("text", "")).strip()
            if len(text) < 100:
                continue
            if len(text) > max_bytes:
                text = text[:max_bytes]

            checksum = hashlib.sha256(text[:4096].encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=f"https://huggingface.co/datasets/{_DATASET_ID}",
                checksum=checksum,
                download_key=f"multi_legal_pile:{subset_label}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": doc_type,
                    "source_name": f"MultiLegalPile / {subset_label}",
                    "jurisdiction": jurisdiction,
                    "collection": collection,
                    "source_url": f"https://huggingface.co/datasets/{_DATASET_ID}",
                    "license_note": "CC-BY-4.0 (Commercial variant)",
                    "language": lang if lang != "eu" else "mul",
                    "hf_subset": subset_label,
                })
            chunks.extend(doc_chunks)
            count += 1
            time.sleep(0.01)

        events.append({"source": f"multi_legal_pile/{subset_label}", "status": "completed", "chunks": count})

    events.append({"source": "multi_legal_pile", "status": "completed", "total_chunks": len(chunks)})
    return chunks, events
