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
    "india",
    "indian",
    "compare",
    "comparison",
    "conflict",
    "alignment",
    "domestic",
    "international",
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
    international = [p for p in passages if p.citation.jurisdiction.lower() == "international"]
    indian = [p for p in passages if p.citation.jurisdiction.lower() == "indian"]
    remainder = [p for p in passages if p.citation.jurisdiction.lower() not in {"international", "indian"}]

    selected: list[RetrievedPassage] = []
    while len(selected) < limit and (international or indian):
        if international:
            selected.append(international.pop(0))
            if len(selected) >= limit:
                break
        if indian:
            selected.append(indian.pop(0))

    for passage in remainder + international + indian:
        if len(selected) >= limit:
            break
        selected.append(passage)

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

    retriever = get_hybrid_retriever(
        k=max(k * 2, 12 if comparative else k),
        collections=collections,
        filters=filters,
    )
    if not retriever:
        return []

    docs = retriever.invoke(normalize_query_text(query))
    passages = [_doc_to_passage(doc, rank + 1) for rank, doc in enumerate(docs)]

    if comparative:
        passages = _interleave_jurisdictions(passages, k)
    else:
        passages = passages[:k]

    return passages[:k]


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


def _render_fallback_answer(query: str, passages: list[RetrievedPassage], comparative: bool) -> str:
    if not passages:
        return "No relevant documents were retrieved for this query."

    international = [p for p in passages if p.citation.jurisdiction.lower() == "international"]
    indian = [p for p in passages if p.citation.jurisdiction.lower() == "indian"]
    passage_chunks = build_passage_chunks(passages[:4], max_chars=420)
    lines = []
    if comparative and international:
        top = international[0]
        lines.append(
            f"Internationally, the strongest retrieved authority is {top.citation.marker} "
            f"{top.citation.source_name} (page {top.citation.page}), which discusses "
            f"{top.citation.excerpt}."
        )
    if comparative and indian:
        top = indian[0]
        lines.append(
            f"On the Indian side, the leading retrieved authority is {top.citation.marker} "
            f"{top.citation.source_name} (page {top.citation.page}), which states "
            f"{top.citation.excerpt}."
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
