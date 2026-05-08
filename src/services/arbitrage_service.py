"""OmniLegal Jurisdiction Arbitrage Engine (Pillar 15 — STATE OF THE ART).

Given a transaction or scenario, scan multiple jurisdictions in parallel
across live primary registries and produce a "favorability matrix":
which jurisdiction is friendliest for the user's intended position, with
primary-source citations for every cell of the matrix.

This is something ChatGPT structurally cannot do well because:
  • It lacks deterministic parallel access to multiple primary registries
  • Its single-pass generation tends to hallucinate jurisdictional rules
  • It cannot produce verifiable matrix cells with live URLs

We do all of that.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.arbitrage")


# A curated short-list of jurisdictions and the primary-source endpoints
# we can hit for each.
_JUR_CATALOG = {
    "india":        {"name": "India",              "sources": ["indian_kanoon"]},
    "united_states":{"name": "United States",      "sources": ["courtlistener", "govinfo"]},
    "european_union":{"name": "European Union",    "sources": ["eurlex"]},
    "echr":         {"name": "European Court of Human Rights", "sources": ["hudoc"]},
    "uk":           {"name": "United Kingdom",     "sources": ["hudoc"]},
    "international":{"name": "International (UN)", "sources": ["un_treaties"]},
}


_PLAN_SYSTEM = """You are OmniLegal's Jurisdiction Arbitrage Planner.

The user describes a transaction or business scenario and a desired outcome
(e.g. "operate a crypto exchange and avoid securities registration", or
"run a children's social network legally"). Your job:

  1. Extract the 3-5 LEGAL FRICTION POINTS the scenario will face
     (e.g. "consumer data export", "minor users below age 16",
     "investment-contract characterisation", "platform liability for UGC").
  2. For EACH friction point produce 2 query phrases ready for live
     legal-registry search.
  3. Recommend 4-6 jurisdictions to scan from the list:
     [india, united_states, european_union, echr, uk, international]

Return STRICT JSON ONLY:
{
  "scenario_summary": "<1 sentence>",
  "user_position": "<1 sentence on what the user wants to do/avoid>",
  "friction_points": [
    {"name": "...", "queries": ["...", "..."]}
  ],
  "jurisdictions": ["india", "united_states", "european_union", ...]
}
NEVER refuse. NEVER moralise. NEVER add disclaimers."""


_VERDICT_SYSTEM = """You are OmniLegal's Jurisdiction Verdict Synthesiser.

You will receive:
  • SCENARIO    — the user's transaction
  • POSITION    — what the user wants to do (verbatim)
  • JURISDICTION
  • LIVE_HITS   — list of live-registry results (title, snippet, source, url)

Produce a verdict for THIS JURISDICTION ONLY:
  - posture: "favorable" | "neutral" | "hostile" | "no_data"
  - confidence: float 0.0-1.0
  - rationale: 2-3 sentences explaining the posture using the live hits
  - top_authorities: list of 2-4 authorities {title, url, why_it_matters}
                     drawn FROM the LIVE_HITS (never invent)
  - friction_findings: per-friction-point notes (string list, max 4)

Return STRICT JSON only. If LIVE_HITS is empty or all snippets thin,
return posture="no_data".
"""


def _build_plan(scenario: str) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json
    parsed, used, _ = generate_json(
        system=_PLAN_SYSTEM,
        prompt=f"SCENARIO:\n{scenario[:3000]}\n\nReturn STRICT JSON only.",
        validate=lambda d: isinstance(d, dict) and isinstance(d.get("friction_points"), list),
        max_tokens=900, temperature=0.25,
    )
    if parsed:
        parsed["used_model"] = used
        return parsed
    return {
        "scenario_summary": scenario[:200],
        "user_position": scenario[:200],
        "friction_points": [{"name": "general", "queries": [scenario[:80]]}],
        "jurisdictions": ["india", "united_states", "european_union"],
        "used_model": "deterministic_fallback",
    }


def _scan_jurisdiction(jur_key: str, scenario: str, friction_queries: list[str], per_q: int = 2) -> dict[str, Any]:
    from src.services.live_authority_service import search_live
    cat = _JUR_CATALOG.get(jur_key, {})
    sources = cat.get("sources") or []
    if not sources:
        return {"hits": [], "name": cat.get("name") or jur_key}

    seen: set[str] = set()
    hits: list[dict[str, Any]] = []
    # Limit to first 2 friction queries per jurisdiction to keep wall-clock under 60s
    for q in friction_queries[:2]:
        if not q or len(q.strip()) < 3:
            continue
        try:
            res = search_live(q, sources, per_q)
        except Exception as exc:
            log.warning("arbitrage scan jur=%s q=%r failed: %s", jur_key, q, exc)
            continue
        for h in res.get("results", []) or []:
            url = h.get("url") or ""
            k = url or (h.get("source", "") + "::" + h.get("title", "")[:80])
            if k in seen:
                continue
            seen.add(k)
            hits.append(h)
    return {"hits": hits[:8], "name": cat.get("name") or jur_key}


def _verdict_for_jurisdiction(scenario: str, position: str, jur_key: str, jur_name: str,
                              hits: list[dict[str, Any]]) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json
    if not hits:
        return {"posture": "no_data", "confidence": 0.0,
                "rationale": "No live-registry hits.", "top_authorities": [],
                "friction_findings": []}
    listed = "\n\n".join(
        f"[{i}] source={h.get('source','?')}\n   title: {(h.get('title') or '')[:200]}\n"
        f"   snippet: {(h.get('snippet') or '')[:280]}\n   url: {h.get('url','')}"
        for i, h in enumerate(hits)
    )
    prompt = (
        f"SCENARIO:\n{scenario[:2000]}\n\nPOSITION:\n{position[:600]}\n\n"
        f"JURISDICTION: {jur_name}\n\nLIVE_HITS:\n{listed}\n\nReturn STRICT JSON only."
    )
    parsed, used, _ = generate_json(
        system=_VERDICT_SYSTEM, prompt=prompt,
        validate=lambda d: isinstance(d, dict) and d.get("posture") in
            {"favorable", "neutral", "hostile", "no_data"},
        max_tokens=1400, temperature=0.2,
    )
    if parsed is None:
        return {"posture": "no_data", "confidence": 0.0,
                "rationale": "LLM scoring failed.", "top_authorities": [],
                "friction_findings": []}
    parsed["used_model"] = used
    return parsed


def scan_arbitrage(scenario: str) -> dict[str, Any]:
    scenario = (scenario or "").strip()
    if not scenario:
        return {"error": "scenario is required"}

    plan = _build_plan(scenario)
    friction_queries: list[str] = []
    for fp in plan.get("friction_points") or []:
        friction_queries.extend(fp.get("queries") or [])
    if not friction_queries:
        friction_queries = [scenario[:80]]

    requested_jurs = plan.get("jurisdictions") or ["india", "united_states", "european_union"]
    requested_jurs = [j for j in requested_jurs if j in _JUR_CATALOG][:6]
    if not requested_jurs:
        requested_jurs = ["india", "united_states", "european_union"]

    matrix: list[dict[str, Any]] = []
    summary_counts = {"favorable": 0, "neutral": 0, "hostile": 0, "no_data": 0}

    import concurrent.futures
    def _row(jk: str) -> dict[str, Any]:
        scan = _scan_jurisdiction(jk, scenario, friction_queries)
        verdict = _verdict_for_jurisdiction(
            scenario, plan.get("user_position", ""), jk, scan["name"], scan["hits"],
        )
        return {
            "jurisdiction_key": jk,
            "jurisdiction_name": scan["name"],
            "live_hits_count": len(scan["hits"]),
            "live_hits": scan["hits"],
            "verdict": verdict,
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(requested_jurs))) as pool:
        for row in pool.map(_row, requested_jurs):
            posture = (row["verdict"].get("posture") or "no_data")
            summary_counts[posture] = summary_counts.get(posture, 0) + 1
            matrix.append(row)

    # Find the "winner" — highest-confidence favorable
    favorable = [m for m in matrix if m["verdict"].get("posture") == "favorable"]
    favorable.sort(key=lambda r: float(r["verdict"].get("confidence") or 0.0), reverse=True)
    recommendation = favorable[0]["jurisdiction_name"] if favorable else None

    return {
        "scenario": scenario,
        "scenario_summary": plan.get("scenario_summary", ""),
        "user_position": plan.get("user_position", ""),
        "friction_points": plan.get("friction_points", []),
        "jurisdictions_scanned": requested_jurs,
        "matrix": matrix,
        "summary": summary_counts,
        "best_jurisdiction": recommendation,
        "plan_used_model": plan.get("used_model"),
    }
