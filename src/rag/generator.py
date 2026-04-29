"""Groq Llama-3.3-70B generator with streaming and citation formatting."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Generator

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import GROQ_API_KEY, GROQ_MODEL

_groq_client = None


def _get_groq():
    global _groq_client
    if _groq_client is None:
        from groq import Groq
        _groq_client = Groq(api_key=GROQ_API_KEY)
    return _groq_client


def build_rag_prompt(
    query: str,
    passages: list[dict[str, Any]],
    *,
    system_extra: str = "",
) -> list[dict[str, str]]:
    """Build messages list for Groq chat completion."""
    system = (
        "You are an international law research assistant. "
        "Answer questions using ONLY the provided source passages. "
        "Every factual claim must include a citation marker [N] referencing the passage number. "
        "Frame all outputs as research information only, not as counsel or instructions to act. "
        "If the passages do not contain sufficient information, state 'Insufficient evidence in retrieved sources.' "
        + system_extra
    )

    context_parts = []
    for i, p in enumerate(passages, 1):
        meta = p.get("metadata", {})
        source = meta.get("source_name", "Unknown")
        art = meta.get("article_number", "")
        citation = meta.get("citation", f"{source}" + (f", art. {art}" if art else ""))
        context_parts.append(f"[{i}] {citation}\n{p.get('text', '')}")

    context = "\n\n".join(context_parts)
    user = f"SOURCES:\n{context}\n\nQUESTION: {query}\n\nAnswer with inline [N] citation markers:"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def generate(
    query: str,
    passages: list[dict[str, Any]],
    *,
    system_extra: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> str:
    """Single-shot generation. Returns full answer string."""
    messages = build_rag_prompt(query, passages, system_extra=system_extra)
    client = _get_groq()
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def generate_stream(
    query: str,
    passages: list[dict[str, Any]],
    *,
    system_extra: str = "",
    max_tokens: int = 2048,
    temperature: float = 0.1,
) -> Generator[str, None, None]:
    """Streaming generation. Yields token chunks."""
    messages = build_rag_prompt(query, passages, system_extra=system_extra)
    client = _get_groq()
    stream = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


# ── Backward-compat wrapper ───────────────────────────────────────────────

def answer_question_stream(
    query: str,
    chat_history: list | None = None,
    k: int = 6,
) -> Generator[Any, None, None]:
    """Legacy shim used by existing Streamlit pages."""
    from src.rag.retriever import search_documents
    passages = search_documents(query, k=k)
    yield {
        "sources": [
            {
                "source_name": p["metadata"].get("source_name", "Unknown"),
                "jurisdiction": p["metadata"].get("jurisdiction", ""),
                "page": p["metadata"].get("page"),
                "content": p["text"][:500],
            }
            for p in passages
        ],
        "error": None if passages else "No relevant sources found.",
    }
    history_note = ""
    if chat_history:
        turns = "; ".join(
            f"{m.get('role','')}: {str(m.get('content',''))[:120]}"
            for m in chat_history[-4:]
        )
        history_note = f"Prior conversation context: {turns}. "
    for token in generate_stream(query, passages, system_extra=history_note):
        yield token
