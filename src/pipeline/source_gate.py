"""Source availability gate — LangGraph node.

Inserted after ``extract_entities`` and before ``retrieve``.  Reads
detected topics and jurisdictions from pipeline state, checks the
:class:`IndexedSourcesRegistry`, and either passes through or fails
early with a clear message listing the missing source bundles.

For unsupported jurisdictions (no local collections indexed), the gate
falls back to international law sources and proceeds instead of
hard-failing.
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

# Jurisdictions for which we have Qdrant collections
_SUPPORTED_JURISDICTIONS = {"india", "in", "russia", "ru", "us", "usa", "uk", "gb", "eu", "israel", "il"}

_registry_instance: IndexedSourcesRegistry | None = None


def _get_registry() -> IndexedSourcesRegistry:
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = IndexedSourcesRegistry()
    return _registry_instance


def source_gate(state: PipelineStateDict) -> PipelineStateDict:
    """Check source availability before retrieval.

    Sets ``source_plan`` with required roles and target collections.
    If any *required* source bundle is missing, sets
    ``pipeline_errors`` and ``insufficient_context``.
    """
    query = state.get("raw_input", "")
    topics = detect_topics(query)

    # Jurisdiction check — unsupported countries fall back to international
    iso_codes = (state.get("entities") or {}).get("iso_country_codes", [])
    unsupported: list[str] = []
    for code in iso_codes:
        if code.lower() not in _SUPPORTED_JURISDICTIONS:
            unsupported.append(code)

    fallback_note = ""
    if unsupported:
        fallback_note = (
            f"Local law for {', '.join(unsupported)} is not indexed. "
            "Proceeding with international law sources only."
        )

    registry = _get_registry()
    availability = registry.check_availability(topics)
    required_roles = registry.get_required_roles(topics)
    target_collections = registry.get_target_collections(topics)

    source_plan: dict[str, Any] = {
        "topics": topics,
        "required_roles": [
            {"role": r.role, "source_pattern": r.source_pattern,
             "collection": r.collection, "description": r.description}
            for r in required_roles
        ],
        "target_collections": target_collections,
        "present_sources": availability.present,
        "missing_sources": availability.missing,
        "unsupported_jurisdictions": unsupported,
        "fallback_note": fallback_note,
    }

    if not availability.ok:
        # Required sources missing — fail early
        error_lines = ["Source availability check failed:"]
        error_lines.extend(f"  • {m}" for m in availability.missing)
        if fallback_note:
            error_lines.append(f"  Note: {fallback_note}")
        error_msg = "\n".join(error_lines)
        print(f"[source_gate] {error_msg}")

        errors = list(state.get("pipeline_errors") or [])
        errors.append(error_msg)

        return {
            **state,
            "source_plan": source_plan,
            "source_availability": {"ok": False, "missing": availability.missing},
            "pipeline_errors": errors,
            "insufficient_context": True,
        }

    if fallback_note:
        print(f"[source_gate] {fallback_note}")

    return {
        **state,
        "source_plan": source_plan,
        "source_availability": {"ok": True, "missing": []},
    }
