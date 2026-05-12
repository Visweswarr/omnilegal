"""Fast lexical fallback over the curated local JSONL corpus.

The vector store can be incomplete during demos or after rebuilds.  This module
keeps the small, curated ``data/corpus`` JSONL files queryable so flagship
research questions still surface primary and doctrinal authorities.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.config import (
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_REFERENCE_DATASET,
    COLLECTION_REFERENCE_DATASET_EU,
    COLLECTION_REFERENCE_DATASET_GLOBAL,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    CORPUS_DIR,
    OMNILEGAL_DIR,
)


_DIR_COLLECTIONS = {
    "case_law_global": COLLECTION_CASE_LAW_GLOBAL,
    "case_law_us": COLLECTION_CASE_LAW_US,
    "case_law_in": COLLECTION_CASE_LAW_IN,
    "case_law_eu": COLLECTION_CASE_LAW_EU,
    "case_law_uk": COLLECTION_CASE_LAW_UK,
    "case_law_ru": COLLECTION_CASE_LAW_RU,
    "case_law_il": COLLECTION_CASE_LAW_IL,
    "commentary_global": COLLECTION_COMMENTARY_GLOBAL,
    "intl_treaties": COLLECTION_INTL_TREATIES,
    "national_in": COLLECTION_NATIONAL_IN,
    "national_us": COLLECTION_STATUTES_US,
    "national_uk": COLLECTION_STATUTES_UK,
    "national_eu": COLLECTION_STATUTES_EU,
    "national_ru": COLLECTION_STATUTES_RU,
    "national_il": COLLECTION_STATUTES_IL,
    "statutes_in": COLLECTION_STATUTES_IN,
    "statutes_us": COLLECTION_STATUTES_US,
    "statutes_uk": COLLECTION_STATUTES_UK,
    "statutes_eu": COLLECTION_STATUTES_EU,
    "statutes_ru": COLLECTION_STATUTES_RU,
    "statutes_il": COLLECTION_STATUTES_IL,
}

_ALIASES = {
    COLLECTION_COMMENTARY: {COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL},
    COLLECTION_REFERENCE_DATASET: {
        COLLECTION_REFERENCE_DATASET,
        COLLECTION_REFERENCE_DATASET_GLOBAL,
        COLLECTION_REFERENCE_DATASET_EU,
    },
    COLLECTION_SHAW_PRIVATE: {COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY_GLOBAL},
}

_STOP_WORDS = {
    "about", "across", "after", "again", "against", "also", "among", "and",
    "any", "are", "can", "country", "countries", "did", "does", "each",
    "every", "for", "from", "have", "how", "into", "its", "jurisdiction",
    "jurisdictions", "law", "laws", "legal", "many", "more", "must", "not",
    "obligation", "obligations", "one", "their", "the", "these", "this",
    "those", "under", "what", "when", "where", "which", "who", "why", "with",
}

_CONCEPT_EXPANSIONS: list[tuple[re.Pattern[str], tuple[str, ...]]] = [
    (
        re.compile(r"\berga\s+omnes\b|\bcommunity\s+obligations?\b", re.IGNORECASE),
        (
            "obligations erga omnes",
            "Barcelona Traction",
            "Wall Advisory Opinion",
            "owed to the international community as a whole",
            "all states have a legal interest",
            "non-recognition",
            "non-assistance",
            "cooperation",
            "genocide",
            "aggression",
            "slavery",
            "racial discrimination",
            "self-determination",
        ),
    ),
    (
        re.compile(r"\bjus\s+cogens\b|\bperemptory\s+norms?\b", re.IGNORECASE),
        (
            "jus cogens",
            "peremptory norm",
            "non-derogable",
            "VCLT Article 53",
            "torture",
            "genocide",
            "slavery",
            "aggression",
            "apartheid",
            "self-determination",
        ),
    ),
    (
        re.compile(r"\bstate responsibility\b|\bresponsibility of states\b", re.IGNORECASE),
        (
            "ILC Articles on State Responsibility",
            "internationally wrongful act",
            "attribution",
            "Article 48",
            "serious breach",
            "cessation",
            "reparation",
        ),
    ),
]


def _infer_collection(path: Path) -> str:
    for part in reversed(path.parts):
        key = part.lower()
        if key in _DIR_COLLECTIONS:
            return _DIR_COLLECTIONS[key]
    return COLLECTION_COMMENTARY_GLOBAL


def _record_from_json(obj: dict[str, Any], path: Path, line_no: int) -> dict[str, Any] | None:
    text = str(obj.get("text") or obj.get("content") or obj.get("raw_text") or "").strip()
    if not text:
        return None

    nested = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    metadata = {
        key: value
        for key, value in obj.items()
        if key not in {"text", "content", "raw_text", "metadata"}
    }
    metadata.update(nested)
    metadata.setdefault("collection", _infer_collection(path))
    metadata.setdefault("source_name", obj.get("source_name") or obj.get("title") or obj.get("case_name") or path.stem)
    metadata.setdefault("citation", obj.get("citation") or metadata.get("source_name"))
    metadata.setdefault("jurisdiction", obj.get("jurisdiction") or metadata.get("jurisdiction") or "international")
    metadata.setdefault("doc_type", obj.get("doc_type") or metadata.get("doc_type") or "commentary")
    metadata.setdefault("source_role", metadata.get("doc_type"))
    metadata["local_corpus_path"] = str(path.relative_to(OMNILEGAL_DIR))
    metadata["local_corpus_line"] = line_no
    metadata["local_fallback"] = True
    return {"text": text, "metadata": metadata}


@lru_cache(maxsize=1)
def _load_records() -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    if not CORPUS_DIR.exists():
        return tuple(records)

    for path in sorted(CORPUS_DIR.rglob("*.jsonl")):
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                for line_no, line in enumerate(handle, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        record = _record_from_json(obj, path, line_no)
                        if record:
                            records.append(record)
        except OSError:
            continue
    return tuple(records)


def _query_phrases(query: str) -> list[str]:
    lowered = query.lower()
    phrases: list[str] = []
    for pattern, expansions in _CONCEPT_EXPANSIONS:
        if pattern.search(query):
            phrases.extend(expansions)
    for quoted in re.findall(r'"([^"]{3,80})"', query):
        phrases.append(quoted)
    for phrase in (
        "erga omnes",
        "jus cogens",
        "state responsibility",
        "self-determination",
        "racial discrimination",
        "human rights",
        "international community",
    ):
        if phrase in lowered:
            phrases.append(phrase)
    seen: set[str] = set()
    unique: list[str] = []
    for phrase in phrases:
        compact = " ".join(str(phrase).lower().split())
        if compact and compact not in seen:
            seen.add(compact)
            unique.append(compact)
    return unique


def _query_terms(query: str) -> set[str]:
    terms = {
        token
        for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in _STOP_WORDS
    }
    for phrase in _query_phrases(query):
        terms.update(
            token
            for token in re.findall(r"[a-z0-9]+", phrase)
            if len(token) > 2 and token not in _STOP_WORDS
        )
    return terms


def _expanded_collection_set(collections: list[str] | None) -> set[str] | None:
    if not collections:
        return None
    allowed: set[str] = set()
    for collection in collections:
        key = str(collection or "").upper()
        allowed.add(key)
        allowed.update(_ALIASES.get(key, set()))
    return allowed


def _score_record(query: str, record: dict[str, Any], terms: set[str], phrases: list[str]) -> float:
    metadata = record.get("metadata") or {}
    text = str(record.get("text") or "")
    haystack = " ".join(
        str(part or "")
        for part in [
            metadata.get("source_name"),
            metadata.get("citation"),
            metadata.get("title"),
            metadata.get("case_name"),
            metadata.get("doc_type"),
            metadata.get("collection"),
            text,
        ]
    ).lower()
    if not haystack:
        return 0.0

    phrase_hits = sum(1 for phrase in phrases if phrase and phrase in haystack)
    term_hits = sum(1 for term in terms if term in haystack)
    if phrase_hits == 0 and term_hits == 0:
        return 0.0

    source_haystack = " ".join(
        str(part or "")
        for part in [metadata.get("source_name"), metadata.get("citation"), metadata.get("title"), metadata.get("case_name")]
    ).lower()
    source_bonus = 1.0 if any(term in source_haystack for term in terms) else 0.0
    try:
        importance = float(metadata.get("importance_score") or 0.0)
    except (TypeError, ValueError):
        importance = 0.0

    exact_query_bonus = 1.5 if " ".join(query.lower().split()) in haystack else 0.0
    return (3.0 * phrase_hits) + (0.8 * term_hits) + source_bonus + (0.6 * importance) + exact_query_bonus


def search_local_corpus(
    query: str,
    *,
    collections: list[str] | None = None,
    k: int = 12,
) -> list[dict[str, Any]]:
    """Return local JSONL hits in the standard retriever dict shape."""
    terms = _query_terms(query)
    phrases = _query_phrases(query)
    if not terms and not phrases:
        return []

    allowed = _expanded_collection_set(collections)
    hits: list[dict[str, Any]] = []
    for record in _load_records():
        metadata = dict(record.get("metadata") or {})
        collection = str(metadata.get("collection") or "").upper()
        if allowed is not None and collection not in allowed:
            continue
        score = _score_record(query, record, terms, phrases)
        if score <= 0:
            continue
        hits.append({
            "text": record["text"],
            "score": score,
            "metadata": metadata,
        })

    hits.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return hits[: max(0, k)]
