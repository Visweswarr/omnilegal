"""Source availability gate — LangGraph node.

Inserted after ``extract_entities`` and before ``retrieve``.  Reads
detected topics and jurisdictions from pipeline state, checks the
:class:`IndexedSourcesRegistry`, and either passes through or fails
early with a clear message listing the missing source bundles.

Unsupported jurisdictions hard-fail. The app must not answer local-law
questions from the wrong country or a generic international fallback.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.pipeline.source_registry import (
    IndexedSourcesRegistry,
    detect_topics,
)
from src.pipeline.state import PipelineStateDict
from src.config import LEGAL_RESEARCH_SHORT_DISCLAIMER

# Jurisdictions for which we have Qdrant collections
_SUPPORTED_JURISDICTIONS = {"india", "in", "russia", "ru", "us", "usa", "uk", "gb", "eu", "israel", "il"}
_JURISDICTION_ALIASES = {
    "in": "in",
    "india": "in",
    "indian": "in",
    "ru": "ru",
    "russia": "ru",
    "russian": "ru",
    "russian federation": "ru",
    "us": "us",
    "usa": "us",
    "u.s.": "us",
    "united states": "us",
    "american": "us",
    "uk": "gb",
    "gb": "gb",
    "united kingdom": "gb",
    "british": "gb",
    "eu": "eu",
    "european union": "eu",
    "israel": "il",
    "il": "il",
    "br": "br",
    "brazil": "br",
    "brazilian": "br",
}

_registry_instance: IndexedSourcesRegistry | None = None


def _get_registry() -> IndexedSourcesRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = IndexedSourcesRegistry()
    return _registry_instance


def _normalise_jurisdiction(value: Any) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    return _JURISDICTION_ALIASES.get(cleaned, cleaned)


def _state_iso_codes(state: PipelineStateDict) -> list[str]:
    values: list[str] = []
    entities = state.get("entities") or {}
    for code in entities.get("iso_country_codes", []) or []:
        norm = _normalise_jurisdiction(code)
        if norm and norm not in values:
            values.append(norm)
    for code in state.get("jurisdictions", []) or []:
        norm = _normalise_jurisdiction(code)
        if norm and norm not in values:
            values.append(norm)
    scenario = entities.get("scenario_context") or {}
    for key in ("location_iso", "passport_iso", "licence_issuing_iso"):
        norm = _normalise_jurisdiction(scenario.get(key))
        if norm and norm not in values:
            values.append(norm)
    return values


def _failure_final(query: str, source_plan: dict[str, Any], missing: list[str]) -> dict[str, Any]:
    missing_lines = "\n".join(f"- {item}" for item in missing) or "- Missing required source bundle."
    answer = (
        "## Insufficient Verified Sources\n"
        "I cannot answer this from the indexed legal corpus yet.\n\n"
        f"{missing_lines}\n\n"
        "No legal conclusion was generated because the source availability gate failed.\n\n"
        f"## Disclaimer\n{LEGAL_RESEARCH_SHORT_DISCLAIMER}"
    )
    return {
        "query": query,
        "answer": answer,
        "citations": [],
        "sources": [],
        "grounding_status": "no_authority",
        "authority_gaps": list(missing),
        "answer_style": "long",
        "sections": {
            "insufficient_verified_sources": missing_lines,
            "disclaimer": LEGAL_RESEARCH_SHORT_DISCLAIMER,
        },
        "source_plan": source_plan,
        "insufficient_context": True,
    }


def source_gate(state: PipelineStateDict) -> PipelineStateDict:
    """Check source availability before retrieval.

    Sets ``source_plan`` with required roles and target collections.
    If any *required* source bundle is missing, sets
    ``pipeline_errors`` and ``insufficient_context``.
    """
    query = state.get("raw_input", "")
    topics = detect_topics(query)

    # Jurisdiction check — unsupported countries hard-fail.
    iso_codes = _state_iso_codes(state)
    unsupported: list[str] = []
    for code in iso_codes:
        if _normalise_jurisdiction(code) not in _SUPPORTED_JURISDICTIONS:
            unsupported.append(code)

    unsupported_gaps = [
        f"Missing required source: local law — {code.upper()} local-law corpus is not indexed"
        for code in unsupported
    ]

    registry = _get_registry()
    availability = registry.check_availability(topics)
    required_roles = registry.get_required_roles(topics)
    optional_roles = registry.get_optional_roles(topics)
    target_collections = registry.get_target_collections(topics)

    source_plan: dict[str, Any] = {
        "topics": topics,
        "required_roles": [
            {"role": r.role, "source_pattern": r.source_pattern,
             "collection": r.collection, "description": r.description}
            for r in required_roles
        ],
        "optional_roles": [
            {"role": r.role, "source_pattern": r.source_pattern,
             "collection": r.collection, "description": r.description}
            for r in optional_roles
        ],
        "target_collections": target_collections,
        "present_sources": availability.present,
        "missing_sources": availability.missing,
        "unsupported_jurisdictions": unsupported,
        "fallback_note": "",
    }

    missing = list(availability.missing) + unsupported_gaps
    if missing:
        # Required sources missing — fail early
        error_lines = ["Source availability check failed:"]
        error_lines.extend(f"  • {m}" for m in missing)
        error_msg = "\n".join(error_lines)
        print(f"[source_gate] {error_msg}")

        errors = list(state.get("pipeline_errors") or [])
        errors.append(error_msg)

        final = _failure_final(query, source_plan, missing)
        return {
            **state,
            "source_plan": source_plan,
            "source_availability": {"ok": False, "missing": missing},
            "pipeline_errors": errors,
            "insufficient_context": True,
            "verified_draft": final["answer"],
            "final": final,
        }

    return {
        **state,
        "source_plan": source_plan,
        "source_availability": {"ok": True, "missing": []},
    }
