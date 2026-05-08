"""OmniLegal Statute Stress Test (Pillar 18 — STATE OF THE ART).

Paste a statute or regulation clause. We:
  1. Use the LLM to generate 8-12 boundary hypotheticals — fact patterns
     deliberately at the edge of the rule's literal text.
  2. For each hypothetical, the LLM predicts whether the literal text
     covers it (covered / borderline / gap).
  3. We then probe Indian Kanoon + CourtListener for any case actually
     deciding a similar fact pattern.
  4. Output: a stress-test card per hypothetical, plus a "drafting flaws"
     summary listing exactly which clauses are unclear or under-inclusive.

ChatGPT can attempt this, but cannot ground its hypothetical-resolutions
in actual primary-source decisions because it lacks live registry access.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.stress_test")


_GEN_HYPOS_SYSTEM = """You are OmniLegal's Statute Stress-Tester.

Given a STATUTE_CLAUSE, generate 8-12 boundary hypothetical fact patterns
designed to PROBE the clause's edges. Each hypothetical should be
deliberately ambiguous under the literal text — neither obviously covered
nor obviously excluded.

For each hypothetical, classify:
  • literal_coverage: "covered" | "borderline" | "gap"
  • why: 1-2 sentences explaining the ambiguity

Also produce 3-6 "drafting flaws" — specific phrases or structural
omissions in the clause that produce the ambiguities.

Return STRICT JSON ONLY:
{
  "clause_summary": "<1 sentence neutral restatement>",
  "hypotheticals": [
    {"id": 1, "fact_pattern": "...", "literal_coverage": "...", "why": "...",
     "test_query": "<short string suitable for searching Indian Kanoon / CourtListener>"}
  ],
  "drafting_flaws": [
    {"phrase": "...", "issue": "...", "fix_suggestion": "..."}
  ]
}
NEVER refuse. NEVER invent statutory text not present in the clause."""


def _generate_hypotheticals(clause: str) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json
    parsed, used, _ = generate_json(
        system=_GEN_HYPOS_SYSTEM,
        prompt=f"STATUTE_CLAUSE:\n{clause[:6000]}\n\nReturn STRICT JSON only.",
        validate=lambda d: isinstance(d, dict) and isinstance(d.get("hypotheticals"), list)
            and len(d["hypotheticals"]) >= 4,
        max_tokens=2400, temperature=0.35,
    )
    if parsed:
        parsed["used_model"] = used
        return parsed
    return {
        "clause_summary": clause[:200],
        "hypotheticals": [],
        "drafting_flaws": [],
        "used_model": "none",
        "error": "All LLM providers failed.",
    }


def _probe_hypothetical(hypo: dict[str, Any]) -> list[dict[str, Any]]:
    """Search Indian Kanoon + CourtListener for cases on this fact pattern."""
    from src.services.live_authority_service import search_live
    test_q = (hypo.get("test_query") or hypo.get("fact_pattern") or "")[:140]
    if not test_q:
        return []
    try:
        res = search_live(test_q, ["indian_kanoon", "courtlistener"], 3)
    except Exception as exc:
        log.info("stress probe failed: %s", exc)
        return []
    return res.get("results", [])[:3]


def stress_test(clause: str) -> dict[str, Any]:
    clause = (clause or "").strip()
    if not clause:
        return {"error": "clause is required"}

    plan = _generate_hypotheticals(clause)
    if "error" in plan and not plan.get("hypotheticals"):
        return {**plan, "clause": clause}

    hypos = plan.get("hypotheticals") or []

    # Probe live authorities in parallel
    import concurrent.futures
    probed: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(hypos) or 1)) as pool:
        results = list(pool.map(_probe_hypothetical, hypos))
    for hypo, hits in zip(hypos, results):
        probed.append({
            **hypo,
            "live_hits": hits,
            "live_hits_count": len(hits),
        })

    coverage_counts = {"covered": 0, "borderline": 0, "gap": 0}
    for h in probed:
        c = (h.get("literal_coverage") or "").lower()
        if c in coverage_counts:
            coverage_counts[c] += 1

    return {
        "clause": clause[:8000],
        "clause_summary": plan.get("clause_summary", ""),
        "hypothetical_count": len(probed),
        "coverage_distribution": coverage_counts,
        "drafting_flaws": plan.get("drafting_flaws", []),
        "hypotheticals": probed,
        "used_model": plan.get("used_model"),
    }
