"""OmniLegal cross-jurisdiction conflict detector.

Two public entry points:

    analyze_conflict(domestic_text, international_text=None)
        Pairwise — original schema-compatible API. Returns ConflictResult.

    analyze_multi_jurisdiction_conflict(query, domestic_jurisdictions=...)
        New richer API — for a given research question, retrieves the
        position from ``COMMENTARY_GLOBAL`` / ``INTL_TREATIES`` (international
        baseline) and, for each requested domestic jurisdiction, retrieves
        the dominant treatise / statute passage and asks the LLM to grade the
        relationship as alignment / qualified_alignment / conflict / neutral.
        Always returns a JSON-serializable dict suitable for the FastAPI
        endpoint and the Chainlit conflict-mode renderer.

Both entry points enforce the **VCLT Article 27 frame** so the LLM is
reminded that, under public international law, a state cannot invoke its
domestic law as justification for failing to perform an international
obligation. This stops the model from collapsing real conflicts into
"both jurisdictions agree".
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from src.schemas import Citation, ConflictResult, RetrievedPassage

log = logging.getLogger("omnilegal.conflict")


# ── VCLT framing & prompts ─────────────────────────────────────────────────


_VCLT_NOTE = (
    "VCLT Article 27 reminder: a State may NOT invoke the provisions of its "
    "internal law as justification for its failure to perform a treaty. When "
    "domestic law diverges from a binding international rule, that is a "
    "genuine conflict — do not paper it over."
)

_LLM_SYSTEM = f"""You are OmniLegal's cross-jurisdiction conflict detector.
{_VCLT_NOTE}

Given a domestic-law text and an international-law text on (roughly) the
same subject, classify their relationship as ONE of:

    - alignment           : domestic law substantively mirrors / implements
                            the international rule.
    - qualified_alignment : domestic law agrees in principle but adds
                            limits, exceptions, or weaker enforcement.
    - conflict            : domestic law permits what international law
                            prohibits, prohibits what international law
                            requires, or otherwise materially diverges.
    - neutral             : the two texts address different questions, so
                            no comparison is meaningful.

Return STRICT JSON ONLY (no prose, no markdown), with this schema:
{{
  "label": "alignment|qualified_alignment|conflict|neutral",
  "status": "<one short sentence headline>",
  "confidence": <float 0..1>,
  "explanation": "<2-4 sentences justifying the label, citing specific
                  language from the two texts>",
  "rationale_spans": ["<short verbatim span from international text>", ...],
  "vclt_article_27_implicated": <true|false>,
  "international_position": "<one sentence summary of the international rule>",
  "domestic_position": "<one sentence summary of the domestic rule>"
}}
"""


_LLM_USER_TEMPLATE = """Domestic text (jurisdiction: {jurisdiction}):
\"\"\"{domestic}\"\"\"

International text:
\"\"\"{international}\"\"\"

Output JSON only.
"""


# ── Lightweight (no-LLM) fallback ──────────────────────────────────────────


_PERMISSIVE = {"permit", "permits", "allow", "allows", "authorize", "authorizes", "may"}
_PROHIBITIVE = {"prohibit", "prohibits", "bar", "bars", "forbid", "forbids", "shall not", "must not"}


def _lightweight_conflict_analysis(domestic_text: str, international_text: str) -> dict[str, Any]:
    domestic = domestic_text.lower()
    international = international_text.lower()
    has_domestic_permission = any(term in domestic for term in _PERMISSIVE)
    has_international_prohibition = any(term in international for term in _PROHIBITIVE)
    has_international_permission = any(term in international for term in _PERMISSIVE)
    has_domestic_prohibition = any(term in domestic for term in _PROHIBITIVE)

    if has_domestic_permission and has_international_prohibition:
        return {
            "label": "conflict",
            "status": "Domestic permission vs international prohibition",
            "confidence": 0.62,
            "explanation": (
                "The domestic clause uses permissive language while the "
                "international counterpart uses prohibitive language."
            ),
            "rationale_spans": [],
            "vclt_article_27_implicated": True,
            "international_position": "Prohibitive (per retrieved text).",
            "domestic_position": "Permissive (per provided text).",
            "raw_label": "lexical_conflict",
        }
    if has_domestic_prohibition and has_international_permission:
        return {
            "label": "qualified_alignment",
            "status": "Domestic stricter than international",
            "confidence": 0.55,
            "explanation": (
                "The domestic clause is more restrictive than the "
                "international one, which permits the activity."
            ),
            "rationale_spans": [],
            "vclt_article_27_implicated": False,
            "international_position": "Permissive (per retrieved text).",
            "domestic_position": "Prohibitive (per provided text).",
            "raw_label": "lexical_qualified",
        }
    return {
        "label": "neutral",
        "status": "No direct permission/prohibition divergence detected",
        "confidence": 0.4,
        "explanation": (
            "Lightweight lexical comparison did not reveal a clear "
            "permit↔prohibit clash; full LLM analysis disabled or unavailable."
        ),
        "rationale_spans": [],
        "vclt_article_27_implicated": False,
        "international_position": "",
        "domestic_position": "",
        "raw_label": "lexical_neutral",
    }


# ── LLM-based entailment ───────────────────────────────────────────────────


def _llm_enabled() -> bool:
    return os.getenv("OMNILEGAL_ENABLE_CONFLICT_LLM", "1").lower() in {"1", "true", "yes"}


def _safe_truncate(text: str, max_chars: int = 4500) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _call_llm_for_conflict(
    domestic_text: str,
    international_text: str,
    *,
    jurisdiction: str = "domestic",
) -> dict[str, Any] | None:
    """Run the conflict prompt through Emergent (Claude) → Gemini fallback."""
    try:
        from src.services.emergent_llm import generate_with_fallback
    except Exception as exc:  # noqa: BLE001
        log.warning("Emergent LLM client import failed: %s", exc)
        return None

    user_prompt = _LLM_USER_TEMPLATE.format(
        jurisdiction=jurisdiction,
        domestic=_safe_truncate(domestic_text),
        international=_safe_truncate(international_text),
    )
    result = generate_with_fallback(
        system=_LLM_SYSTEM,
        prompt=user_prompt,
        timeout_seconds=float(os.getenv("OMNILEGAL_CONFLICT_TIMEOUT_SECONDS", "35")),
    )
    if not result.text:
        log.info("LLM conflict call returned empty text: %s", result.error or "unknown")
        return None
    parsed = _parse_llm_json(result.text)
    if parsed:
        parsed["used_model"] = f"{result.provider}/{result.model}"
    return parsed


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    label = str(data.get("label", "")).strip().lower()
    if label not in {"alignment", "qualified_alignment", "conflict", "neutral"}:
        return None
    rationale_spans = data.get("rationale_spans") or []
    if isinstance(rationale_spans, str):
        rationale_spans = [rationale_spans]
    return {
        "label": label,
        "status": str(data.get("status") or "").strip()
                  or label.replace("_", " ").title(),
        "confidence": float(data.get("confidence") or 0.0),
        "explanation": str(data.get("explanation") or "").strip(),
        "rationale_spans": [str(span) for span in rationale_spans][:5],
        "vclt_article_27_implicated": bool(data.get("vclt_article_27_implicated", False)),
        "international_position": str(data.get("international_position") or "").strip(),
        "domestic_position": str(data.get("domestic_position") or "").strip(),
        "raw_label": label,
    }


def _run_entailment_analysis(
    domestic_text: str,
    international_text: str,
    *,
    jurisdiction: str = "domestic",
) -> dict[str, Any]:
    """Pick the strongest available analysis: heavy NLI → LLM → lexical."""
    if os.getenv("OMNILEGAL_ENABLE_HEAVY_MODELS", "0").lower() in {"1", "true", "yes"}:
        try:
            from src.models.entailment import detect_conflict

            heavy = detect_conflict(domestic_text, international_text)
            if heavy:
                return heavy
        except Exception as exc:  # noqa: BLE001
            log.info("heavy entailment unavailable, falling back: %s", exc)

    if _llm_enabled():
        llm_result = _call_llm_for_conflict(
            domestic_text, international_text, jurisdiction=jurisdiction,
        )
        if llm_result:
            return llm_result

    return _lightweight_conflict_analysis(domestic_text, international_text)


# ── Helpers shared with the legacy single-pair API ─────────────────────────


_LABEL_TO_COLOR = {
    "alignment": "green",
    "qualified_alignment": "orange",
    "conflict": "red",
    "neutral": "yellow",
}


def _normalize_label(label: str, status: str) -> tuple[str, str]:
    lowered = (label or "").lower().strip()
    if lowered in _LABEL_TO_COLOR:
        return lowered, _LABEL_TO_COLOR[lowered]
    blob = f"{status} {label}".lower()
    if "conflict" in blob or "contradiction" in blob:
        return "conflict", "red"
    if "qualified" in blob:
        return "qualified_alignment", "orange"
    if "alignment" in blob or "aligned" in blob:
        return "alignment", "green"
    return "neutral", "yellow"


def _extract_rationale_spans(reference_text: str, domestic_text: str, max_spans: int = 2) -> list[str]:
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", domestic_text.lower())
        if len(token) > 4
    }
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(reference_text.split()))
    ranked: list[tuple[int, str]] = []
    for sentence in sentences:
        score = sum(term in sentence.lower() for term in query_terms)
        if sentence.strip():
            ranked.append((score, sentence.strip()))
    ranked.sort(key=lambda item: item[0], reverse=True)
    spans = [sentence for _, sentence in ranked[:max_spans] if sentence]
    if not spans and reference_text:
        spans = [" ".join(reference_text.split())[:240]]
    return spans


def _pick_counterpart(domestic_text: str) -> tuple[RetrievedPassage | None, list[RetrievedPassage]]:
    from src.services.retrieval_qa import retrieve_passages

    passages = retrieve_passages(domestic_text, k=8, comparative=True)
    international = [
        passage for passage in passages if passage.citation.jurisdiction.lower() == "international"
    ]
    return (international[0] if international else None, passages)


# ── Pairwise public API (backward-compatible) ──────────────────────────────


def analyze_conflict(domestic_text: str, international_text: str | None = None) -> ConflictResult:
    if international_text is not None:
        counterpart_text = international_text
        counterpart_citation: Citation | None = None
    else:
        counterpart, _ = _pick_counterpart(domestic_text)
        counterpart_text = counterpart.content if counterpart else ""
        counterpart_citation = counterpart.citation if counterpart else None

    if not counterpart_text:
        return ConflictResult(
            domestic_text=domestic_text,
            international_text="",
            label="neutral",
            status="No International Counterpart Retrieved",
            confidence=0.0,
            color="yellow",
            explanation=(
                "No international authority could be retrieved for this clause, "
                "so the system cannot assess alignment or conflict yet."
            ),
            counterpart_citation=None,
            rationale_spans=[],
            source_citations=[],
            raw_label="unavailable",
        )

    raw = _run_entailment_analysis(domestic_text, counterpart_text)
    label, color = _normalize_label(raw.get("label", ""), raw.get("status", ""))
    rationale_spans = raw.get("rationale_spans") or _extract_rationale_spans(
        counterpart_text, domestic_text,
    )
    source_citations = [counterpart_citation] if counterpart_citation else []
    return ConflictResult(
        domestic_text=domestic_text,
        international_text=counterpart_text,
        label=label,  # type: ignore[arg-type]
        status=str(raw.get("status") or label.replace("_", " ").title()),
        confidence=float(raw.get("confidence", 0.0)),
        color=color,
        explanation=str(raw.get("explanation") or ""),
        counterpart_citation=counterpart_citation,
        rationale_spans=rationale_spans,
        source_citations=[c for c in source_citations if isinstance(c, Citation)],
        raw_label=str(raw.get("raw_label") or label),
    )


# ── Multi-jurisdiction comparison (the new flagship feature) ───────────────


_JURISDICTION_LABELS = {
    "india": "India",
    "indian": "India",
    "in": "India",
    "us": "United States",
    "usa": "United States",
    "united_states": "United States",
    "uk": "United Kingdom",
    "united_kingdom": "United Kingdom",
    "eu": "European Union",
    "russia": "Russia",
    "russian": "Russia",
    "ru": "Russia",
    "israel": "Israel",
    "israeli": "Israel",
    "il": "Israel",
}


_JURISDICTION_COLLECTIONS = {
    "india":   ["STATUTES_IN", "NATIONAL_IN", "CASE_LAW_IN"],
    "indian":  ["STATUTES_IN", "NATIONAL_IN", "CASE_LAW_IN"],
    "in":      ["STATUTES_IN", "NATIONAL_IN", "CASE_LAW_IN"],
    "us":      ["STATUTES_US", "NATIONAL_US", "CASE_LAW_US"],
    "usa":     ["STATUTES_US", "NATIONAL_US", "CASE_LAW_US"],
    "united_states": ["STATUTES_US", "NATIONAL_US", "CASE_LAW_US"],
    "uk":      ["STATUTES_UK", "NATIONAL_UK", "CASE_LAW_UK"],
    "united_kingdom": ["STATUTES_UK", "NATIONAL_UK", "CASE_LAW_UK"],
    "eu":      ["STATUTES_EU", "NATIONAL_EU", "CASE_LAW_EU"],
    "russia":  ["STATUTES_RU", "NATIONAL_RU", "CASE_LAW_RU"],
    "russian": ["STATUTES_RU", "NATIONAL_RU", "CASE_LAW_RU"],
    "ru":      ["STATUTES_RU", "NATIONAL_RU", "CASE_LAW_RU"],
    "israel":  ["STATUTES_IL", "NATIONAL_IL", "CASE_LAW_IL"],
    "israeli": ["STATUTES_IL", "NATIONAL_IL", "CASE_LAW_IL"],
    "il":      ["STATUTES_IL", "NATIONAL_IL", "CASE_LAW_IL"],
}

_INTERNATIONAL_COLLECTIONS = [
    "INTL_TREATIES", "COMMENTARY_GLOBAL", "SHAW_PRIVATE", "CASE_LAW_GLOBAL",
]


def _retrieve_for_jurisdiction(query: str, jurisdiction: str) -> list[RetrievedPassage]:
    """Retrieve top passages restricted to one jurisdiction's collections."""
    try:
        from src.services.retrieval_qa import retrieve_passages
    except Exception:  # noqa: BLE001
        return []

    norm = jurisdiction.lower().strip()
    target_collections = _JURISDICTION_COLLECTIONS.get(norm)
    if not target_collections:
        # Unknown jurisdiction key; fall back to broad retrieval and filter.
        candidates = retrieve_passages(query, k=12, comparative=True)
        label = _JURISDICTION_LABELS.get(norm, norm).lower()
        return [
            p for p in candidates
            if (p.citation.jurisdiction or "").lower().startswith(norm)
            or (p.citation.jurisdiction or "").lower() == label
        ][:4]
    passages = retrieve_passages(
        query, k=6, comparative=False, collections=target_collections,
    )
    return passages[:4]


def _retrieve_international(query: str) -> list[RetrievedPassage]:
    try:
        from src.services.retrieval_qa import retrieve_passages
    except Exception:
        return []
    passages = retrieve_passages(
        query, k=6, comparative=False, collections=_INTERNATIONAL_COLLECTIONS,
    )
    return passages[:4]


def _passage_to_dict(passage: RetrievedPassage) -> dict[str, Any]:
    return {
        "source_name": passage.citation.source_name,
        "marker": passage.citation.marker,
        "jurisdiction": passage.citation.jurisdiction,
        "page": passage.citation.page,
        "excerpt": passage.citation.excerpt or passage.content[:280],
    }


def analyze_multi_jurisdiction_conflict(
    query: str,
    domestic_jurisdictions: list[str] | None = None,
) -> dict[str, Any]:
    """Compare a query across one international baseline and N domestic
    jurisdictions, returning a structured payload suitable for both the
    Chainlit UI and the FastAPI endpoint."""
    domestic_jurisdictions = domestic_jurisdictions or [
        "india", "us", "uk", "russia", "israel",
    ]

    international_passages = _retrieve_international(query)
    international_text = "\n\n".join(
        f"{p.citation.source_name}: {p.content}" for p in international_passages
    )[:6000]
    international_summary = (
        international_passages[0].content[:600]
        if international_passages else ""
    )

    per_jurisdiction: list[dict[str, Any]] = []
    overall_status_counts = {"alignment": 0, "qualified_alignment": 0, "conflict": 0, "neutral": 0}

    for jur in domestic_jurisdictions:
        passages = _retrieve_for_jurisdiction(query, jur)
        domestic_text = "\n\n".join(
            f"{p.citation.source_name}: {p.content}" for p in passages
        )[:6000]
        if not domestic_text:
            per_jurisdiction.append({
                "jurisdiction": _JURISDICTION_LABELS.get(jur.lower(), jur),
                "jurisdiction_key": jur.lower(),
                "label": "neutral",
                "color": "yellow",
                "status": "No domestic authority retrieved",
                "confidence": 0.0,
                "explanation": (
                    f"No retrieved authority tagged as {jur} matched the query. "
                    "Try rephrasing or ingesting more sources for this jurisdiction."
                ),
                "rationale_spans": [],
                "vclt_article_27_implicated": False,
                "international_position": international_summary,
                "domestic_position": "",
                "domestic_passages": [],
                "international_passages": [_passage_to_dict(p) for p in international_passages],
            })
            overall_status_counts["neutral"] += 1
            continue
        if not international_text:
            per_jurisdiction.append({
                "jurisdiction": _JURISDICTION_LABELS.get(jur.lower(), jur),
                "jurisdiction_key": jur.lower(),
                "label": "neutral",
                "color": "yellow",
                "status": "No international counterpart retrieved",
                "confidence": 0.0,
                "explanation": (
                    "No international authority could be retrieved for this query, "
                    "so the conflict relationship cannot be assessed."
                ),
                "rationale_spans": [],
                "vclt_article_27_implicated": False,
                "international_position": "",
                "domestic_position": passages[0].content[:600] if passages else "",
                "domestic_passages": [_passage_to_dict(p) for p in passages],
                "international_passages": [],
            })
            overall_status_counts["neutral"] += 1
            continue

        raw = _run_entailment_analysis(
            domestic_text=domestic_text,
            international_text=international_text,
            jurisdiction=_JURISDICTION_LABELS.get(jur.lower(), jur),
        )
        label, color = _normalize_label(raw.get("label", ""), raw.get("status", ""))
        per_jurisdiction.append({
            "jurisdiction": _JURISDICTION_LABELS.get(jur.lower(), jur),
            "jurisdiction_key": jur.lower(),
            "label": label,
            "color": color,
            "status": raw.get("status") or label.replace("_", " ").title(),
            "confidence": float(raw.get("confidence", 0.0)),
            "explanation": raw.get("explanation", ""),
            "rationale_spans": raw.get("rationale_spans") or _extract_rationale_spans(
                international_text, domestic_text,
            ),
            "vclt_article_27_implicated": bool(raw.get("vclt_article_27_implicated", False)),
            "international_position": raw.get("international_position", "") or international_summary,
            "domestic_position": raw.get("domestic_position", "") or (passages[0].content[:600] if passages else ""),
            "used_model": raw.get("used_model", "lexical"),
            "domestic_passages": [_passage_to_dict(p) for p in passages],
            "international_passages": [_passage_to_dict(p) for p in international_passages],
        })
        overall_status_counts[label] = overall_status_counts.get(label, 0) + 1

    # Build a high-level verdict
    if overall_status_counts.get("conflict", 0) > 0:
        verdict = "conflict_detected"
        verdict_human = (
            f"At least one domestic jurisdiction conflicts with the international rule. "
            f"VCLT Article 27 may be implicated."
        )
    elif overall_status_counts.get("qualified_alignment", 0) > 0 and overall_status_counts.get("alignment", 0) == 0:
        verdict = "qualified_alignment"
        verdict_human = (
            "All compared jurisdictions agree in principle but with limits or exceptions."
        )
    elif overall_status_counts.get("alignment", 0) > 0:
        verdict = "alignment"
        verdict_human = "All compared jurisdictions align with the international rule."
    else:
        verdict = "neutral_or_unknown"
        verdict_human = (
            "No clear alignment or conflict could be assessed across the requested "
            "jurisdictions on the available retrieved authority."
        )

    return {
        "query": query,
        "international_position": international_summary,
        "international_passages": [_passage_to_dict(p) for p in international_passages],
        "per_jurisdiction": per_jurisdiction,
        "verdict": verdict,
        "verdict_human": verdict_human,
        "vclt_article_27_note": _VCLT_NOTE,
        "label_counts": overall_status_counts,
    }
