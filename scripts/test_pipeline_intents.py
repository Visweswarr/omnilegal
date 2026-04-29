"""
Verification script for the five query-intent pipeline tests defined in the
OmniLegal fix plan.  Run from the repo root:

    python scripts/test_pipeline_intents.py

Each test inspects state fields produced by entity_extractor.extract_entities
(and optionally the full pipeline) and asserts on the values described in the
plan's Verification Plan section.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.entity_extractor import extract_entities
from src.pipeline.state import PipelineStateDict

_PASS = "\033[92mPASS\033[0m"
_FAIL = "\033[91mFAIL\033[0m"
_failures: list[str] = []


def _assert(condition: bool, label: str, got: object = None) -> None:
    if condition:
        print(f"  {_PASS}  {label}")
    else:
        msg = f"  {_FAIL}  {label}" + (f"  (got: {got!r})" if got is not None else "")
        print(msg)
        _failures.append(label)


def _run(query: str) -> PipelineStateDict:
    state: PipelineStateDict = {"raw_input": query, "input_class": "question", "input_confidence": 0.95}
    return extract_entities(state)


# ── Test 1: Entity + Intent Detection ────────────────────────────────────────

def test_jurisdiction_comparison_intent() -> None:
    print("\nTest 1: Entity + Intent Detection")
    print('  Input: "compare how russia and india treat death penalty"')
    state = _run("compare how russia and india treat death penalty")

    iso = state.get("entities", {}).get("iso_country_codes", [])
    intent = state.get("query_intent", {})
    labels = intent.get("labels", [])
    primary = intent.get("primary", [])
    jurisdiction = state.get("entities", {}).get("jurisdiction", "")

    _assert("IN" in iso, "iso_country_codes contains IN", iso)
    _assert("RU" in iso, "iso_country_codes contains RU", iso)
    _assert("human_rights" in (state.get("issue_labels") or []), "issue_labels includes human_rights", state.get("issue_labels"))
    _assert("jurisdiction_comparison" in primary, "query_intent.primary == jurisdiction_comparison", primary)
    _assert("country" in labels, "query_intent.labels includes country", labels)
    _assert(jurisdiction in ("mixed", "in", "ru"), "jurisdiction is mixed (not 'indian')", jurisdiction)


# ── Test 2: Conceptual Query Routing ─────────────────────────────────────────

def test_conceptual_routing() -> None:
    print("\nTest 2: Conceptual Query Routing")
    print('  Input: "explain erga omnes obligations in international law"')
    state = _run("explain erga omnes obligations in international law")

    intent = state.get("query_intent", {})
    primary = intent.get("primary", [])
    labels = intent.get("labels", [])
    issue_labels = state.get("issue_labels") or []

    _assert("conceptual" in primary, "query_intent.primary includes conceptual", primary)
    _assert("named_case" not in primary, "named_case NOT in primary (pure conceptual)", primary)
    _assert(
        "erga_omnes_jus_cogens" in issue_labels or "state_responsibility" in issue_labels,
        "issue_labels includes erga_omnes_jus_cogens or state_responsibility",
        issue_labels,
    )


# ── Test 3: Noise Filtering (entity / issue level) ───────────────────────────

def test_noise_filtering() -> None:
    print("\nTest 3: Noise Filtering (entity extraction)")
    print('  Input: "state responsibility erga omnes ICJ"')
    state = _run("state responsibility erga omnes ICJ")

    issue_labels = state.get("issue_labels") or []
    entities = (state.get("entities") or {}).get("entities") or []
    entity_labels = {e.get("label", "").lower() for e in entities}

    _assert(
        "state_responsibility" in issue_labels or "erga_omnes_jus_cogens" in issue_labels,
        "issue_labels includes state_responsibility or erga_omnes_jus_cogens",
        issue_labels,
    )
    _assert("icj case" in entity_labels or "court" in entity_labels, "ICJ detected as entity", entity_labels)


# ── Test 4: Case Comparison ───────────────────────────────────────────────────

def test_case_comparison() -> None:
    print("\nTest 4: Case Comparison")
    print('  Input: "compare corfu channel and lotus case"')
    state = _run("compare corfu channel and lotus case")

    intent = state.get("query_intent", {})
    primary = intent.get("primary", [])
    labels = intent.get("labels", [])
    entities = (state.get("entities") or {}).get("entities") or []
    case_names = {e["text"].lower() for e in entities if e.get("label", "").lower() in {"legal_case", "icj case", "arbitration case"}}

    _assert("case_comparison" in primary, "query_intent.primary includes case_comparison", primary)
    _assert("named_case" in labels, "query_intent.labels includes named_case", labels)
    _assert(
        any("corfu" in n for n in case_names),
        "Corfu Channel detected as case entity",
        case_names,
    )
    _assert(
        any("lotus" in n for n in case_names),
        "Lotus detected as case entity",
        case_names,
    )


# ── Test 5: Cross-Jurisdiction Citation Policy (intent-level) ────────────────

def test_cross_jurisdiction_citation_policy() -> None:
    print("\nTest 5: Cross-Jurisdiction Citation Policy (intent flags)")
    print('  Input: "compare india vs iccpr on death penalty"')
    state = _run("compare india vs iccpr on death penalty")

    intent = state.get("query_intent", {})
    primary = intent.get("primary", [])
    labels = intent.get("labels", [])
    iso = (state.get("entities") or {}).get("iso_country_codes", [])

    _assert(
        "jurisdiction_comparison" in primary or "mixed" in primary or "country" in labels,
        "intent indicates comparative/mixed mode (cross-jurisdiction citations allowed)",
        primary,
    )
    _assert("IN" in iso, "India detected in iso_country_codes", iso)
    issue_labels = state.get("issue_labels") or []
    _assert("human_rights" in issue_labels, "issue_labels includes human_rights (death penalty)", issue_labels)


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("OmniLegal Pipeline Intent Verification")
    print("=" * 60)

    test_jurisdiction_comparison_intent()
    test_conceptual_routing()
    test_noise_filtering()
    test_case_comparison()
    test_cross_jurisdiction_citation_policy()

    print("\n" + "=" * 60)
    if _failures:
        print(f"RESULT: {len(_failures)} assertion(s) FAILED:")
        for f in _failures:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("RESULT: All assertions passed.")
        sys.exit(0)
