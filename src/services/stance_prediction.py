from __future__ import annotations

from src.schemas import StanceResult
from src.services.conflict_detection import analyze_conflict
from src.services.retrieval_qa import dedupe_citations, retrieve_passages


_STANCE_MAP = {
    "alignment": "support",
    "qualified_alignment": "qualified_support",
    "conflict": "oppose",
    "neutral": "insufficient_signal",
}


def predict_indian_stance(issue: str) -> StanceResult:
    passages = retrieve_passages(issue, k=8, comparative=True)
    indian = [passage for passage in passages if passage.citation.jurisdiction.lower() == "indian"]
    international = [
        passage for passage in passages if passage.citation.jurisdiction.lower() == "international"
    ]

    if not indian or not international:
        return StanceResult(
            issue=issue,
            stance_label="insufficient_signal",
            confidence=0.25,
            rationale="The system could not retrieve enough Indian and international authorities together to infer a defensible India-specific stance.",
            top_domestic_authorities=dedupe_citations([passage.citation for passage in indian[:3]]),
            supporting_international_authorities=dedupe_citations(
                [passage.citation for passage in international[:3]]
            ),
            evidence=[],
            used_model="baseline_mapping",
        )

    conflict = analyze_conflict(indian[0].content, international[0].content)
    stance_label = _STANCE_MAP.get(conflict.label, "insufficient_signal")
    confidence = min(0.95, max(0.35, conflict.confidence + 0.1))

    domestic_citations = dedupe_citations([passage.citation for passage in indian[:3]])
    international_citations = dedupe_citations([passage.citation for passage in international[:3]])

    rationale_map = {
        "support": "The leading Indian authority aligns with the retrieved international norm, so India can plausibly support the issue while grounding its intervention in domestic legality.",
        "qualified_support": "The strongest retrieved Indian authority partially aligns with the international norm, but the overlap is conditional rather than absolute. India would likely support the issue with caveats and drafting safeguards.",
        "oppose": "The leading Indian authority conflicts with the retrieved international norm, so India would likely resist or narrow the proposal unless the language is revised.",
        "insufficient_signal": "The retrieved authorities do not provide a strong enough domestic basis to infer a confident India-specific legal stance.",
    }

    evidence = []
    if domestic_citations:
        evidence.append(
            f"Top domestic authority: {domestic_citations[0].marker or '[C?]'} "
            f"{domestic_citations[0].source_name} (page {domestic_citations[0].page})."
        )
    if international_citations:
        evidence.append(
            f"Top international authority: {international_citations[0].marker or '[C?]'} "
            f"{international_citations[0].source_name} (page {international_citations[0].page})."
        )
    evidence.extend(conflict.rationale_spans[:2])

    return StanceResult(
        issue=issue,
        stance_label=stance_label,  # type: ignore[arg-type]
        confidence=confidence,
        rationale=rationale_map[stance_label],
        top_domestic_authorities=domestic_citations,
        supporting_international_authorities=international_citations,
        evidence=evidence,
        used_model="baseline_mapping",
    )
