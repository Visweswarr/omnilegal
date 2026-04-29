from __future__ import annotations

import re

from src.schemas import ArgumentSpan, Citation, RetrievedPassage


_AUTHORITY_TERMS = {"article", "court", "held", "charter", "constitution", "icj", "judge"}
_COUNTER_TERMS = {"however", "but", "unless", "subject", "provided", "although"}
_REBUTTAL_TERMS = {"not", "cannot", "does not", "no right", "reject", "resist"}
_CLAIM_TERMS = {"must", "shall", "obligation", "duty", "requires", "protects", "guarantees"}


def _sentence_split(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]


def _classify_sentence(sentence: str) -> str:
    lowered = sentence.lower()
    if any(term in lowered for term in _COUNTER_TERMS):
        return "counterargument"
    if any(term in lowered for term in _REBUTTAL_TERMS):
        return "rebuttal"
    if any(term in lowered for term in _AUTHORITY_TERMS):
        return "authority"
    if any(term in lowered for term in _CLAIM_TERMS):
        return "claim"
    if "because" in lowered or "since" in lowered or "therefore" in lowered:
        return "premise"
    return "policy"


def build_argument_spans(
    issue: str,
    passages: list[RetrievedPassage],
    max_spans: int = 8,
) -> list[ArgumentSpan]:
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", issue.lower())
        if len(token) > 3
    }

    ranked: list[tuple[float, ArgumentSpan]] = []
    for passage in passages[:6]:
        citation: Citation = passage.citation
        for sentence in _sentence_split(passage.content)[:4]:
            score = sum(term in sentence.lower() for term in query_terms)
            score += max(0, 5 - passage.rank) * 0.35
            if citation.jurisdiction.lower() in {"international", "indian"}:
                score += 0.2
            span = ArgumentSpan(
                label=_classify_sentence(sentence),  # type: ignore[arg-type]
                text=sentence,
                citation=citation,
                importance=round(score, 3),
                notes=f"Derived from {citation.source_name}",
            )
            ranked.append((score, span))

    ranked.sort(key=lambda item: item[0], reverse=True)
    spans: list[ArgumentSpan] = []
    seen = set()
    for _, span in ranked:
        normalized = span.text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        spans.append(span)
        if len(spans) >= max_spans:
            break
    return spans
