"""Tests for the source availability registry and gate.

Replaces the old test_quality_first_sources.py which tested the now-deleted
simple_legal_runtime and source_escalator modules.
"""
from __future__ import annotations

import pytest

from src.pipeline.source_registry import (
    AvailabilityResult,
    IndexedSourcesRegistry,
    SourceRequirement,
    TopicSourceMap,
    detect_topics,
    _get_registry,
)
from src.pipeline.source_gate import source_gate


# ---------------------------------------------------------------------------
# Topic detection
# ---------------------------------------------------------------------------

def test_detect_diplomatic_immunity():
    topics = detect_topics("What is diplomatic immunity under the Vienna Convention?")
    assert "diplomatic_immunity" in topics


def test_detect_india_russia_driving():
    topics = detect_topics("Can an Indian tourist drive in Russia with an Indian licence?")
    assert "driving_india_russia" in topics


def test_detect_bns_69():
    topics = detect_topics("Explain BNS Section 69 in India")
    assert "bns_69" in topics


def test_detect_murder_sentencing():
    topics = detect_topics("Compare murder sentencing in India, UK, and US")
    assert "murder_sentencing" in topics


def test_detect_tinoco():
    topics = detect_topics("Analyze the Tinoco arbitration and state recognition")
    assert "tinoco" in topics


def test_detect_wall():
    topics = detect_topics("Explain the Wall Advisory Opinion and self-determination")
    assert "wall" in topics


def test_detect_travel():
    topics = detect_topics("India Russia travel visa advice")
    assert "travel_india_russia" in topics


def test_detect_default_for_unknown():
    topics = detect_topics("What is the meaning of life?")
    assert topics == ["default"]


# ---------------------------------------------------------------------------
# Registry loading
# ---------------------------------------------------------------------------

def test_registry_loads_from_yaml():
    registry = _get_registry()
    assert "diplomatic_immunity" in registry
    assert "default" in registry


def test_registry_has_required_roles():
    registry = _get_registry()
    diplo = registry["diplomatic_immunity"]
    assert len(diplo.required) >= 2
    roles = {r.role for r in diplo.required}
    assert "treaty" in roles
    assert "case_law" in roles


def test_registry_driving_has_three_required():
    registry = _get_registry()
    driving = registry["driving_india_russia"]
    assert len(driving.required) >= 3


# ---------------------------------------------------------------------------
# Source gate node (unit test with mock state)
# ---------------------------------------------------------------------------

def test_source_gate_passes_through_on_default():
    state = {"raw_input": "What is the meaning of life?", "entities": {}}
    result = source_gate(state)
    assert result.get("source_plan") is not None
    # default topic has no required sources, so should pass
    # (even if Qdrant is not loaded)


def test_source_gate_adds_unsupported_jurisdiction_note():
    state = {
        "raw_input": "What is Brazil's driving law?",
        "entities": {"iso_country_codes": ["br"]},
    }
    result = source_gate(state)
    source_plan = result.get("source_plan", {})
    assert "br" in source_plan.get("unsupported_jurisdictions", [])
    assert "international" in source_plan.get("fallback_note", "").lower()
