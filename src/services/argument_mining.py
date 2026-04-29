from __future__ import annotations

from src.adapters.argument_patterns import build_argument_spans
from src.adapters.donor_registry import build_provenance
from src.services.brief_generation import generate_issue_brief
from src.services.retrieval_qa import dedupe_citations, retrieve_passages
from src.schemas import ArgumentMap, BenchmarkRun, DebateCard, DebateLine


def build_argument_map(issue: str) -> ArgumentMap:
    passages = retrieve_passages(issue, k=8, comparative=True)
    spans = build_argument_spans(issue, passages, max_spans=8)
    citations = dedupe_citations([span.citation for span in spans if span.citation is not None])
    return ArgumentMap(
        issue=issue,
        spans=spans,
        citations=citations,
        provenance=build_provenance(
            "argument_mining",
            usage_mode="runtime",
            donor_ids=["mining_legal_arguments"],
        ),
        used_model="heuristic_argument_miner",
    )


def _line(text: str, purpose: str, citations):
    return DebateLine(text=text, purpose=purpose, citations=dedupe_citations([c for c in citations if c]))  # type: ignore[arg-type]


def build_debate_card(issue: str) -> DebateCard:
    brief = generate_issue_brief(issue)
    argument_map = build_argument_map(issue)

    opening_bullets = []
    likely_pois = []
    rebuttals = []
    red_lines = []

    if brief.stance and brief.stance.top_domestic_authorities:
        citation = brief.stance.top_domestic_authorities[0]
        opening_bullets.append(
            _line(
                f"India should frame this issue through {citation.marker or '[C?]'} {citation.source_name}, "
                f"which anchors the domestic legal basis for its position.",
                "opening",
                [citation],
            )
        )
    if brief.conflict and brief.conflict.counterpart_citation:
        citation = brief.conflict.counterpart_citation
        opening_bullets.append(
            _line(
                f"The international frame should begin with {citation.marker or '[C?]'} {citation.source_name}, "
                f"while stressing the {brief.conflict.label.replace('_', ' ')} relationship to Indian law.",
                "opening",
                [citation],
            )
        )
    for span in argument_map.spans[:2]:
        if span.citation:
            opening_bullets.append(
                _line(
                    f"Use this authority in speech: {span.text}",
                    "opening",
                    [span.citation],
                )
            )

    if brief.conflict and brief.conflict.counterpart_citation:
        likely_pois.append(
            _line(
                f"How do you reconcile your position with {brief.conflict.counterpart_citation.marker or '[C?]'} "
                f"{brief.conflict.counterpart_citation.source_name}?",
                "poi",
                [brief.conflict.counterpart_citation],
            )
        )
    for span in argument_map.spans:
        if span.label == "counterargument" and span.citation:
            likely_pois.append(
                _line(
                    f"An opposing delegate may argue: {span.text}",
                    "poi",
                    [span.citation],
                )
            )
            break
    if brief.stance and brief.stance.supporting_international_authorities:
        citation = brief.stance.supporting_international_authorities[0]
        likely_pois.append(
            _line(
                f"Expect a POI asking whether India will endorse the international obligation reflected in "
                f"{citation.marker or '[C?]'} {citation.source_name}.",
                "poi",
                [citation],
            )
        )

    if brief.stance:
        combined = brief.stance.top_domestic_authorities[:1] + brief.stance.supporting_international_authorities[:1]
        rebuttals.append(
            _line(
                f"India's answer is a {brief.stance.stance_label.replace('_', ' ')} position, not a rejection of law: "
                f"{brief.stance.rationale}",
                "rebuttal",
                combined,
            )
        )
    if brief.conflict and brief.conflict.rationale_spans:
        rebuttals.append(
            _line(
                f"If challenged, return to the retrieved legal record: {brief.conflict.rationale_spans[0]}",
                "rebuttal",
                [brief.conflict.counterpart_citation] if brief.conflict.counterpart_citation else [],
            )
        )
    for span in argument_map.spans:
        if span.label == "rebuttal" and span.citation:
            rebuttals.append(_line(span.text, "rebuttal", [span.citation]))
            break

    if brief.conflict and brief.conflict.label == "conflict":
        red_lines.append(
            _line(
                "Do not accept drafting that creates a direct conflict with the leading retrieved Indian authority.",
                "red_line",
                brief.stance.top_domestic_authorities if brief.stance else [],
            )
        )
    else:
        red_lines.append(
            _line(
                "Insist that final language stays tied to cited legal authorities rather than vague political commitments.",
                "red_line",
                brief.citations[:2],
            )
        )
    if brief.stance and brief.stance.supporting_international_authorities:
        red_lines.append(
            _line(
                "Preserve implementation discretion even when supporting the international norm.",
                "red_line",
                brief.stance.supporting_international_authorities[:1],
            )
        )

    return DebateCard(
        issue=issue,
        opening_bullets=opening_bullets[:4],
        likely_pois=likely_pois[:4],
        rebuttals=rebuttals[:4],
        negotiation_red_lines=red_lines[:3],
        argument_map=argument_map,
        brief=brief,
        provenance=build_provenance(
            "argument_mining",
            usage_mode="runtime",
            donor_ids=["mining_legal_arguments"],
        )
        + (brief.provenance or []),
        used_model="template_debate_coach",
    )
