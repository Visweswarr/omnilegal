from __future__ import annotations

import re
from collections import defaultdict

from src.schemas import RetrievedPassage


def build_passage_chunks(passages: list[RetrievedPassage], max_chars: int = 900) -> list[str]:
    grouped: dict[str, list[RetrievedPassage]] = defaultdict(list)
    for passage in passages:
        key = f"{passage.citation.source_name}|{passage.citation.page}"
        grouped[key].append(passage)

    chunks: list[str] = []
    for grouped_passages in grouped.values():
        label = grouped_passages[0].citation
        combined_parts = []
        total = 0
        for passage in grouped_passages:
            compact = " ".join(passage.content.split())
            remaining = max_chars - total
            if remaining <= 0:
                break
            snippet = compact[:remaining]
            combined_parts.append(snippet)
            total += len(snippet)
        chunks.append(
            f"{label.marker or '[C?]'} {label.source_name} "
            f"(Jurisdiction: {label.jurisdiction}, Page: {label.page}) "
            + " ".join(combined_parts)
        )
    return chunks


def retrieval_ids_for_passages(passages: list[RetrievedPassage]) -> list[str]:
    ids = []
    for passage in passages:
        citation = passage.citation
        safe_source = re.sub(r"[^a-z0-9]+", "_", citation.source_name.lower()).strip("_")
        ids.append(f"{safe_source}:{citation.page}:{passage.rank}")
    return ids
