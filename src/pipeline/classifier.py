"""Step 1 - deterministic input classification."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.pipeline.state import PipelineStateDict


_QUESTION_RE = re.compile(r"\?\s*$")
_QUESTION_PREFIX_RE = re.compile(
    r"^\s*(tell me about|brief me on|explain|summari[sz]e|what is|what are|how does|how do|compare|is|are|can|does|do)\b",
    re.IGNORECASE,
)
_TREATY_RE = re.compile(r"Article\s+\d+.{0,40}Parties", re.IGNORECASE | re.DOTALL)
_NEWS_RE = re.compile(
    r"\b(bombed|struck|invaded|attacked|killed|shelled)\b.{0,80}\b[A-Z][a-z]+\b",
    re.DOTALL,
)


def classify_input(state: PipelineStateDict) -> PipelineStateDict:
    text = state["raw_input"]
    words = len(text.split())
    label = "statement"
    confidence = 0.0

    if _QUESTION_RE.search(text.strip()) or _QUESTION_PREFIX_RE.search(text.strip()):
        label, confidence = "question", 0.95
    elif words > 1500 and _TREATY_RE.search(text):
        label, confidence = "treaty", 0.9
    elif _NEWS_RE.search(text):
        label, confidence = "news_claim", 0.85

    if confidence < 0.8:
        label, confidence = "question", 0.55

    updated: PipelineStateDict = {**state, "input_class": label, "input_confidence": confidence}

    # Merged: run v2's mode/jurisdiction/doc_type classifier
    try:
        from pipeline_v2.classifier import analyze_query

        analysis = analyze_query(text)
        updated["mode"] = analysis.mode
        updated["jurisdictions"] = analysis.jurisdictions
        updated["doc_types"] = analysis.doc_types
    except Exception as exc:
        print(f"Warning: v2 mode classifier failed: {exc}")
        updated.setdefault("mode", "research")
        updated.setdefault("jurisdictions", [])
        updated.setdefault("doc_types", [])

    return updated
