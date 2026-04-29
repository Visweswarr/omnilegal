"""Retriever — hybrid search with hard jurisdiction + doc-type filter."""
from __future__ import annotations

import logging
import re
from typing import Any

from pipeline_v2.classifier import QueryAnalysis
from pipeline_v2.settings import MIN_RETRIEVAL_SCORE, TOP_K_DENSE, TOP_K_FINAL
from pipeline_v2.vector_store import hybrid_search

log = logging.getLogger("pipeline_v2.retriever")

_STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "have", "has", "do", "does",
    "did", "will", "would", "shall", "should", "may", "might", "can", "could",
    "about", "with", "from", "into", "through", "during", "before", "after",
    "above", "below", "to", "for", "of", "on", "at", "by", "in", "tell", "me",
    "what", "how", "when", "why", "where", "which", "this", "that", "these",
    "those", "and", "or", "but", "if", "not", "i", "you", "he", "she", "they",
}


def _key_terms(q: str) -> set[str]:
    words = re.findall(r"[a-z][a-z0-9\-]+", q.lower())
    return {w for w in words if len(w) > 2 and w not in _STOP}


def _variants(analysis: QueryAnalysis) -> list[str]:
    q = analysis.raw_query
    variants = [q]
    terms = re.findall(r"[a-zA-Z][a-zA-Z0-9\-]+", q)
    keywords = " ".join(w for w in terms if w.lower() not in _STOP)
    if keywords and keywords != q:
        variants.append(keywords)
    if analysis.mode == "tourist":
        variants.append(
            f"{keywords} consular notification international driving permit "
            "vienna convention foreign national traveller rights"
        )
    if analysis.mode == "conflict":
        variants.append(
            f"{keywords} treaty statute supremacy jus cogens pacta sunt servanda "
            "doctrine of incorporation monism dualism"
        )
    return variants


def _term_overlap_score(text: str, key_terms: set[str]) -> int:
    if not key_terms:
        return 0
    t = text.lower()
    return sum(1 for term in key_terms if term in t)


def retrieve(analysis: QueryAnalysis) -> list[dict[str, Any]]:
    jurisdiction_filter: list[str] = []
    if analysis.jurisdictions:
        jurisdiction_filter = list(analysis.jurisdictions)
        if analysis.include_international:
            jurisdiction_filter.append("INTL")
    # doc_types left unfiltered at the store level to avoid hiding relevant treaties.

    query_variants = _variants(analysis)
    key_terms = _key_terms(analysis.raw_query)

    bucket: dict[int, dict[str, Any]] = {}
    for v in query_variants:
        try:
            hits = hybrid_search(
                query=v,
                jurisdictions=jurisdiction_filter or None,
                doc_types=None,
                limit=TOP_K_DENSE,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("Hybrid search failed for variant %r: %s", v, e)
            continue
        for h in hits:
            pid = hash(h["text"][:160])
            existing = bucket.get(pid)
            if existing is None or h["score"] > existing["score"]:
                bucket[pid] = h

    # Fallback: if jurisdiction filter returned nothing, retry without it.
    if not bucket and jurisdiction_filter:
        log.info("No hits under jurisdiction filter — retrying unrestricted.")
        for v in query_variants:
            try:
                hits = hybrid_search(
                    query=v, jurisdictions=None, doc_types=None, limit=TOP_K_DENSE
                )
            except Exception:
                continue
            for h in hits:
                pid = hash(h["text"][:160])
                bucket.setdefault(pid, h)

    candidates = list(bucket.values())

    # Rerank: combine dense score + keyword overlap boost.
    for c in candidates:
        overlap = _term_overlap_score(c["text"], key_terms)
        c["term_overlap"] = overlap
        c["final_score"] = c["score"] + 0.04 * overlap

    candidates.sort(key=lambda h: h["final_score"], reverse=True)

    # Drop very low-score hits unless we have too few.
    strong = [c for c in candidates if c["score"] >= MIN_RETRIEVAL_SCORE]
    if len(strong) >= 3:
        candidates = strong

    # Cap per source_id to avoid one source dominating.
    per_source: dict[str, int] = {}
    deduped: list[dict[str, Any]] = []
    for c in candidates:
        sid = str(c.get("metadata", {}).get("source_id") or "?")
        if per_source.get(sid, 0) >= 3:
            continue
        per_source[sid] = per_source.get(sid, 0) + 1
        deduped.append(c)

    # Attach citation label.
    for idx, c in enumerate(deduped[:TOP_K_FINAL], start=1):
        c["label"] = f"S{idx}"

    return deduped[:TOP_K_FINAL]
