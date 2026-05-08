"""OmniLegal Argument Workbench / Red Team Mode (Pillar 11).

Take an opponent's argument, contract draft, or treaty clause and surface:
  - weak points (with quoted spans)
  - the strongest 5 counter-arguments, each with grounded supporting authorities
  - exploitable loopholes
  - best precedents to use in rebuttal

Pulls grounded passages from the local corpus where possible.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.redteam")


_REDTEAM_SYSTEM = """You are OmniLegal's Red Team architect.

You will receive:
  • TEXT (an opponent argument, contract clause, or treaty article)
  • MODE (argument | contract | treaty)
  • RETRIEVED AUTHORITY [S#] passages from the local corpus

Identify weaknesses and produce ammunition for the opposing side. Use [S#]
markers — never invent citations. If retrieved authority is empty, you may
still surface logical or doctrinal weaknesses, but mark anchor_citations as
empty arrays.

Return STRICT JSON ONLY (no markdown):

{
  "weak_points": [
    {"quote": "<short quote from TEXT>", "weakness_type": "vague|overbroad|self-contradictory|unsupported|circular|category-error", "why": "<2 sentences>"}
  ],
  "counter_arguments": [
    {"point": "<one sentence rebuttal>", "elaboration": "<2-3 sentences>", "anchor_citations": ["<source name from [S#]>", "..."]}
  ],
  "loopholes": [
    {"quote": "<quote from TEXT>", "exploitation_pattern": "<2 sentences explaining how to exploit>"}
  ],
  "best_precedents_for_rebuttal": [
    {"cite": "<source name>", "relevance_score": 0.0, "why_relevant": "<one sentence>"}
  ],
  "summary": "<3-4 sentence executive summary>"
}

Provide exactly 5 counter_arguments and 3-6 weak_points. Tone: clinical,
adversarial, formal. NEVER fabricate quotes — only quote spans that appear
verbatim in TEXT.
"""


def _passages_for(text: str) -> list[dict[str, Any]]:
    try:
        from src.services.retrieval_qa import retrieve_passages
    except Exception:
        return []
    # Use the first ~400 chars as the retrieval query
    seed = " ".join((text or "").split())[:400]
    if not seed:
        return []
    try:
        passages = retrieve_passages(seed, k=8, comparative=True)
    except Exception as exc:
        log.warning("redteam retrieval failed: %s", exc)
        return []
    return [
        {
            "marker": p.citation.marker,
            "source_name": p.citation.source_name,
            "jurisdiction": p.citation.jurisdiction,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:300],
        }
        for p in passages[:8]
    ]


def _passages_block(passages: list[dict[str, Any]]) -> str:
    if not passages:
        return "(no grounded passages retrieved)"
    return "\n\n".join(
        f"[S{i+1}] {p['source_name']} ({p.get('jurisdiction','?')}): {p['excerpt'][:400]}"
        for i, p in enumerate(passages)
    )


def _validate(packet: dict[str, Any]) -> bool:
    if not isinstance(packet, dict):
        return False
    for k in ("weak_points", "counter_arguments", "loopholes",
              "best_precedents_for_rebuttal", "summary"):
        if k not in packet:
            return False
    return isinstance(packet["counter_arguments"], list) and len(packet["counter_arguments"]) >= 1


def redteam(text: str, mode: str = "argument") -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"error": "Empty input."}
    mode = (mode or "argument").lower()
    if mode not in ("argument", "contract", "treaty"):
        mode = "argument"

    passages = _passages_for(text)
    user_prompt = (
        f"MODE: {mode}\n\nTEXT:\n{text[:6000]}\n\n"
        f"RETRIEVED AUTHORITY:\n{_passages_block(passages)}\n\n"
        "Output STRICT JSON only."
    )

    from src.services.llm_waterfall import generate_json, attempts_as_dicts
    parsed, used, attempts = generate_json(
        system=_REDTEAM_SYSTEM, prompt=user_prompt,
        validate=_validate, max_tokens=2400, temperature=0.25,
    )
    if parsed is not None:
        parsed["used_model"] = used
        parsed["mode"] = mode
        parsed["passages"] = passages
        parsed["provider_attempts"] = attempts_as_dicts(attempts)
        return parsed

    log.warning("redteam: all providers failed: %s", attempts_as_dicts(attempts))
    return {
        "mode": mode,
        "summary": "All LLM providers failed — could not generate red-team analysis.",
        "weak_points": [],
        "counter_arguments": [],
        "loopholes": [],
        "best_precedents_for_rebuttal": [],
        "passages": passages,
        "error": (attempts[-1].error if attempts else "no providers attempted"),
        "used_model": "none",
        "provider_attempts": attempts_as_dicts(attempts),
    }
