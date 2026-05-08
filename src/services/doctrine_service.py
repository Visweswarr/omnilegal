"""OmniLegal Doctrine Time Machine (Pillar 08).

For a doctrine + jurisdiction, build a chronology of milestone cases and
classify each judgment's posture: introduced | expanded | narrowed |
applied | overruled.

Data sources:
  • Internal corpus retrieval (always)
  • Live registries (Indian Kanoon / CourtListener / HUDOC) when available
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.doctrine")


_TIMELINE_SYSTEM = """You are OmniLegal's Doctrine Historian.

Given a DOCTRINE, JURISDICTION, and a list of CANDIDATE judgments
(each with year, case name, court, and a snippet), produce a
chronological timeline. For each entry classify the court's posture
toward the doctrine:

  • introduced  — first authoritative articulation
  • expanded    — broadened scope or strengthened the rule
  • narrowed    — limited scope or carved out exceptions
  • applied     — applied the existing rule without modification
  • overruled   — explicitly overruled or rejected the doctrine

Return STRICT JSON ONLY:

{
  "doctrine": "...",
  "jurisdiction": "...",
  "inception_case": "<case name or empty>",
  "current_status": "<one sentence>",
  "summary": "<3-4 sentence narrative arc>",
  "milestones": [
    {"year": 1973, "case": "...", "court": "...",
     "posture": "introduced|expanded|narrowed|applied|overruled",
     "summary": "<2 sentences>", "citation": "<source/url if known>"}
  ]
}

CRITICAL RULES:
  • Sort milestones by year ascending.
  • Include 4-12 milestones. Even if the snippets are thin, classify each
    candidate using the case name, court, and year as signals — DO NOT
    drop candidates merely because the snippet is short.
  • Only the "introduced" posture should appear AT MOST ONCE.
  • If you genuinely cannot tell a candidate's posture, use "applied".
  • NEVER invent case names — only use names that appear in the candidates.
  • If candidates list is empty, return milestones: [].
"""


def _retrieve_candidates(doctrine: str, jurisdiction: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    # Local corpus
    try:
        from src.services.retrieval_qa import retrieve_passages
        passages = retrieve_passages(f"{doctrine} {jurisdiction}", k=10, comparative=True)
        for p in passages:
            candidates.append({
                "year": _extract_year(p.content),
                "case": p.citation.source_name,
                "court": p.citation.jurisdiction or "",
                "snippet": (p.citation.excerpt or p.content[:400])[:600],
                "source": "corpus",
                "url": "",
            })
    except Exception as exc:
        log.warning("doctrine corpus retrieval failed: %s", exc)

    # Live registries — use larger pull to give the LLM enough material
    try:
        from src.services.live_authority_service import search_live
        sources = _registry_sources_for(jurisdiction)
        if sources:
            live = search_live(doctrine, sources, 8)
            for hit in (live.get("results") or [])[:25]:
                candidates.append({
                    "year": _extract_year(hit.get("date") or "") or _extract_year(hit.get("title") or ""),
                    "case": hit.get("title") or "Unknown",
                    "court": hit.get("court") or hit.get("jurisdiction") or "",
                    "snippet": (hit.get("snippet") or "")[:600],
                    "source": hit.get("source", "live"),
                    "url": hit.get("url", ""),
                })
    except Exception as exc:
        log.warning("doctrine live retrieval failed: %s", exc)

    # Drop candidates with no usable signal at all
    cleaned = [c for c in candidates if (c.get("case") or "").strip()]
    return cleaned[:30]


def _registry_sources_for(jurisdiction: str) -> list[str]:
    j = (jurisdiction or "").lower()
    if any(t in j for t in ("india", "indian", "in")):
        return ["indian_kanoon"]
    if any(t in j for t in ("us", "united states", "america")):
        return ["courtlistener", "govinfo"]
    if any(t in j for t in ("uk", "britain", "england")):
        return ["hudoc"]
    if any(t in j for t in ("eu", "europe", "echr")):
        return ["hudoc", "eurlex"]
    return ["courtlistener", "indian_kanoon", "hudoc"]


_YEAR_RE = re.compile(r"\b(1[7-9]\d{2}|20\d{2})\b")


def _extract_year(text: str | None) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(str(text))
    return int(m.group(0)) if m else None


def _format_candidates(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "(no candidates)"
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(
            f"#{i}  year={c.get('year','?')}  case={c.get('case','?')}  "
            f"court={c.get('court','?')}  source={c.get('source','?')}\n"
            f"     snippet: {c.get('snippet','')[:300]}"
        )
    return "\n".join(lines)


def track_doctrine(doctrine: str, jurisdiction: str) -> dict[str, Any]:
    doctrine = (doctrine or "").strip()
    jurisdiction = (jurisdiction or "").strip() or "Comparative"
    if not doctrine:
        return {"error": "doctrine is required"}

    candidates = _retrieve_candidates(doctrine, jurisdiction)

    user_prompt = (
        f"DOCTRINE: {doctrine}\nJURISDICTION: {jurisdiction}\n\n"
        f"CANDIDATES:\n{_format_candidates(candidates)}\n\n"
        "Output STRICT JSON only."
    )

    from src.services.llm_waterfall import generate_json, attempts_as_dicts

    def _validate(d: dict[str, Any]) -> bool:
        return isinstance(d, dict) and isinstance(d.get("milestones"), list)

    parsed, used, attempts = generate_json(
        system=_TIMELINE_SYSTEM, prompt=user_prompt,
        validate=_validate, max_tokens=2400, temperature=0.2,
    )
    if parsed is not None:
        parsed["doctrine"] = parsed.get("doctrine") or doctrine
        parsed["jurisdiction"] = parsed.get("jurisdiction") or jurisdiction
        parsed["candidates_seen"] = len(candidates)
        parsed["used_model"] = used
        parsed["provider_attempts"] = attempts_as_dicts(attempts)
        try:
            parsed["milestones"] = sorted(
                parsed["milestones"],
                key=lambda m: int(m.get("year") or 0),
            )
        except Exception:
            pass
        return parsed

    log.warning("doctrine: all providers failed: %s", attempts_as_dicts(attempts))
    # Deterministic fallback: chronological list of candidates only
    sorted_candidates = sorted(
        [c for c in candidates if c.get("year")],
        key=lambda c: c["year"],
    )
    return {
        "doctrine": doctrine,
        "jurisdiction": jurisdiction,
        "inception_case": sorted_candidates[0]["case"] if sorted_candidates else "",
        "current_status": "LLM analysis unavailable.",
        "summary": "LLM unavailable; showing raw chronological candidates only.",
        "milestones": [
            {
                "year": c["year"], "case": c["case"], "court": c["court"],
                "posture": "applied", "summary": c["snippet"][:240],
                "citation": c.get("url", ""),
            }
            for c in sorted_candidates[:12]
        ],
        "candidates_seen": len(candidates),
        "used_model": "none",
        "error": (attempts[-1].error if attempts else "no providers attempted"),
        "provider_attempts": attempts_as_dicts(attempts),
    }
