"""Cross-encoder reranker for pipeline_v2.

Loads BAAI/bge-reranker-v2-m3 lazily on first use and rescores
candidate passages from the dense/hybrid retriever.

Usage:
    from pipeline_v2.reranker import rerank
    top = rerank(query, candidates, top_k=8)

Falls back gracefully (returns the input order) when:
  - the reranker library / model isn't available, or
  - OMNILEGAL_ENABLE_RERANKER is set to 0.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from pipeline_v2.settings import (
    ENABLE_RERANKER,
    RERANKER_BATCH_SIZE,
    RERANKER_MODEL,
    RERANKER_USE_FP16,
)

log = logging.getLogger("pipeline_v2.reranker")

_reranker: Any = None
_reranker_failed: bool = False


def _load_reranker() -> Any:
    """Load FlagReranker lazily. Returns None and disables further attempts on failure."""
    global _reranker, _reranker_failed
    if _reranker is not None:
        return _reranker
    if _reranker_failed or not ENABLE_RERANKER:
        return None
    try:
        from FlagEmbedding import FlagReranker  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        log.warning("FlagEmbedding not installed (%s) — reranker disabled.", exc)
        _reranker_failed = True
        return None
    try:
        log.info("Loading reranker model %s (fp16=%s, batch=%d)…",
                 RERANKER_MODEL, RERANKER_USE_FP16, RERANKER_BATCH_SIZE)
        _reranker = FlagReranker(
            RERANKER_MODEL,
            use_fp16=RERANKER_USE_FP16,
            batch_size=RERANKER_BATCH_SIZE,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Reranker model failed to load (%s) — falling back to dense order.", exc)
        _reranker_failed = True
        _reranker = None
    return _reranker


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    text_key: str = "text",
    score_key: str = "rerank_score",
) -> list[dict[str, Any]]:
    """Rescore `candidates` against `query` with bge-reranker-v2-m3.

    The original `score`/`final_score` fields are preserved; the reranker
    score is written to `rerank_score` and used as the primary sort key.
    Returns up to `top_k` candidates (all of them if `top_k` is None).
    """
    if not candidates:
        return []
    if not query or not query.strip():
        return candidates if top_k is None else candidates[:top_k]

    model = _load_reranker()
    if model is None:
        return candidates if top_k is None else candidates[:top_k]

    pairs = [[query, str(c.get(text_key) or "")] for c in candidates]
    try:
        raw_scores = model.compute_score(pairs, normalize=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("Reranker scoring failed (%s) — using dense order.", exc)
        return candidates if top_k is None else candidates[:top_k]

    # FlagReranker returns a float for a single pair, list for many.
    if isinstance(raw_scores, (int, float)):
        raw_scores = [float(raw_scores)]
    else:
        raw_scores = [float(s) for s in raw_scores]

    for cand, score in zip(candidates, raw_scores):
        cand[score_key] = score

    candidates.sort(key=lambda c: c.get(score_key, 0.0), reverse=True)
    return candidates if top_k is None else candidates[:top_k]


def is_available() -> bool:
    """Return True if the reranker is enabled and loadable."""
    if not ENABLE_RERANKER:
        return False
    if _reranker is not None:
        return True
    if _reranker_failed:
        return False
    return _load_reranker() is not None


__all__ = ["rerank", "is_available"]
