"""OmniLegal Conflict Atlas service.

Generates a per-country verdict matrix for a legal topic, suitable for
rendering on a world map. Builds on top of
``analyze_multi_jurisdiction_conflict`` but expands the country list and
splits each jurisdiction's status into the four colour buckets the UI
expects (legal / restricted / illegal / no_data).

Returns a JSON-friendly dict:

    {
      "topic": "...",
      "international_position": "...",
      "verdict_human": "...",
      "countries": [
        {
          "iso_a3": "IND",
          "name": "India",
          "verdict": "restricted",
          "color": "amber",
          "confidence": 0.78,
          "headline": "...",
          "explanation": "...",
          "rationale_spans": [...],
          "international_position": "...",
          "domestic_position": "...",
          "vclt_27": false,
          "sources": [
              {"source_name": "...", "marker": "[C2]", "page": 14,
               "excerpt": "..."},
          ],
          "data_grounded": true
        },
        ...
      ],
      "label_counts": {...}
    }
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("omnilegal.atlas")


# Mapping of jurisdiction key → ISO-A3 + display name.  These are the
# corpora we have grounded data for.
GROUNDED_JURISDICTIONS = [
    {"key": "india",   "iso_a3": "IND", "name": "India"},
    {"key": "us",      "iso_a3": "USA", "name": "United States"},
    {"key": "uk",      "iso_a3": "GBR", "name": "United Kingdom"},
    {"key": "russia",  "iso_a3": "RUS", "name": "Russia"},
    {"key": "israel",  "iso_a3": "ISR", "name": "Israel"},
    {"key": "eu",      "iso_a3": "EUR", "name": "European Union"},
]


# Jurisdictions where we have NO local corpus but the user might still want
# an answer. We mark these clearly as "ai_inferred" and surface that to the
# UI so it's never confused with grounded data.
AI_INFERRED_JURISDICTIONS = [
    {"key": "germany",  "iso_a3": "DEU", "name": "Germany"},
    {"key": "france",   "iso_a3": "FRA", "name": "France"},
    {"key": "china",    "iso_a3": "CHN", "name": "China"},
    {"key": "japan",    "iso_a3": "JPN", "name": "Japan"},
    {"key": "brazil",   "iso_a3": "BRA", "name": "Brazil"},
    {"key": "australia","iso_a3": "AUS", "name": "Australia"},
    {"key": "canada",   "iso_a3": "CAN", "name": "Canada"},
    {"key": "south_africa","iso_a3": "ZAF", "name": "South Africa"},
    {"key": "nigeria",  "iso_a3": "NGA", "name": "Nigeria"},
    {"key": "mexico",   "iso_a3": "MEX", "name": "Mexico"},
    {"key": "saudi_arabia","iso_a3": "SAU", "name": "Saudi Arabia"},
    {"key": "uae",      "iso_a3": "ARE", "name": "United Arab Emirates"},
    {"key": "singapore","iso_a3": "SGP", "name": "Singapore"},
    {"key": "south_korea","iso_a3": "KOR", "name": "South Korea"},
    {"key": "iran",     "iso_a3": "IRN", "name": "Iran"},
    {"key": "turkey",   "iso_a3": "TUR", "name": "Turkey"},
    {"key": "indonesia","iso_a3": "IDN", "name": "Indonesia"},
    {"key": "pakistan", "iso_a3": "PAK", "name": "Pakistan"},
]


# ── Mapping ────────────────────────────────────────────────────────────────


_LABEL_TO_VERDICT = {
    "alignment":           ("legal",      "green"),
    "qualified_alignment": ("restricted", "amber"),
    "conflict":            ("illegal",    "red"),
    "neutral":             ("no_data",    "gray"),
}


def _verdict_from_label(label: str) -> tuple[str, str]:
    return _LABEL_TO_VERDICT.get(label, ("no_data", "gray"))


# ── AI-inferred fallback for non-grounded countries ────────────────────────


_INFER_SYSTEM = """You are a comparative-law analyst. Given a legal topic
and an international rule summary, determine — to the best of your training
data — whether the topic is LEGAL, RESTRICTED, or ILLEGAL in a specific
country and produce a one-sentence justification.

Return STRICT JSON only:
{
  "verdict": "legal|restricted|illegal|no_data",
  "headline": "<one short sentence>",
  "explanation": "<2-3 sentences citing the country's principal statute or doctrine>",
  "confidence": <float 0..1>
}
"""


def _infer_country(topic: str, country_name: str, international_position: str) -> dict[str, Any]:
    try:
        from src.services.emergent_llm import generate_with_fallback
    except Exception:
        return {
            "verdict": "no_data",
            "headline": "Insufficient data",
            "explanation": "AI-inferred analysis unavailable.",
            "confidence": 0.0,
        }

    user = (
        f"Topic: {topic}\n\n"
        f"International rule (for context):\n\"\"\"{international_position[:1200]}\"\"\"\n\n"
        f"Country: {country_name}\n\n"
        "Output STRICT JSON only — no markdown."
    )
    result = generate_with_fallback(
        system=_INFER_SYSTEM, prompt=user, timeout_seconds=20.0,
    )
    if not result.text:
        return {
            "verdict": "no_data",
            "headline": "AI inference failed",
            "explanation": result.error or "no response",
            "confidence": 0.0,
        }
    import json
    import re

    raw = result.text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return {
            "verdict": "no_data",
            "headline": "Could not parse AI response",
            "explanation": "",
            "confidence": 0.0,
        }
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {
            "verdict": "no_data",
            "headline": "Could not parse AI response",
            "explanation": "",
            "confidence": 0.0,
        }
    verdict = str(data.get("verdict", "no_data")).strip().lower()
    if verdict not in {"legal", "restricted", "illegal", "no_data"}:
        verdict = "no_data"
    return {
        "verdict": verdict,
        "headline": str(data.get("headline", "")).strip(),
        "explanation": str(data.get("explanation", "")).strip(),
        "confidence": float(data.get("confidence", 0.0) or 0.0),
        "used_model": f"{result.provider}/{result.model}",
    }


# ── Public entry point ─────────────────────────────────────────────────────


def build_atlas(
    topic: str,
    *,
    include_ai_inferred: bool = True,
) -> dict[str, Any]:
    """Build the world-map matrix for ``topic``.

    Runs the per-country entailment analyses in parallel for ~3× speed-up
    over the sequential ``analyze_multi_jurisdiction_conflict`` helper.
    """
    import concurrent.futures

    from src.services.conflict_detection import (
        _JURISDICTION_LABELS,  # noqa: WPS437
        _extract_rationale_spans,  # noqa: WPS437
        _normalize_label,  # noqa: WPS437
        _passage_to_dict,  # noqa: WPS437
        _retrieve_for_jurisdiction,  # noqa: WPS437
        _retrieve_international,  # noqa: WPS437
        _run_entailment_analysis,  # noqa: WPS437
        _VCLT_NOTE,  # noqa: WPS437
    )

    grounded_keys = [j["key"] for j in GROUNDED_JURISDICTIONS]

    international_passages = _retrieve_international(topic)
    international_text = "\n\n".join(
        f"{p.citation.source_name}: {p.content}" for p in international_passages
    )[:6000]
    international_summary = (
        international_passages[0].content[:600]
        if international_passages else ""
    )

    def _per_jur(jur_key: str) -> dict[str, Any]:
        passages = _retrieve_for_jurisdiction(topic, jur_key)
        domestic_text = "\n\n".join(
            f"{p.citation.source_name}: {p.content}" for p in passages
        )[:6000]
        if not domestic_text or not international_text:
            return {
                "jurisdiction_key": jur_key.lower(),
                "jurisdiction": _JURISDICTION_LABELS.get(jur_key.lower(), jur_key),
                "label": "neutral",
                "color": "yellow",
                "status": "No domestic authority retrieved" if not domestic_text else "No international counterpart retrieved",
                "confidence": 0.0,
                "explanation": (
                    f"No retrieved authority tagged as {jur_key} matched the query. "
                    "Try rephrasing or ingesting more sources for this jurisdiction."
                ) if not domestic_text else "No international authority could be retrieved.",
                "rationale_spans": [],
                "vclt_article_27_implicated": False,
                "international_position": international_summary,
                "domestic_position": passages[0].content[:600] if passages else "",
                "domestic_passages": [_passage_to_dict(p) for p in passages],
                "international_passages": [_passage_to_dict(p) for p in international_passages],
                "used_model": "lexical",
            }
        raw = _run_entailment_analysis(
            domestic_text=domestic_text,
            international_text=international_text,
            jurisdiction=_JURISDICTION_LABELS.get(jur_key.lower(), jur_key),
        )
        # Honesty: if the LLM failed and we only have a lexical guess (no
        # used_model returned by the analyser), downgrade to ``no_data``
        # rather than confidently mis-labelling.
        used_model_raw = str(raw.get("used_model") or "").lower()
        if used_model_raw in {"", "lexical", "lexical_unavailable", "none"}:
            return {
                "jurisdiction_key": jur_key.lower(),
                "jurisdiction": _JURISDICTION_LABELS.get(jur_key.lower(), jur_key),
                "label": "neutral",
                "color": "yellow",
                "status": "LLM analyser temporarily unavailable",
                "confidence": 0.0,
                "explanation": (
                    "The LLM entailment analyser is currently unavailable (likely a quota / "
                    "budget cap on the configured provider). We are showing 'no_data' rather "
                    "than a low-confidence lexical guess. Add balance to your Emergent universal "
                    "key (Profile → Universal Key → Add Balance) and retry."
                ),
                "rationale_spans": [],
                "vclt_article_27_implicated": False,
                "international_position": international_summary,
                "domestic_position": passages[0].content[:600] if passages else "",
                "domestic_passages": [_passage_to_dict(p) for p in passages],
                "international_passages": [_passage_to_dict(p) for p in international_passages],
                "used_model": "lexical_unavailable",
            }
        label, color = _normalize_label(raw.get("label", ""), raw.get("status", ""))
        return {
            "jurisdiction_key": jur_key.lower(),
            "jurisdiction": _JURISDICTION_LABELS.get(jur_key.lower(), jur_key),
            "label": label,
            "color": color,
            "status": raw.get("status") or label.replace("_", " ").title(),
            "confidence": float(raw.get("confidence", 0.0)),
            "explanation": raw.get("explanation", ""),
            "rationale_spans": raw.get("rationale_spans") or _extract_rationale_spans(international_text, domestic_text),
            "vclt_article_27_implicated": bool(raw.get("vclt_article_27_implicated", False)),
            "international_position": raw.get("international_position", "") or international_summary,
            "domestic_position": raw.get("domestic_position", "") or (passages[0].content[:600] if passages else ""),
            "used_model": raw.get("used_model", "lexical"),
            "domestic_passages": [_passage_to_dict(p) for p in passages],
            "international_passages": [_passage_to_dict(p) for p in international_passages],
        }

    overall_status_counts = {"alignment": 0, "qualified_alignment": 0, "conflict": 0, "neutral": 0}
    per_jurisdiction: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(grounded_keys))) as pool:
        futures = {pool.submit(_per_jur, key): key for key in grounded_keys}
        for fut in concurrent.futures.as_completed(futures, timeout=120):
            try:
                entry = fut.result(timeout=120)
                per_jurisdiction.append(entry)
                overall_status_counts[entry.get("label", "neutral")] = (
                    overall_status_counts.get(entry.get("label", "neutral"), 0) + 1
                )
            except Exception as exc:
                log.exception("per-jurisdiction failed for %s: %s", futures[fut], exc)

    # Re-order into our canonical sequence
    order = {j["key"]: i for i, j in enumerate(GROUNDED_JURISDICTIONS)}
    per_jurisdiction.sort(key=lambda e: order.get(e["jurisdiction_key"], 99))

    used_models = sorted({str(e.get("used_model")) for e in per_jurisdiction if e.get("used_model")})
    top_used_model = used_models[0] if used_models else "lexical"

    if overall_status_counts.get("conflict", 0) > 0:
        verdict = "conflict_detected"
        verdict_human = (
            "At least one domestic jurisdiction conflicts with the international rule. "
            "VCLT Article 27 may be implicated."
        )
    elif overall_status_counts.get("qualified_alignment", 0) > 0 and overall_status_counts.get("alignment", 0) == 0:
        verdict = "qualified_alignment"
        verdict_human = "All compared jurisdictions agree in principle but with limits or exceptions."
    elif overall_status_counts.get("alignment", 0) > 0:
        verdict = "alignment"
        verdict_human = "All compared jurisdictions align with the international rule."
    else:
        verdict = "neutral_or_unknown"
        verdict_human = (
            "No clear alignment or conflict could be assessed across the requested "
            "jurisdictions on the available retrieved authority."
        )

    countries: list[dict[str, Any]] = []
    label_counts = {"legal": 0, "restricted": 0, "illegal": 0, "no_data": 0,
                    "ai_inferred_legal": 0, "ai_inferred_restricted": 0,
                    "ai_inferred_illegal": 0}

    by_jur_key = {entry["jurisdiction_key"]: entry for entry in per_jurisdiction}

    for jur in GROUNDED_JURISDICTIONS:
        entry = by_jur_key.get(jur["key"], {})
        verdict_label, color = _verdict_from_label(entry.get("label", "neutral"))
        explanation = entry.get("explanation") or "No analysis available."
        if not entry or entry.get("status") in {
            "No domestic authority retrieved",
            "No international counterpart retrieved",
        }:
            verdict_label, color = "no_data", "gray"
            explanation = entry.get("explanation") or "No grounded authority retrieved."
        countries.append({
            "iso_a3": jur["iso_a3"],
            "name": jur["name"],
            "jurisdiction_key": jur["key"],
            "verdict": verdict_label,
            "color": color,
            "confidence": float(entry.get("confidence", 0.0) or 0.0),
            "headline": entry.get("status") or verdict_label.title(),
            "explanation": explanation,
            "rationale_spans": entry.get("rationale_spans", []),
            "international_position": entry.get("international_position", "") or international_summary,
            "domestic_position": entry.get("domestic_position", ""),
            "vclt_27": bool(entry.get("vclt_article_27_implicated", False)),
            "sources": entry.get("domestic_passages", []),
            "international_sources": entry.get("international_passages", []),
            "data_grounded": True,
            "used_model": entry.get("used_model", "lexical"),
        })
        label_counts[verdict_label] = label_counts.get(verdict_label, 0) + 1

    if include_ai_inferred and AI_INFERRED_JURISDICTIONS:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_infer_country, topic, jur["name"], international_summary): jur
                for jur in AI_INFERRED_JURISDICTIONS
            }
            inferred_by_key: dict[str, dict[str, Any]] = {}
            for fut in concurrent.futures.as_completed(futures, timeout=80):
                jur = futures[fut]
                try:
                    inferred_by_key[jur["key"]] = fut.result(timeout=60)
                except Exception:
                    inferred_by_key[jur["key"]] = {
                        "verdict": "no_data", "headline": "AI inference timed out",
                        "explanation": "", "confidence": 0.0,
                    }
        for jur in AI_INFERRED_JURISDICTIONS:
            inferred = inferred_by_key.get(jur["key"], {"verdict": "no_data"})
            verdict_label = inferred.get("verdict", "no_data")
            color = {"legal": "green", "restricted": "amber", "illegal": "red", "no_data": "gray"}.get(verdict_label, "gray")
            countries.append({
                "iso_a3": jur["iso_a3"],
                "name": jur["name"],
                "jurisdiction_key": jur["key"],
                "verdict": verdict_label,
                "color": color,
                "confidence": float(inferred.get("confidence", 0.0) or 0.0),
                "headline": inferred.get("headline", ""),
                "explanation": inferred.get("explanation", ""),
                "rationale_spans": [],
                "international_position": international_summary,
                "domestic_position": "",
                "vclt_27": False,
                "sources": [],
                "international_sources": [],
                "data_grounded": False,
                "used_model": inferred.get("used_model", ""),
            })
            if verdict_label != "no_data":
                key = f"ai_inferred_{verdict_label}"
                label_counts[key] = label_counts.get(key, 0) + 1
            else:
                label_counts["no_data"] = label_counts.get("no_data", 0) + 1

    return {
        "topic": topic,
        "international_position": international_summary,
        "international_sources": [_passage_to_dict(p) for p in international_passages],
        "verdict": verdict,
        "verdict_human": verdict_human,
        "vclt_article_27_note": _VCLT_NOTE,
        "countries": countries,
        "label_counts": label_counts,
        "used_model": top_used_model,
        "grounded_country_count": len(GROUNDED_JURISDICTIONS),
        "ai_inferred_country_count": len(AI_INFERRED_JURISDICTIONS) if include_ai_inferred else 0,
    }
