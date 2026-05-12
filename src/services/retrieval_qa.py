from __future__ import annotations

import os
import re
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent.parent / ".env")
except ImportError:
    pass

try:
    from groq import Groq
except ImportError:
    Groq = None  # type: ignore[misc,assignment]

from src.adapters.donor_registry import build_provenance
from src.adapters.retrieval_patterns import build_passage_chunks
from src.rag.retriever import get_hybrid_retriever, normalize_query_text
from src.schemas import Citation, QaResult, RetrievedPassage

SYSTEM_PROMPT = """You are a highly analytical Model United Nations Legal Research Assistant.
Your role is to provide detailed, well-structured answers using ONLY the retrieved context documents.

Rules:
1. Base your answer exclusively on the provided context.
2. Cite sources using the provided citation markers.
3. If the context is incomplete, say what is missing.
4. Write like a legal researcher briefing a MUN delegate.
"""

_CLIENT = None
_COMPARATIVE_KEYWORDS = {
    "all countries",
    "all jurisdictions",
    "countries",
    "country",
    "india",
    "indian",
    "compare",
    "comparison",
    "conflict",
    "alignment",
    "domestic",
    "international",
    "jurisdiction",
    "jurisdictions",
    "treaty",
    "constitution",
}


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        if Groq is None:
            return None
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
        _CLIENT = Groq(api_key=api_key)
    return _CLIENT


def _is_comparative_query(query: str) -> bool:
    lowered = query.lower()
    return any(keyword in lowered for keyword in _COMPARATIVE_KEYWORDS)


def _clean_excerpt(text: str, limit: int = 360) -> str:
    compact = " ".join(text.split()).strip()
    return compact[:limit]


def _doc_to_passage(doc, rank: int) -> RetrievedPassage:
    # Support both new dict format {text, metadata} and old LangChain Document objects
    if isinstance(doc, dict):
        meta = doc.get("metadata") or {}
        content = doc.get("text") or doc.get("page_content") or ""
        score = doc.get("rerank_score") or doc.get("score")
    else:
        meta = getattr(doc, "metadata", {}) or {}
        content = getattr(doc, "page_content", "") or ""
        score = None

    source_name = meta.get("source_name") or meta.get("source_repo") or "Unknown"
    notes = "; ".join(
        part for part in [
            meta.get("type") or meta.get("document_type"),
            f"collection={meta.get('collection')}" if meta.get("collection") else "",
            f"repo={meta.get('source_repo')}" if meta.get("source_repo") else "",
            f"lang={meta.get('language')}" if meta.get("language") else "",
        ]
        if part
    )
    citation = Citation(
        marker=f"[C{rank}]",
        source_name=source_name,
        jurisdiction=meta.get("jurisdiction", "N/A"),
        page=meta.get("page", "?"),
        excerpt=_clean_excerpt(content),
        notes=notes or None,
    )
    relevance = float(score) if score is not None else max(0.0, 1.0 - ((rank - 1) * 0.08))
    return RetrievedPassage(
        citation=citation,
        content=content,
        rank=rank,
        relevance_score=relevance,
        document_type=meta.get("document_type") or meta.get("type"),
        provenance=build_provenance(
            "retrieval",
            usage_mode="runtime",
            donor_ids=["lleqa"],
        )
        + build_provenance(
            "retrieval",
            usage_mode="reference",
            donor_ids=["clerc", "bsard"],
        ),
    )


def _interleave_jurisdictions(passages: list[RetrievedPassage], limit: int) -> list[RetrievedPassage]:
    buckets: dict[str, list[RetrievedPassage]] = {}
    order: list[str] = []
    priority = ["international", "indian", "in", "us", "uk", "gb", "eu", "russia", "ru", "israel", "il"]
    for passage in passages:
        jurisdiction = str(passage.citation.jurisdiction or "unknown").lower()
        if jurisdiction not in buckets:
            buckets[jurisdiction] = []
            order.append(jurisdiction)
        buckets[jurisdiction].append(passage)

    ordered = [item for item in priority if item in buckets]
    ordered.extend(item for item in order if item not in set(ordered))

    selected: list[RetrievedPassage] = []
    seen_keys: set[tuple[str, str]] = set()
    while len(selected) < limit and any(buckets.values()):
        added = False
        for jurisdiction in ordered:
            bucket = buckets.get(jurisdiction) or []
            while bucket:
                passage = bucket.pop(0)
                key = (passage.citation.source_name, passage.citation.excerpt[:80])
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                selected.append(passage)
                added = True
                break
            if len(selected) >= limit:
                break
        if not added:
            break

    return selected


def retrieve_passages(
    query: str,
    k: int = 6,
    comparative: bool | None = None,
    *,
    collections: list[str] | None = None,
    filters: dict | None = None,
) -> list[RetrievedPassage]:
    if comparative is None:
        comparative = _is_comparative_query(query)

    effective_k = max(k, 10) if comparative else k
    retriever = get_hybrid_retriever(
        k=max(effective_k * 2, 20 if comparative else effective_k),
        collections=collections,
        filters=filters,
    )
    if not retriever:
        return []

    docs = retriever.invoke(normalize_query_text(query))
    passages = [_doc_to_passage(doc, rank + 1) for rank, doc in enumerate(docs)]

    if comparative:
        passages = _interleave_jurisdictions(passages, effective_k)
    else:
        passages = passages[:effective_k]

    return passages[:effective_k]


def build_context(passages: list[RetrievedPassage]) -> str:
    return "\n\n".join(build_passage_chunks(passages))


def dedupe_citations(citations: list[Citation]) -> list[Citation]:
    unique: list[Citation] = []
    seen: set[tuple[str, str, str]] = set()
    for citation in citations:
        key = (
            citation.source_name,
            str(citation.page),
            citation.excerpt[:120],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(citation)
    return unique


def _marker_for(passages: list[RetrievedPassage], *needles: str) -> str:
    lowered_needles = [needle.lower() for needle in needles]
    for passage in passages:
        haystack = " ".join(
            [
                passage.citation.source_name,
                passage.citation.excerpt,
                passage.content[:2000],
            ]
        ).lower()
        if any(needle in haystack for needle in lowered_needles):
            return passage.citation.marker or ""
    return passages[0].citation.marker if passages else ""


def _render_erga_fallback_answer(query: str, passages: list[RetrievedPassage]) -> str:
    barcelona = _marker_for(passages, "barcelona traction", "international community as a whole")
    wall = _marker_for(passages, "wall advisory", "non-recognition", "non-assistance")
    ilc = _marker_for(passages, "ILC Articles on Responsibility of States", "ILC Articles on State Responsibility")
    jus_cogens = _marker_for(passages, "jus cogens", "peremptory", "non-derogable")
    return (
        "Short answer: erga omnes obligations are not a separate checklist invented by each country. "
        "They are international obligations owed to the international community as a whole, so every state "
        "has a legal interest in their protection. The retrieved authorities identify the core family as "
        f"aggression, genocide, basic human rights including slavery and racial discrimination, and related "
        f"community-interest duties {barcelona}.\n\n"
        "For domestic law, the practical consequence is that states should not maintain or apply national laws "
        "that authorize or assist serious breaches. When an erga omnes or jus cogens breach exists, the sources "
        f"support duties of non-recognition, non-assistance, and cooperation to bring the unlawful situation to an end {wall}. "
        f"The state-responsibility materials also support invocation by non-injured states and collective responses to serious breaches {ilc}. "
        f"Where the obligation is also jus cogens, treaties or domestic rules cannot derogate from it {jus_cogens}.\n\n"
        "Country-by-country implementation still depends on each jurisdiction's constitution, statutes, and courts. "
        "The retrieved corpus is strongest on the international baseline; run the Comparative page for a per-jurisdiction IRAC matrix."
    )


def _render_fallback_answer(query: str, passages: list[RetrievedPassage], comparative: bool) -> str:
    if not passages:
        return "No relevant documents were retrieved for this query."

    if re.search(r"\berga\s+omnes\b|\bjus\s+cogens\b|\bperemptory\s+norms?\b", query, re.IGNORECASE):
        return _render_erga_fallback_answer(query, passages)

    passage_chunks = build_passage_chunks(passages[:4], max_chars=420)
    lines = []
    if comparative:
        grouped: dict[str, RetrievedPassage] = {}
        for passage in passages:
            jurisdiction = str(passage.citation.jurisdiction or "unknown")
            grouped.setdefault(jurisdiction, passage)
        if grouped:
            lines.append("The strongest retrieved authorities by jurisdiction/source group are:")
            for jurisdiction, top in list(grouped.items())[:6]:
                lines.append(
                    f"- {jurisdiction}: {top.citation.marker} {top.citation.source_name} "
                    f"(page {top.citation.page}) - {top.citation.excerpt}"
                )
    if not lines:
        top = passages[0]
        lines.append(
            f"The top retrieved source is {top.citation.marker} {top.citation.source_name} "
            f"(page {top.citation.page}), which says {top.citation.excerpt}."
        )
    if passage_chunks:
        lines.append(
            "Key retrieved record:\n"
            + "\n".join(f"- {chunk}" for chunk in passage_chunks[:3])
        )
    lines.append(
        "Use the cited passages below to drill deeper or run the issue through the conflict "
        "detector and brief generator for a more structured MUN-ready output."
    )
    return "\n\n".join(lines)


def answer_question(
    query: str,
    chat_history: list[dict] | None = None,
    k: int = 6,
    use_groq: bool | None = None,
    collections: list[str] | None = None,
    filters: dict | None = None,
) -> QaResult:
    comparative = _is_comparative_query(query)
    passages = retrieve_passages(
        query,
        k=k,
        comparative=comparative,
        collections=collections,
        filters=filters,
    )
    citations = dedupe_citations([passage.citation for passage in passages])
    provenance = build_provenance(
        "long_form_qa",
        usage_mode="runtime",
        donor_ids=["lleqa"],
    ) + build_provenance(
        "retrieval",
        usage_mode="reference",
        donor_ids=["clerc", "bsard"],
    )

    if not passages:
        return QaResult(
            query=query,
            answer="No relevant documents were found for this query.",
            citations=[],
            sources=[],
            used_model="retrieval_only",
            comparative=comparative,
            retrieval_strategy="qdrant_hybrid_rrf_rerank",
            provenance=provenance,
        )

    client = _get_client() if use_groq is not False else None
    if use_groq is None:
        client = _get_client()

    if client is None:
        return QaResult(
            query=query,
            answer=_render_fallback_answer(query, passages, comparative),
            citations=citations,
            sources=passages,
            used_model="hybrid_longform_template",
            used_groq=False,
            comparative=comparative,
            retrieval_strategy="qdrant_hybrid_rrf_rerank",
            provenance=provenance,
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for item in (chat_history or [])[-6:]:
        role = item.get("role")
        content = item.get("content")
        if role and content:
            messages.append({"role": role, "content": content})

    messages.append(
        {
            "role": "user",
            "content": (
                f"QUESTION: {query}\n\n"
                f"RETRIEVED CONTEXT:\n{build_context(passages)}\n\n"
                "Answer the question using the context only and cite sources with the provided markers."
            ),
        }
    )

    try:
        chat_completion = client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=1536,
            top_p=0.9,
        )
        answer_text = chat_completion.choices[0].message.content
        answer_text = re.sub(r"\[Source\s+(\d+)\]", r"[C\1]", answer_text)
        return QaResult(
            query=query,
            answer=answer_text,
            citations=citations,
            sources=passages,
            used_model="llama-3.3-70b-versatile",
            used_groq=True,
            comparative=comparative,
            retrieval_strategy="qdrant_hybrid_rrf_rerank",
            provenance=provenance,
        )
    except Exception:
        return QaResult(
            query=query,
            answer=_render_fallback_answer(query, passages, comparative),
            citations=citations,
            sources=passages,
            used_model="hybrid_longform_template",
            used_groq=False,
            comparative=comparative,
            retrieval_strategy="qdrant_hybrid_rrf_rerank",
            provenance=provenance,
        )
