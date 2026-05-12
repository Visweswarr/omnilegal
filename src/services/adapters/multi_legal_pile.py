"""MultiLegalPile adapter for Hugging Face phase-5 legal reference ingestion.

Streams bounded samples from ``joelniklaus/MultiLegalPile_Wikipedia_Filtered``.
The dataset is opt-in via the remote ingestion command; callers should verify
upstream subcorpus licenses before redistributing derived corpora.
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
    COLLECTION_STATUTES_US,
    HF_TOKEN,
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
)

log = logging.getLogger(__name__)

_DATASET_ID = "joelniklaus/MultiLegalPile_Wikipedia_Filtered"
_CONFIGS = [
    "en_legislation",
    "en_caselaw",
    "fr_legislation",
    "de_legislation",
    "es_legislation",
    "it_legislation",
]

_JURISDICTION_ALIASES = {
    "gb": "uk",
    "uk": "uk",
    "united kingdom": "uk",
    "england": "uk",
    "england and wales": "uk",
    "us": "us",
    "usa": "us",
    "united states": "us",
    "eu": "eu",
    "european union": "eu",
    "fr": "fr",
    "fra": "fr",
    "france": "fr",
    "de": "de",
    "deu": "de",
    "germany": "de",
    "es": "es",
    "esp": "es",
    "spain": "es",
    "it": "it",
    "ita": "it",
    "italy": "it",
}


def _try_load_dataset() -> Any:
    try:
        from datasets import load_dataset  # type: ignore[import-untyped]
        return load_dataset
    except ImportError:
        log.warning("'datasets' library not installed - pip install datasets")
        return None


def _config_language(config: str) -> str:
    return config.split("_", 1)[0]


def _config_type(config: str) -> str:
    return "case_law" if "case" in config else "statute"


def _normalise_jurisdiction(example: dict[str, Any], config: str) -> str:
    raw = str(example.get("jurisdiction") or "").strip().lower()
    if raw in _JURISDICTION_ALIASES:
        return _JURISDICTION_ALIASES[raw]
    language = str(example.get("language") or _config_language(config)).strip().lower()
    if language == "fr":
        return "fr"
    if language in {"de", "es", "it", "nl", "pt"}:
        return language
    if language == "en":
        return "uk"
    return "eu"


def _doc_type(example: dict[str, Any], config: str) -> str:
    raw = str(example.get("type") or "").strip().lower()
    if "case" in raw:
        return "case_law"
    if "legislation" in raw or "statute" in raw or "code" in raw:
        return "statute"
    return _config_type(config)


def _collection_for_row(config: str, example: dict[str, Any]) -> tuple[str, str, str]:
    doc_type = _doc_type(example, config)
    jurisdiction = _normalise_jurisdiction(example, config)
    if doc_type == "case_law":
        if jurisdiction == "us":
            return COLLECTION_CASE_LAW_US, doc_type, jurisdiction
        if jurisdiction == "uk":
            return COLLECTION_CASE_LAW_UK, doc_type, jurisdiction
        return COLLECTION_CASE_LAW_EU, doc_type, jurisdiction
    if jurisdiction == "us":
        return COLLECTION_STATUTES_US, doc_type, jurisdiction
    if jurisdiction == "uk":
        return COLLECTION_STATUTES_UK, doc_type, jurisdiction
    return COLLECTION_STATUTES_EU, doc_type, jurisdiction


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
    """Stream MultiLegalPile samples and return ``(chunks, events)``."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 100)
    load_dataset = _try_load_dataset()
    if load_dataset is None:
        return [], [{"source": "multi_legal_pile", "status": "error", "reason": "datasets library not installed"}]

    from src.services.remote_sources import chunk_remote_text

    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    items_per_config = max(1, effective_max // len(_CONFIGS))

    for config in _CONFIGS:
        try:
            ds = load_dataset(
                _DATASET_ID,
                config,
                split="train",
                streaming=True,
                trust_remote_code=True,
                token=HF_TOKEN or None,
            )
        except Exception as exc:
            log.warning("MultiLegalPile %s failed: %s", config, exc)
            events.append({"source": f"multi_legal_pile/{config}", "status": "error", "reason": str(exc)})
            continue

        count = 0
        for example in ds:
            if count >= items_per_config:
                break
            if not isinstance(example, dict):
                continue
            text = str(example.get("text") or "").strip()
            if len(text) < 100:
                continue
            raw_bytes = text.encode("utf-8", errors="ignore")
            if len(raw_bytes) > max_bytes:
                text = raw_bytes[:max_bytes].decode("utf-8", errors="ignore")
                raw_bytes = text.encode("utf-8", errors="ignore")
            if not budget.reserve(len(raw_bytes)):
                events.append({"source": f"multi_legal_pile/{config}", "status": "budget_exhausted", "bytes": len(raw_bytes)})
                break

            collection, doc_type, jurisdiction = _collection_for_row(config, example)
            language = str(example.get("language") or _config_language(config) or "").strip().lower() or "mul"
            checksum = hashlib.sha256(text[:4096].encode("utf-8", errors="ignore")).hexdigest()
            doc_chunks = chunk_remote_text(
                record,
                plan,
                text,
                url=f"https://huggingface.co/datasets/{_DATASET_ID}",
                checksum=checksum,
                download_key=f"multi_legal_pile:{config}:{checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": doc_type,
                    "source_name": f"MultiLegalPile Wikipedia-filtered / {config}",
                    "jurisdiction": jurisdiction,
                    "collection": collection,
                    "source_url": f"https://huggingface.co/datasets/{_DATASET_ID}",
                    "license_note": "MultiLegalPile Wikipedia-filtered; verify upstream subcorpus license before redistribution.",
                    "language": language,
                    "hf_dataset": _DATASET_ID,
                    "hf_config": config,
                    "hf_subset": config,
                    "canonical_doc_id": f"hf:{_DATASET_ID}:{config}:{checksum[:16]}",
                    "source_fingerprint": checksum[:16],
                })
            chunks.extend(doc_chunks)
            count += 1
            time.sleep(0.01)

        events.append({"source": f"multi_legal_pile/{config}", "status": "completed", "items": count})

    events.append({"source": "multi_legal_pile", "status": "completed", "total_chunks": len(chunks)})
    return chunks, events
