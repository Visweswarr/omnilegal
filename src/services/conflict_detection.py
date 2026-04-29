from __future__ import annotations

import os
import re

from src.schemas import Citation, ConflictResult, RetrievedPassage


def _pick_counterpart(domestic_text: str) -> tuple[RetrievedPassage | None, list[RetrievedPassage]]:
    from src.services.retrieval_qa import retrieve_passages

    passages = retrieve_passages(domestic_text, k=8, comparative=True)
    international = [
        passage for passage in passages if passage.citation.jurisdiction.lower() == "international"
    ]
    return (international[0] if international else None, passages)


def _lightweight_conflict_analysis(domestic_text: str, international_text: str) -> dict[str, object]:
    domestic = domestic_text.lower()
    international = international_text.lower()
    permissive = {"permit", "permits", "allow", "allows", "authorize", "authorizes"}
    prohibitive = {"prohibit", "prohibits", "bar", "bars", "forbid", "forbids", "no ", "not "}
    has_domestic_permission = any(term in domestic for term in permissive)
    has_international_prohibition = any(term in international for term in prohibitive)
    if has_domestic_permission and has_international_prohibition:
        return {
            "status": "Conflict Detected",
            "raw_label": "lexical_conflict",
            "confidence": 0.72,
            "explanation": "The domestic text appears permissive while the international text appears prohibitive.",
        }
    return {
        "status": "Neutral / Not Directly Addressed",
        "raw_label": "lexical_neutral",
        "confidence": 0.45,
        "explanation": "The lightweight checker did not find a direct permission/prohibition conflict.",
    }


def _run_entailment_analysis(domestic_text: str, international_text: str) -> dict[str, object]:
    if os.getenv("OMNILEGAL_ENABLE_HEAVY_MODELS", "0").lower() not in {"1", "true", "yes"}:
        return _lightweight_conflict_analysis(domestic_text, international_text)
    try:
        from src.models.entailment import detect_conflict
        return detect_conflict(domestic_text, international_text)
    except Exception as exc:
        raw = _lightweight_conflict_analysis(domestic_text, international_text)
        raw["explanation"] = f"{raw['explanation']} Heavy entailment unavailable: {type(exc).__name__}."
        return raw


def _extract_rationale_spans(reference_text: str, domestic_text: str, max_spans: int = 2) -> list[str]:
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", domestic_text.lower())
        if len(token) > 4
    }
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(reference_text.split()))
    ranked = []
    for sentence in sentences:
        score = sum(term in sentence.lower() for term in query_terms)
        if sentence.strip():
            ranked.append((score, sentence.strip()))
    ranked.sort(key=lambda item: item[0], reverse=True)
    spans = [sentence for _, sentence in ranked[:max_spans] if sentence]
    if not spans and reference_text:
        spans = [" ".join(reference_text.split())[:240]]
    return spans


def _normalize_label(status: str) -> tuple[str, str]:
    lowered = status.lower()
    if "conflict" in lowered or "contradiction" in lowered:
        return "conflict", "red"
    if "alignment" in lowered and "full" in lowered:
        return "alignment", "green"
    if "neutral" in lowered:
        return "neutral", "yellow"
    if "alignment" in lowered:
        return "qualified_alignment", "orange"
    return "neutral", "yellow"


def analyze_conflict(domestic_text: str, international_text: str | None = None) -> ConflictResult:
    if international_text is not None:
        counterpart_text = international_text
        counterpart_citation = None
    else:
        counterpart, _ = _pick_counterpart(domestic_text)
        counterpart_text = counterpart.content if counterpart else ""
        counterpart_citation = counterpart.citation if counterpart else None

    if not counterpart_text:
        return ConflictResult(
            domestic_text=domestic_text,
            international_text="",
            label="neutral",
            status="No International Counterpart Retrieved",
            confidence=0.0,
            color="yellow",
            explanation="No international authority could be retrieved for this clause, so the system cannot assess alignment or conflict yet.",
            counterpart_citation=None,
            rationale_spans=[],
            source_citations=[],
            raw_label="unavailable",
        )

    raw = _run_entailment_analysis(domestic_text, counterpart_text)
    label, color = _normalize_label(raw.get("status", "neutral"))
    rationale_spans = _extract_rationale_spans(counterpart_text, domestic_text)
    source_citations = [counterpart_citation] if counterpart_citation else []

    return ConflictResult(
        domestic_text=domestic_text,
        international_text=counterpart_text,
        label=label,  # type: ignore[arg-type]
        status=raw.get("status", "Neutral / Not Directly Addressed"),
        confidence=float(raw.get("confidence", 0.0)),
        color=color,
        explanation=raw.get("explanation", "No explanation provided."),
        counterpart_citation=counterpart_citation,
        rationale_spans=rationale_spans,
        source_citations=[citation for citation in source_citations if isinstance(citation, Citation)],
        raw_label=raw.get("raw_label", ""),
    )
