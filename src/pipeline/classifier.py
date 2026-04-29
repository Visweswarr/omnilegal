"""
Step 1 — Input classification.
Cascade: regex heuristics → DeBERTa zero-shot (only when regex confidence < 0.8).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import OMNILEGAL_ENABLE_HEAVY_MODELS, OMNILEGAL_ENABLE_ZERO_SHOT
from src.pipeline.state import PipelineStateDict
from src.models.heavy_nlp import get_zero_shot_classifier


_LABELS = ["question", "treaty", "news_claim", "statement"]

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

    if confidence < 0.8 and OMNILEGAL_ENABLE_HEAVY_MODELS and OMNILEGAL_ENABLE_ZERO_SHOT:
        try:
            clf = get_zero_shot_classifier(multi_label=False)
            if clf:
                result = clf(text[:512], candidate_labels=_LABELS)
                label = result["labels"][0]
                confidence = float(result["scores"][0])
            else:
                label, confidence = "question", 0.55
        except Exception as exc:
            print(f"Warning: zero-shot classifier failed: {exc}")
            if not confidence:
                label, confidence = "question", 0.5
    elif confidence < 0.8:
        # Local CPU default: avoid blocking Chainlit while large HF models download.
        label, confidence = "question", 0.55

    return {**state, "input_class": label, "input_confidence": confidence}
