"""OmniLegal Adversarial Case Finder (Pillar 14 — STATE OF THE ART).

Given a user's argument or claim, retrieve the strongest cases from live
primary registries that DESTROY the user's position. Then rank by
adversarial damage and explain HOW the opposing counsel will weaponise
each precedent.

This is fundamentally different from "find supporting authority":
ChatGPT can simulate "what's the law on X" but cannot deterministically
search Indian Kanoon / CourtListener / HUDOC for cases pointing the OTHER
way — because that requires both (a) the LLM to invert the user's claim
into the strongest counter-proposition AND (b) live primary-source access
to verify the counter-cases actually exist.

Workflow:
  1. LLM extracts the user's core claim and inverts it (the "kill thesis").
  2. We hit Indian Kanoon, CourtListener, HUDOC, EUR-Lex in parallel with
     the kill-thesis as the query.
  3. For the top live results, the LLM annotates each with:
       - damage_score (0-1.0)
       - exact_quote_to_weaponise (from the snippet)
       - exploitation_strategy (how opposing counsel will use it)
  4. Returns ranked counter-precedents + a damage summary.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.adversarial")


_INVERT_SYSTEM = """You are OmniLegal's Adversarial Strategist.

Given the user's CLAIM (their legal position or argument), produce:
  - core_claim: a 1-sentence neutralised restatement of what the user is asserting
  - kill_thesis: the strongest 1-sentence opposing proposition a court could endorse
  - search_terms: 3-5 short, registry-friendly search phrases (string list) that
                  would surface cases supporting the kill_thesis
  - jurisdictions_to_attack: list of 2-4 jurisdiction tags from
                  ["india","us","uk","eu","echr","international"] — pick the
                  ones where authority hostile to the user's claim is likely.

Return STRICT JSON ONLY. Never refuse. Never moralise."""


_SCORE_SYSTEM = """You are OmniLegal's Adversarial Damage Scorer.

You will receive:
  • USER_CLAIM    — the user's position
  • KILL_THESIS   — the opposing proposition
  • CANDIDATES    — list of [N] live-registry cases (title, snippet, source, url)

For each candidate, return:
  - damage_score:        float 0.0-1.0  (how much it hurts the user; 1.0 = case-killer)
  - quote_to_weaponise:  the strongest single sentence FROM THE SNIPPET that
                         opposing counsel will quote in their brief
                         (use empty string if snippet too thin)
  - exploitation:        2 sentences explaining HOW opposing counsel uses it
  - is_overruled:        boolean — true ONLY if the snippet itself flags it as overruled

Ignore candidates that are off-topic. Skip those with damage_score < 0.25.

Return STRICT JSON:
{
  "ranked": [
    {"index": 0, "damage_score": 0.92, "quote_to_weaponise": "...",
     "exploitation": "...", "is_overruled": false},
    ...
  ],
  "summary": "<3-4 sentence executive summary of the worst 3 precedents>",
  "ammunition_count": <int>
}

NEVER fabricate quotes that aren't in the snippets. NEVER invent case names.
"""


def _invert_claim(claim: str) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json
    parsed, used, _ = generate_json(
        system=_INVERT_SYSTEM,
        prompt=f"USER_CLAIM:\n{claim[:3000]}\n\nReturn STRICT JSON only.",
        validate=lambda d: isinstance(d, dict) and bool(d.get("kill_thesis")),
        max_tokens=900, temperature=0.25,
    )
    if parsed:
        parsed["used_model"] = used
        return parsed
    # Deterministic fallback — naive negation
    return {
        "core_claim": claim[:240],
        "kill_thesis": f"NOT ({claim[:200]})",
        "search_terms": [claim[:80]],
        "jurisdictions_to_attack": ["india", "us", "echr"],
        "used_model": "deterministic_fallback",
    }


def _jur_to_sources(jurisdictions: list[str]) -> list[str]:
    out: set[str] = set()
    for j in jurisdictions or []:
        j = (j or "").lower()
        if j in ("india", "indian", "in"):
            out.add("indian_kanoon")
        elif j in ("us", "united states", "america"):
            out.update(["courtlistener", "govinfo"])
        elif j in ("uk", "britain"):
            out.add("hudoc")  # UK historically falls under ECHR enforcement
        elif j in ("eu", "europe"):
            out.update(["eurlex", "hudoc"])
        elif j in ("echr",):
            out.add("hudoc")
        elif j in ("international", "un"):
            out.add("un_treaties")
    if not out:
        out.update(["indian_kanoon", "courtlistener", "hudoc"])
    return sorted(out)


def _gather_candidates(search_terms: list[str], sources: list[str], per_term: int = 4) -> list[dict[str, Any]]:
    from src.services.live_authority_service import search_live
    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for term in (search_terms or [])[:5]:
        if not term or len(term.strip()) < 3:
            continue
        try:
            res = search_live(term, sources, per_term)
        except Exception as exc:
            log.warning("adversarial gather term=%r failed: %s", term, exc)
            continue
        for hit in res.get("results", []) or []:
            url = hit.get("url") or ""
            key = url or (hit.get("source", "") + "::" + hit.get("title", "")[:80])
            if key in seen:
                continue
            seen.add(key)
            candidates.append(hit)
    return candidates[:18]


def _score_candidates(claim: str, kill_thesis: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json, attempts_as_dicts
    if not candidates:
        return {"ranked": [], "summary": "No live-registry candidates retrieved.",
                "ammunition_count": 0, "used_model": "none", "provider_attempts": []}
    listed = "\n\n".join(
        f"[{i}] source={c.get('source','?')} jurisdiction={c.get('jurisdiction','?')}\n"
        f"   title: {(c.get('title') or '')[:200]}\n"
        f"   snippet: {(c.get('snippet') or '')[:380]}\n"
        f"   url: {c.get('url','')}"
        for i, c in enumerate(candidates)
    )
    prompt = (
        f"USER_CLAIM:\n{claim[:1500]}\n\n"
        f"KILL_THESIS:\n{kill_thesis[:600]}\n\n"
        f"CANDIDATES (n={len(candidates)}):\n{listed}\n\n"
        "Output STRICT JSON only."
    )
    parsed, used, attempts = generate_json(
        system=_SCORE_SYSTEM, prompt=prompt,
        validate=lambda d: isinstance(d, dict) and isinstance(d.get("ranked"), list),
        max_tokens=2400, temperature=0.2,
    )
    if parsed is None:
        return {"ranked": [], "summary": "Scoring LLM failed across all providers.",
                "ammunition_count": 0, "used_model": "none",
                "provider_attempts": attempts_as_dicts(attempts)}
    parsed["used_model"] = used
    parsed["provider_attempts"] = attempts_as_dicts(attempts)
    return parsed


def find_adversarial(claim: str) -> dict[str, Any]:
    claim = (claim or "").strip()
    if not claim:
        return {"error": "claim is required"}

    inversion = _invert_claim(claim)
    kill_thesis = inversion.get("kill_thesis") or claim
    search_terms = inversion.get("search_terms") or [claim[:80]]
    jurisdictions = inversion.get("jurisdictions_to_attack") or ["india", "us", "echr"]
    sources = _jur_to_sources(jurisdictions)

    candidates = _gather_candidates(search_terms, sources)
    scoring = _score_candidates(claim, kill_thesis, candidates)

    ranked: list[dict[str, Any]] = []
    seen_indices: set[int] = set()
    for entry in scoring.get("ranked") or []:
        try:
            idx = int(entry.get("index", -1))
            if idx < 0 or idx >= len(candidates):
                continue
            if idx in seen_indices:
                continue
            seen_indices.add(idx)
            c = candidates[idx]
            ranked.append({
                **c,
                "damage_score": float(entry.get("damage_score") or 0.0),
                "quote_to_weaponise": str(entry.get("quote_to_weaponise") or "")[:400],
                "exploitation": str(entry.get("exploitation") or "")[:600],
                "is_overruled": bool(entry.get("is_overruled")),
            })
        except Exception:
            continue
    ranked.sort(key=lambda r: r.get("damage_score", 0.0), reverse=True)

    return {
        "user_claim": claim,
        "core_claim": inversion.get("core_claim", ""),
        "kill_thesis": kill_thesis,
        "search_terms": search_terms,
        "jurisdictions_attacked": jurisdictions,
        "sources_queried": sources,
        "candidates_retrieved": len(candidates),
        "ammunition_count": len(ranked),
        "summary": scoring.get("summary", ""),
        "counter_precedents": ranked[:8],
        "inversion_used_model": inversion.get("used_model"),
        "scoring_used_model": scoring.get("used_model"),
        "provider_attempts": scoring.get("provider_attempts", []),
    }
