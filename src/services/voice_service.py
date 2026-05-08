"""OmniLegal Voice Coach (Pillar 10) — backend chunk verifier.

The browser handles speech-to-text via the Web Speech API (free, no key),
then POSTs each sentence chunk here. We re-use the citation-forensics
engine to verify every claim. The response is small, so the UX feels live.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.voice")


def verify_chunk(text: str) -> dict[str, Any]:
    """Verify one streaming chunk (one or more sentences)."""
    text = (text or "").strip()
    if not text:
        return {"error": "Empty chunk."}
    try:
        from src.services.forensics_service import verify_text
        result = verify_text(text)
    except Exception as exc:
        log.exception("voice verify_chunk failed")
        return {"error": f"{type(exc).__name__}: {exc}", "text": text}

    # Compact response — only what the live UI needs.
    # forensics_service returns: summary{counts}, overall_grade, overall_score,
    # claims[{citation_text, status, overlap, best_match{...}}], annotated_segments.
    claims = result.get("claims") or []
    return {
        "text": text,
        "trust_score": result.get("overall_score", 0.0),
        "verdict": result.get("overall_grade", "unknown"),
        "summary_counts": result.get("summary") or {},
        "claims": [
            {
                "citation": c.get("citation_text") or "",
                "kind":     c.get("citation_kind") or "",
                "status":   c.get("status") or "unknown",
                "confidence": c.get("overlap") or 0.0,
                "match":   ((c.get("best_match") or {}).get("excerpt") or "")[:240],
                "source":  ((c.get("best_match") or {}).get("source_name") or ""),
            }
            for c in claims[:8]
        ],
        "annotated_segments": result.get("annotated_segments") or [],
    }


def finalize_session(transcript: str) -> dict[str, Any]:
    """Run a full forensics report over the complete transcript."""
    transcript = (transcript or "").strip()
    if not transcript:
        return {"error": "Empty transcript."}
    try:
        from src.services.forensics_service import verify_text
        return verify_text(transcript)
    except Exception as exc:
        log.exception("voice finalize failed")
        return {"error": f"{type(exc).__name__}: {exc}", "transcript": transcript}
