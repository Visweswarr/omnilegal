"""OmniLegal Council of Models service.

Sends the same legal question to three different LLMs in parallel
(Claude Sonnet 4.5 via Emergent, Gemini 2.5 Flash, Groq Llama-3.3-70B),
then asks a meta-judge (Groq Llama 70B) to synthesise a final verdict
that explicitly highlights agreements / disagreements.

The retrieval step is shared — every model sees the same RAG context so
their answers are directly comparable. Disagreement is the *signal*.
"""
from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from src.services.retrieval_qa import build_context, retrieve_passages

log = logging.getLogger("omnilegal.council")


_BASE_SYSTEM = """You are a member of the OmniLegal Council. Answer the
research question using ONLY the supplied retrieved context. Cite the
provided [C#] markers — never invent citations. Be precise, concise, and
willing to disagree with other models if the evidence supports your
view. Maximum 250 words.
"""


def _passages_to_context(passages: list[Any]) -> str:
    return build_context(passages)


def _passages_to_dicts(passages: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "marker": p.citation.marker,
            "source_name": p.citation.source_name,
            "jurisdiction": p.citation.jurisdiction,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:280],
        }
        for p in passages
    ]


def _format_user_prompt(query: str, context: str) -> str:
    return (
        f"QUESTION:\n{query}\n\n"
        f"RETRIEVED CONTEXT:\n{context[:6000]}\n\n"
        "Answer using only the context. Use [C#] markers."
    )


def _ask_claude(query: str, context: str) -> dict[str, Any]:
    from src.services.emergent_llm import generate_text

    started = _now()
    res = generate_text(
        system=_BASE_SYSTEM,
        prompt=_format_user_prompt(query, context),
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        timeout_seconds=45.0,
    )
    return {
        "model": "Claude Sonnet 4.5",
        "provider": "anthropic",
        "answer": res.text,
        "error": res.error,
        "elapsed_seconds": _elapsed(started),
        "model_id": res.model,
    }


def _ask_gemini(query: str, context: str) -> dict[str, Any]:
    from src.services.gemini_client import generate_gemini_content

    started = _now()
    res = generate_gemini_content(
        system=_BASE_SYSTEM,
        prompt=_format_user_prompt(query, context),
        temperature=0.15,
        max_output_tokens=900,
    )
    return {
        "model": "Gemini 2.5 Flash",
        "provider": "google",
        "answer": res.text,
        "error": res.error,
        "elapsed_seconds": _elapsed(started),
        "model_id": res.model,
    }


def _ask_groq(query: str, context: str) -> dict[str, Any]:
    from src.services.groq_client import generate_groq_chat

    started = _now()
    res = generate_groq_chat(
        messages=[
            {"role": "system", "content": _BASE_SYSTEM},
            {"role": "user", "content": _format_user_prompt(query, context)},
        ],
        max_tokens=900,
        temperature=0.15,
    )
    return {
        "model": "Llama 3.3 70B (Groq)",
        "provider": "groq",
        "answer": res.text,
        "error": res.error,
        "elapsed_seconds": _elapsed(started),
        "model_id": res.model,
    }


def _now() -> float:
    import time
    return time.time()


def _elapsed(started: float) -> float:
    import time
    return round(time.time() - started, 2)


_JUDGE_SYSTEM = """You are the Chief Justice of the OmniLegal Council.

You will receive three independent answers to the same legal research
question, plus the shared retrieved context. Produce a verdict that:

1. States the strongest, most-grounded answer drawn from the three.
2. Explicitly lists points of AGREEMENT among the three models.
3. Explicitly lists points of DISAGREEMENT, indicating which model holds
   which position and which evidence supports each.
4. Flags any model whose answer goes beyond the retrieved context.

Return STRICT JSON ONLY:

{
  "verdict": "<3-5 sentences, the synthesised final answer>",
  "agreements": ["...", "..."],
  "disagreements": [
    {"point": "...", "claude": "...", "gemini": "...", "groq": "..."}
  ],
  "ungrounded_warnings": ["<model>: <claim that lacks support>", "..."],
  "confidence": <float 0..1>
}
"""


def _ask_judge(query: str, context: str, answers: list[dict[str, Any]]) -> dict[str, Any]:
    from src.services.groq_client import generate_groq_chat

    parts = [f"QUESTION: {query}", "", f"RETRIEVED CONTEXT:\n{context[:5000]}", ""]
    for ans in answers:
        parts.append(f"=== {ans['model']} ===")
        parts.append(ans.get("answer") or f"(no answer; error: {ans.get('error', '')})")
        parts.append("")
    parts.append("Output STRICT JSON only.")
    user = "\n".join(parts)

    res = generate_groq_chat(
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": user[:14000]},
        ],
        max_tokens=1400,
        temperature=0.05,
        response_format={"type": "json_object"},
    )
    if not res.text:
        return {
            "verdict": "",
            "agreements": [],
            "disagreements": [],
            "ungrounded_warnings": [],
            "confidence": 0.0,
            "error": res.error,
        }
    import json
    import re

    raw = res.text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                pass
        return {
            "verdict": raw[:1200],
            "agreements": [],
            "disagreements": [],
            "ungrounded_warnings": [],
            "confidence": 0.0,
            "error": "judge returned non-JSON",
        }


def run_council(query: str, k: int = 6) -> dict[str, Any]:
    passages = retrieve_passages(query, k=k, comparative=True)
    context = _passages_to_context(passages)

    if not passages:
        return {
            "query": query,
            "answers": [],
            "verdict": "",
            "passages": [],
            "error": "no passages retrieved",
        }

    answers: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(_ask_claude, query, context),
            pool.submit(_ask_gemini, query, context),
            pool.submit(_ask_groq, query, context),
        ]
        for fut in concurrent.futures.as_completed(futures, timeout=70):
            try:
                answers.append(fut.result(timeout=70))
            except Exception as exc:
                answers.append({
                    "model": "unknown",
                    "provider": "unknown",
                    "answer": "",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": 0.0,
                })

    # Sort answers in fixed order: Claude → Gemini → Groq
    order = {"anthropic": 0, "google": 1, "groq": 2}
    answers.sort(key=lambda a: order.get(a.get("provider", ""), 99))

    judge = _ask_judge(query, context, answers)

    return {
        "query": query,
        "answers": answers,
        "judge": judge,
        "passages": _passages_to_dicts(passages),
    }
