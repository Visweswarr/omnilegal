"""
Step 5 — grounded synthesis for OmniLegal Codex.

This node turns retrieved passages plus jurisdiction analysis into a structured
draft. It prefers a deterministic, gap-aware fallback when runtime LLM providers
are unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import LEGAL_RESEARCH_SHORT_DISCLAIMER
from src.pipeline.state import PipelineStateDict
from src.services.answer_format import format_answer_sections
from src.services.authority import authority_rank, infer_authority_tier, is_merits_citable_tier


def _clean_source_excerpt(text: str, *, limit: int = 220) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    if "\n\n" in text:
        candidate = " ".join(text.split("\n\n", 1)[1].split())
        if candidate:
            raw = candidate
    raw = raw.replace("Source URL:", "").strip()
    return raw[:limit]


def _normalize_jurisdiction(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    mapping = {
        "india": "in",
        "indian": "in",
        "russia": "ru",
        "russian federation": "ru",
        "russian": "ru",
        "united states": "us",
        "american": "us",
        "united kingdom": "gb",
        "uk": "gb",
        "british": "gb",
        "international": "international",
    }
    return mapping.get(cleaned, cleaned)

def _temporal_score(passage: dict[str, Any]) -> float:
    meta = passage.get("metadata", {}) or {}
    base = float(passage.get("score", 0.0) or 0.0)
    year = meta.get("year")
    importance = float(meta.get("importance_score", 0.0) or 0.0)
    recency = 0.0
    if isinstance(year, int) and year > 0:
        recency = min(1.0, max(0.0, (year - 1900) / 150))
    return base + (0.2 * importance) + (0.1 * recency)


def _apply_temporal_weighting(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for passage in passages:
        enriched = dict(passage)
        enriched["temporal_score"] = _temporal_score(enriched)
        ranked.append(enriched)
    return sorted(ranked, key=lambda item: item.get("temporal_score", item.get("score", 0.0)), reverse=True)


def _detected_case_names(state: dict[str, Any]) -> list[str]:
    entities = (state.get("entities") or {}).get("entities") or []
    seen: set[str] = set()
    names: list[str] = []
    for entity in entities:
        if entity.get("label", "").lower() in {
            "legal_case",
            "legal case",
            "icj case",
            "arbitration case",
            "international arbitration",
        } and entity["text"] not in seen:
            seen.add(entity["text"])
            names.append(entity["text"])
    return names


def _state_jurisdictions(state: PipelineStateDict) -> list[str]:
    values: list[str] = []
    scenario_context = ((state.get("entities") or {}).get("scenario_context") or {})
    for code in [
        scenario_context.get("location_iso"),
        scenario_context.get("passport_iso"),
        scenario_context.get("licence_issuing_iso"),
    ]:
        cleaned = _normalize_jurisdiction(str(code or ""))
        if cleaned and cleaned not in values:
            values.append(cleaned)
    for analysis in state.get("jurisdiction_analyses", []) or []:
        jurisdiction = _normalize_jurisdiction(str(analysis.get("jurisdiction") or "").strip())
        if jurisdiction and jurisdiction not in values:
            values.append(jurisdiction)
    for code in (state.get("query_intent", {}) or {}).get("iso_codes", []) or []:
        cleaned = _normalize_jurisdiction(str(code or "").strip().lower())
        if cleaned and cleaned not in values:
            values.append(cleaned)
    if "international_overlay" in ((state.get("query_intent", {}) or {}).get("labels") or []) and "international" not in values:
        values.append("international")
    return values


def _state_legal_domains(state: PipelineStateDict) -> list[str]:
    values: list[str] = []
    for label in state.get("issue_labels", []) or []:
        cleaned = str(label or "").strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _analysis_focus(state: PipelineStateDict) -> str:
    intent_primary = set((state.get("query_intent") or {}).get("primary") or [])
    if "named_case" in intent_primary or "case_comparison" in intent_primary:
        return (
            "Focus on the identified case law: facts, issues, holding, legal principle, "
            "and why it matters, but only to the extent supported by the supplied sources."
        )
    if "jurisdiction_comparison" in intent_primary or "cross_border_scenario" in intent_primary:
        return (
            "Identify each implicated jurisdiction, the legal domains involved, immediate rights "
            "or procedural protections, and the realistic next steps available to the user."
        )
    if "conceptual" in intent_primary:
        return (
            "Explain the doctrine, legal basis, typical application, and limits, but stay grounded "
            "in the supplied sources."
        )
    return (
        "Answer the user's legal question pragmatically: identify the governing sources, what they "
        "appear to say, where the gaps remain, and what realistic steps follow."
    )


def _answer_style_instruction(answer_style: str) -> str:
    if answer_style == "short":
        return (
            "Keep the whole answer compact. Use 2–4 short paragraphs total across the four required sections. "
            "Prioritise the bottom line, key rights, and realistic next steps."
        )
    return (
        "Provide a fuller explanation under the four required sections. Be detailed where the sources support it, "
        "but stay concise enough to remain readable."
    )


def _format_analyses(analyses: list[dict[str, Any]]) -> str:
    lines = []
    for analysis in analyses:
        jurisdiction = analysis.get("jurisdiction", "unknown")
        conclusion = analysis.get("conclusion", "indeterminate")
        confidence = analysis.get("confidence", 0.0)
        rules = []
        for rule in analysis.get("applicable_rules", [])[:3]:
            if isinstance(rule, dict):
                rendered = rule.get("rule", "")
            else:
                rendered = str(rule)
            if rendered:
                rules.append(rendered)
        application = str(analysis.get("application", "") or "").strip()
        lines.append(
            f"- {jurisdiction}: conclusion={conclusion}; confidence={confidence:.2f}; "
            f"rules={'; '.join(rules) or 'n/a'}; application={application or 'n/a'}"
        )
    return "\n".join(lines) or "- No jurisdiction analysis available."


def _format_source_context(retrieved: list[dict[str, Any]]) -> str:
    context_parts = []
    for index, passage in enumerate(retrieved[:12], 1):
        meta = passage.get("metadata", {}) or {}
        source = meta.get("source_name", "Unknown")
        jurisdiction = meta.get("jurisdiction", "unknown")
        doc_type = meta.get("doc_type", "")
        tier = infer_authority_tier(meta)
        citation = meta.get("citation", source)
        excerpt = " ".join((passage.get("text") or "").split())[:900]
        context_parts.append(
            f"[{index}] source={source} | citation={citation} | jurisdiction={jurisdiction} | "
            f"doc_type={doc_type} | authority_tier={tier}\n{excerpt}"
        )
    return "\n\n".join(context_parts)


def _conflict_note(analyses: list[dict[str, Any]]) -> str:
    conclusions: dict[str, str] = {}
    for analysis in analyses:
        jurisdiction = str(analysis.get("jurisdiction") or "").strip()
        conclusion = str(analysis.get("conclusion") or "").strip()
        if jurisdiction and conclusion:
            conclusions[jurisdiction] = conclusion
    unique = {value for value in conclusions.values() if value}
    if len(conclusions) < 2 or len(unique) <= 1:
        return "No clear cross-jurisdiction conflict was detected from the structured analysis."
    pairs = ", ".join(f"{jurisdiction}={conclusion}" for jurisdiction, conclusion in conclusions.items())
    return (
        "Potential jurisdictional tension detected. Surface the disagreement explicitly and do not resolve it "
        f"unless the supplied sources do so. Structured conclusions: {pairs}."
    )


def _fallback_draft(
    query: str,
    retrieved: list[dict[str, Any]],
    analyses: list[dict[str, Any]],
    state: PipelineStateDict,
    *,
    seed_text: str = "",
) -> str:
    answer_style = str(state.get("answer_style") or "long")
    scenario_context = ((state.get("entities") or {}).get("scenario_context") or {})
    intent_primary = set((state.get("query_intent") or {}).get("primary") or [])
    merits_lines: list[str] = []
    background_seen = False

    def scenario_line(index: int, passage: dict[str, Any]) -> str:
        meta = passage.get("metadata", {}) or {}
        source = meta.get("source_name", "Retrieved source")
        collection = str(meta.get("collection") or "").upper()
        jurisdiction = _normalize_jurisdiction(meta.get("jurisdiction", ""))
        text = " ".join(
            str(part or "")
            for part in [source, meta.get("citation"), passage.get("text")]
        ).lower()
        location_iso = _normalize_jurisdiction(scenario_context.get("location_iso", ""))
        passport_iso = _normalize_jurisdiction(scenario_context.get("passport_iso", ""))
        licence_iso = _normalize_jurisdiction(scenario_context.get("licence_issuing_iso", ""))
        excerpt = _clean_source_excerpt(passage.get("text", ""))

        if excerpt:
            return f"{source} excerpt: {excerpt} [{index}]"
        if collection == "INTL_TREATIES" and "consular" in text:
            return f"The Vienna Convention on Consular Relations is retrieved here as the main treaty source on consular notification and consular access for detained foreign nationals. [{index}]"
        if collection == "INTL_TREATIES" and any(term in text for term in ["road traffic", "driving permit", "foreign driving", "driving licence", "driving license"]):
            return f"The Convention on Road Traffic is retrieved here as the treaty overlay on foreign-licence recognition and international driving permits, subject to local implementation rules. [{index}]"
        if location_iso and jurisdiction == location_iso and any(term in text for term in ["administrative", "traffic", "road traffic", "driving", "licence", "license"]):
            return f"{source} appears relevant to how the place-of-stop jurisdiction treats traffic licensing issues and whether the matter is framed as a local road-traffic violation. [{index}]"
        if location_iso and jurisdiction == location_iso and any(term in text for term in ["detention", "arrest", "police", "interpreter", "counsel", "procedure"]):
            return f"{source} appears relevant if the roadside matter escalates into detention, questioning, or formal criminal procedure in the place-of-stop jurisdiction. [{index}]"
        if jurisdiction and jurisdiction in {passport_iso, licence_iso} and any(term in text for term in ["driving", "licence", "license", "permit", "motor vehicles", "passport"]):
            return (
                f"{source} is the home-country motor-vehicle and driver-licensing statute, so it is "
                f"relevant to the status of the Indian driving licence as a home-country document. [{index}]"
            )
        if excerpt:
            return f"{source} indicates: {excerpt} [{index}]"
        return f"{source} appears relevant to the user's scenario. [{index}]"

    indexed_merits: list[tuple[int, dict[str, Any]]] = []
    for index, passage in enumerate(retrieved, 1):
        tier = infer_authority_tier((passage.get("metadata") or {}))
        if not is_merits_citable_tier(tier):
            if tier == "reference_dataset":
                background_seen = True
            continue
        indexed_merits.append((index, passage))

    if "cross_border_scenario" in intent_primary and indexed_merits:
        location_iso = _normalize_jurisdiction(scenario_context.get("location_iso", ""))
        passport_iso = _normalize_jurisdiction(scenario_context.get("passport_iso", ""))
        licence_iso = _normalize_jurisdiction(scenario_context.get("licence_issuing_iso", ""))
        home_isos = {code for code in {passport_iso, licence_iso} if code}
        buckets: dict[str, list[tuple[int, dict[str, Any]]]] = {
            "traffic_local": [],
            "procedure_local": [],
            "treaty_road": [],
            "treaty_consular": [],
            "home_documents": [],
            "other": [],
        }

        for item in indexed_merits:
            index, passage = item
            meta = passage.get("metadata", {}) or {}
            collection = str(meta.get("collection") or "").upper()
            jurisdiction = _normalize_jurisdiction(meta.get("jurisdiction", ""))
            text = " ".join(
                str(part or "")
                for part in [meta.get("source_name"), meta.get("citation"), passage.get("text")]
            ).lower()
            if collection == "INTL_TREATIES" and "consular" in text:
                buckets["treaty_consular"].append(item)
            elif collection == "INTL_TREATIES" and any(term in text for term in ["road traffic", "driving permit", "driving licence", "driving license", "foreign driving"]):
                buckets["treaty_road"].append(item)
            elif location_iso and jurisdiction == location_iso and any(
                term in text
                for term in [
                    "road traffic safety",
                    "code of administrative offences",
                    "administrative offences",
                    "administrative liability",
                    "driving",
                    "licence",
                    "license",
                    "road traffic",
                ]
            ):
                buckets["traffic_local"].append(item)
            elif location_iso and jurisdiction == location_iso and any(term in text for term in ["detention", "arrest", "police", "procedure", "interpreter", "counsel"]):
                buckets["procedure_local"].append(item)
            elif home_isos and jurisdiction in home_isos and any(term in text for term in ["passport", "driving", "licence", "license", "permit", "motor vehicles"]):
                buckets["home_documents"].append(item)
            else:
                buckets["other"].append(item)

        target_count = 2 if answer_style == "short" else 4
        chosen: list[tuple[int, dict[str, Any]]] = []
        seen_indexes: set[int] = set()
        for bucket_name in ["traffic_local", "treaty_road", "treaty_consular", "home_documents", "procedure_local", "other"]:
            for index, passage in buckets[bucket_name]:
                if index in seen_indexes:
                    continue
                chosen.append((index, passage))
                seen_indexes.add(index)
                break
            if len(chosen) >= target_count:
                break
        if len(chosen) < target_count:
            for index, passage in indexed_merits:
                if index in seen_indexes:
                    continue
                chosen.append((index, passage))
                seen_indexes.add(index)
                if len(chosen) >= target_count:
                    break
        merits_lines = [scenario_line(index, passage) for index, passage in chosen]
    else:
        for index, passage in indexed_merits:
            merits_lines.append(scenario_line(index, passage))
            if len(merits_lines) >= (2 if answer_style == "short" else 4):
                break

    general_parts: list[str] = []
    if not merits_lines:
        general_parts.append(
            "Treat this as practical legal orientation rather than a definitive merits opinion. The safest next steps depend on the exact local charge, paperwork, and procedural posture."
        )
    else:
        general_parts.append(
            "The retrieved authority appears relevant but incomplete, so the answer should be treated as a partial source-grounded analysis rather than a definitive merits opinion."
        )
    if background_seen:
        general_parts.append(
            "Lower-tier reference-dataset material was available, but it is background context only and cannot substitute for controlling authority."
        )
    if "cross_border_scenario" in intent_primary:
        general_parts.append(
            "In cross-border traffic or detention scenarios, the practical question is usually a mix of local police or traffic law, local procedure, and any treaty overlay on foreign-document recognition or consular access."
        )
    if seed_text:
        general_parts.append(
            "Internal seed case summaries were available as orientation material, but they should be checked directly against primary sources before reliance."
        )
    retrieval_confidence = (state.get("query_intent") or {}).get("retrieval_confidence", {}) or {}
    reason = str(retrieval_confidence.get("reason") or "").strip()
    if reason:
        general_parts.append(f"Retrieval note: {reason}")

    jurisdictions = ", ".join(_state_jurisdictions(state)) or "the relevant local jurisdiction"
    legal_domains = ", ".join(_state_legal_domains(state)) or "the applicable legal regime"
    if "cross_border_scenario" in intent_primary and answer_style == "short":
        practical_steps = (
            "Get the exact local charge or protocol, clarify whether the allegation is no licence at all or a foreign-licence recognition issue, request an interpreter and local lawyer, and ask for consular contact if detained."
        )
    elif "cross_border_scenario" in intent_primary:
        practical_steps = (
            "Get the exact local charge, article, or administrative protocol in writing; clarify whether the allegation is no licence at all, failure to carry or produce it, or use of a foreign licence that local law does not recognise; preserve the original passport, driving licence, and any international driving permit; ask for an interpreter and local lawyer before substantive questioning; request consular notification or consular access if detained; and have local counsel assess whether the matter can be handled as an administrative fine, document-production issue, or appeal rather than a criminal case."
        )
    elif answer_style == "short":
        practical_steps = (
            f"Confirm the exact jurisdiction and charge, identify the controlling procedure in {jurisdictions}, "
            "preserve the relevant documents, and speak with a qualified local lawyer before taking action."
        )
    else:
        practical_steps = (
            f"Confirm which jurisdiction is controlling ({jurisdictions}), identify the implicated legal domains ({legal_domains}), "
            "get the exact charge or procedural posture in writing, preserve passports/licences/orders/notices, ask for an interpreter if needed, "
            "seek consular help where nationality is relevant, and consult a qualified local lawyer before making admissions or procedural decisions."
        )

    sections = {
        "sourced_authority": " ".join(merits_lines).strip(),
        "general_principles": "",
        "practical_steps": "",
        "disclaimer": LEGAL_RESEARCH_SHORT_DISCLAIMER,
    }
    return format_answer_sections(sections)


def _label_sources(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach S1, S2, ... labels to retrieved passages for LLM citation."""
    labeled = []
    for idx, p in enumerate(retrieved, start=1):
        labeled.append({**p, "label": f"S{idx}"})
    return labeled


def synthesize(state: PipelineStateDict) -> PipelineStateDict:
    query = state["raw_input"]
    answer_style = str(state.get("answer_style") or "long")
    retrieved = sorted(
        _apply_temporal_weighting(state.get("retrieved", []) or []),
        key=lambda passage: (
            authority_rank(infer_authority_tier(passage.get("metadata") or {})),
            float(passage.get("temporal_score", passage.get("score", 0.0)) or 0.0),
        ),
        reverse=True,
    )
    analyses = state.get("jurisdiction_analyses", []) or []

    # SHORT mode should stay layman-readable and cite only merits authority.
    # Commentary can appear in LONG mode under Malcolm Shaw when relevant.
    generation_sources = retrieved
    if answer_style == "short":
        generation_sources = [
            passage for passage in retrieved
            if is_merits_citable_tier(infer_authority_tier(passage.get("metadata") or {}))
        ] or retrieved

    # Attach [S#] labels so the LLM can cite them
    labeled = _label_sources(generation_sources)

    # Attempt provider-backed generation first (Groq -> Ollama).
    mode = str(state.get("mode") or "research")
    draft = ""
    provider = ""
    try:
        from src.pipeline.llm import LLMUnavailable, complete
        from src.pipeline.prompts import build_synthesis_message, system_for

        system = system_for(mode)
        user = build_synthesis_message(query, labeled, answer_style)
        draft, provider = complete(system, user, temperature=0.12)
    except Exception as exc:  # noqa: BLE001
        print(f"Warning: LLM synthesis failed ({type(exc).__name__}: {exc}); using template fallback.")

    # Fall back to v1's template-based draft if LLM unavailable or empty
    if not draft or len(draft.strip()) < 50:
        draft = _fallback_draft(query, generation_sources, analyses, state, seed_text="")
        provider = "template_fallback"

    return {
        **state,
        "retrieved": labeled,
        "draft": draft,
        "conflicts": [],
        "provider": provider,
    }
