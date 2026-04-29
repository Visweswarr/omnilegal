from __future__ import annotations

import re

from src.schemas import RetrievedPassage


def _sentence_split(text: str) -> list[str]:
    return [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]


def build_extractive_summary(
    issue: str,
    passages: list[RetrievedPassage],
    sentence_limit: int = 4,
) -> str:
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", issue.lower())
        if len(token) > 3
    }

    ranked_sentences: list[tuple[float, str]] = []
    for passage in passages[:6]:
        citation = passage.citation
        for sentence in _sentence_split(passage.content)[:4]:
            score = sum(term in sentence.lower() for term in query_terms)
            score += max(0, 4 - passage.rank) * 0.4
            if citation.jurisdiction.lower() == "international":
                score += 0.15
            if citation.jurisdiction.lower() == "indian":
                score += 0.15
            ranked_sentences.append(
                (
                    score,
                    f"{citation.marker or '[C?]'} {sentence}",
                )
            )

    ranked_sentences.sort(key=lambda item: item[0], reverse=True)
    selected = []
    seen = set()
    for _, sentence in ranked_sentences:
        normalized = sentence.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        selected.append(sentence)
        if len(selected) >= sentence_limit:
            break

    return " ".join(selected)
