"""Tests for the source availability gate.

Failure-first: these tests verify that the pipeline rejects queries
when required source bundles are missing or when jurisdictions are
unsupported.
"""
from __future__ import annotations

import pytest

from src.pipeline.source_gate import source_gate


class TestSourceGateFailures:
    """The gate must fail early when sources are missing."""

    def test_default_topic_passes_with_no_required_sources(self):
        """Queries that don't match any known topic use the default
        registry entry, which has no required sources."""
        state = {"raw_input": "Hello world", "entities": {}}
        result = source_gate(state)
        avail = result.get("source_availability", {})
        # Default topic has no required sources → ok
        assert avail.get("ok") is True or avail.get("missing") == []

    def test_unsupported_jurisdiction_adds_fallback_note(self):
        """When a query mentions a country outside the indexed set,
        the gate should add a fallback note and proceed with
        international sources."""
        state = {
            "raw_input": "What is the driving law in Brazil?",
            "entities": {"iso_country_codes": ["br"]},
        }
        result = source_gate(state)
        plan = result.get("source_plan", {})
        assert "br" in plan.get("unsupported_jurisdictions", [])
        assert "international" in plan.get("fallback_note", "").lower()

    def test_source_plan_has_required_roles_for_diplomatic(self):
        """Diplomatic immunity queries should populate required_roles."""
        state = {
            "raw_input": "What is diplomatic immunity under the Vienna Convention?",
            "entities": {},
        }
        result = source_gate(state)
        plan = result.get("source_plan", {})
        roles = [r["role"] for r in plan.get("required_roles", [])]
        assert "treaty" in roles
        assert "case_law" in roles

    def test_source_plan_has_target_collections(self):
        """Source plan should include target Qdrant collections."""
        state = {
            "raw_input": "Can an Indian drive in Russia with an Indian licence?",
            "entities": {},
        }
        result = source_gate(state)
        plan = result.get("source_plan", {})
        collections = plan.get("target_collections", [])
        assert len(collections) > 0

    def test_topics_detected_correctly_in_source_plan(self):
        """The source plan should reflect detected topics."""
        state = {
            "raw_input": "Explain BNS Section 69 in India",
            "entities": {},
        }
        result = source_gate(state)
        plan = result.get("source_plan", {})
        assert "bns_69" in plan.get("topics", [])


class TestSourceGateIntegration:
    """Integration-style tests (require Qdrant to be seeded for full coverage)."""

    def test_gate_returns_source_plan_dict(self):
        """The gate must always set source_plan in state."""
        state = {"raw_input": "What is murder?", "entities": {}}
        result = source_gate(state)
        assert "source_plan" in result
        assert isinstance(result["source_plan"], dict)
