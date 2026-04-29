from __future__ import annotations

from src.adapters.donor_registry import build_provenance
from src.adapters.summarization_patterns import build_extractive_summary
from src.schemas import BriefResult, BriefSection, Citation
from src.services.conflict_detection import analyze_conflict
from src.services.retrieval_qa import answer_question, dedupe_citations, retrieve_passages
from src.services.stance_prediction import predict_indian_stance


def _marker(citation: Citation | None) -> str:
    if citation is None:
        return "[C?]"
    return citation.marker or f"[{citation.source_name}]"


def _top_by_jurisdiction(issue: str):
    passages = retrieve_passages(issue, k=8, comparative=True)
    international = [passage for passage in passages if passage.citation.jurisdiction.lower() == "international"]
    indian = [passage for passage in passages if passage.citation.jurisdiction.lower() == "indian"]
    return passages, international, indian


def _digest(passages, fallback: str) -> str:
    if not passages:
        return fallback
    snippets = []
    for passage in passages[:2]:
        snippets.append(
            f"{_marker(passage.citation)} {passage.citation.source_name} (page {passage.citation.page}) "
            f"highlights {passage.citation.excerpt}."
        )
    return " ".join(snippets)


def generate_issue_brief(issue: str) -> BriefResult:
    passages, international, indian = _top_by_jurisdiction(issue)
    qa_result = answer_question(issue, k=6, use_groq=False)
    stance = predict_indian_stance(issue)
    extractive_fallback = build_extractive_summary(issue, passages)

    conflict = None
    if international and indian:
        conflict = analyze_conflict(indian[0].content, international[0].content)

    sections: list[BriefSection] = [BriefSection(heading="Issue", content=issue.strip())]

    if international:
        sections.append(
            BriefSection(
                heading="International Obligations",
                content=_digest(
                    international,
                    extractive_fallback or "No international authority was retrieved for this issue.",
                ),
            )
        )
    else:
        sections.append(
            BriefSection(
                heading="International Obligations",
                content="No international authority was retrieved for this issue.",
            )
        )

    if indian:
        sections.append(
            BriefSection(
                heading="Indian Domestic Position",
                content=_digest(
                    indian,
                    extractive_fallback or "No Indian authority was retrieved for this issue.",
                ),
            )
        )
    else:
        sections.append(
            BriefSection(
                heading="Indian Domestic Position",
                content="No Indian authority was retrieved for this issue.",
            )
        )

    if conflict:
        conflict_text = (
            f"The leading comparison is classified as **{conflict.label.replace('_', ' ')}** with confidence "
            f"{conflict.confidence:.2f}. {_marker(conflict.counterpart_citation)} {conflict.explanation}"
        )
    else:
        conflict_text = "The system could not retrieve both domestic and international authorities to compare alignment."
    sections.append(BriefSection(heading="Conflict or Alignment", content=conflict_text))

    sections.append(
        BriefSection(
            heading="Predicted Indian Stance",
            content=(
                f"Predicted label: **{stance.stance_label.replace('_', ' ')}** "
                f"(confidence {stance.confidence:.2f}). {stance.rationale}"
            ),
        )
    )

    talking_points = []
    if international:
        talking_points.append(
            f"- Cite {_marker(international[0].citation)} to frame the key international obligation."
        )
    if indian:
        talking_points.append(
            f"- Anchor India's position in {_marker(indian[0].citation)} and emphasize domestic constitutional consistency."
        )
    if conflict and conflict.label == "conflict":
        talking_points.append("- Push for narrower or more qualified drafting to avoid direct domestic legal friction.")
    elif conflict and conflict.label == "qualified_alignment":
        talking_points.append("- Support the principle, but insist on language that preserves Indian legal discretion and implementation flexibility.")
    else:
        talking_points.append("- Present India as supportive of legally grounded drafting and practical implementation.")
    sections.append(
        BriefSection(
            heading="Suggested MUN Talking Points",
            content="\n".join(talking_points),
        )
    )

    citations = dedupe_citations(
        [passage.citation for passage in passages]
        + (stance.top_domestic_authorities or [])
        + (stance.supporting_international_authorities or [])
        + ([conflict.counterpart_citation] if conflict and conflict.counterpart_citation else [])
    )

    citation_lines = []
    for citation in citations:
        citation_lines.append(
            f"{citation.marker or '[C?]'} {citation.source_name} "
            f"(Jurisdiction: {citation.jurisdiction}, Page: {citation.page})"
        )
    sections.append(
        BriefSection(
            heading="Citations",
            content="\n".join(citation_lines) if citation_lines else "No citations available.",
        )
    )

    return BriefResult(
        issue=issue,
        sections=sections,
        citations=citations,
        stance=stance,
        conflict=conflict,
        supporting_qa=qa_result,
        extractive_fallback=extractive_fallback or None,
        summary_mode="hybrid_chunked",
        provenance=build_provenance(
            "summarization",
            usage_mode="runtime",
            donor_ids=["summarization"],
        )
        + qa_result.provenance,
        used_model="hybrid_brief_generator",
    )
