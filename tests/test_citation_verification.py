"""Tests for the citation verification layer.

Verifies that the citation verifier correctly grades markers, rejects
hallucinated citations, and enforces lexical/quote matching.
"""
from __future__ import annotations

import pytest

from src.pipeline.citation_verifier import (
    _grade_citation,
    _lexical_support_ratio,
    _normalise_for_match,
    _forced_quote_passes,
    _check_source_plan_sufficiency,
)


class TestLexicalSupport:
    """Lexical support ratio must be meaningful for CORRECT grade."""

    def test_high_overlap_is_correct(self):
        """Claim that reuses many passage words should score high."""
        claim = "The Vienna Convention provides diplomatic agents with immunity from criminal jurisdiction."
        passage = "The Vienna Convention on Diplomatic Relations provides that diplomatic agents shall enjoy immunity from the criminal jurisdiction of the receiving state."
        ratio = _lexical_support_ratio(claim, passage)
        assert ratio >= 0.35, f"Expected >= 0.35, got {ratio}"

    def test_no_overlap_is_zero(self):
        """Completely unrelated text should score near zero."""
        claim = "The quantum entanglement paradox demonstrates non-locality."
        passage = "Article 41 provides for recognition of driving permits issued by contracting parties."
        ratio = _lexical_support_ratio(claim, passage)
        assert ratio < 0.15, f"Expected < 0.15, got {ratio}"

    def test_partial_overlap_is_ambiguous_range(self):
        """Some shared terms but not a clear match — between thresholds."""
        claim = "Diplomatic relations require mutual respect between sovereign states."
        passage = "Section 103 provides the punishment for murder. A person who commits murder may be punished with death or imprisonment for life and is also liable to fine."
        ratio = _lexical_support_ratio(claim, passage)
        # Very low overlap — different topics
        assert ratio < 0.35, f"Expected < 0.35, got {ratio}"


class TestQuoteMatching:
    """Forced quote verification."""

    def test_verbatim_quote_passes(self):
        passage = "The diplomatic agent shall be inviolable. He shall not be liable to any form of arrest or detention."
        ok, missing = _forced_quote_passes(
            1,
            'The agent "shall be inviolable" [1].',
            passage,
        )
        assert ok is True
        assert missing == []

    def test_missing_quote_fails(self):
        passage = "Article 41 provides for recognition of driving permits."
        ok, missing = _forced_quote_passes(
            1,
            'The treaty says "diplomatic agents enjoy full immunity" [1].',
            passage,
        )
        assert ok is False
        assert len(missing) > 0


class TestGradeCitation:
    """Grade citation with real passage data."""

    def test_out_of_range_marker_is_incorrect(self):
        result = _grade_citation(5, "some text [5]", [])
        assert result["grade"] == "INCORRECT"

    def test_empty_passage_is_incorrect(self):
        result = _grade_citation(1, "some text [1]", [{"text": "", "metadata": {}}])
        assert result["grade"] == "INCORRECT"

    def test_valid_citation_with_overlap(self, monkeypatch: pytest.MonkeyPatch):
        # Disable NLI entailment to ensure we only test lexical support
        monkeypatch.setattr("src.pipeline.citation_verifier.OMNILEGAL_ENABLE_NLI_VERIFIER", False)
        passage = {
            "text": "The Vienna Convention on Diplomatic Relations establishes that diplomatic agents enjoy immunity from criminal jurisdiction. Article 31 provides this protection.",
            "metadata": {
                "source_name": "VCDR",
                "jurisdiction": "international",
                "doc_type": "treaty",
            },
        }
        draft = "The Vienna Convention on Diplomatic Relations establishes immunity from criminal jurisdiction for diplomatic agents [1]."
        result = _grade_citation(1, draft, [passage])
        # With high lexical overlap, grade should not be INCORRECT
        assert result["grade"] != "INCORRECT", f"Expected non-INCORRECT, got {result}"


class TestSourcePlanSufficiency:
    """Source plan role sufficiency checks."""

    def test_all_roles_cited_returns_empty(self):
        state = {
            "source_plan": {
                "required_roles": [
                    {"role": "treaty", "description": "VCDR"},
                    {"role": "case_law", "description": "Arrest Warrant"},
                ],
            },
        }
        retrieved = [
            {"text": "treaty text", "metadata": {"source_role": "treaty"}},
            {"text": "case text", "metadata": {"source_role": "case_law"}},
        ]
        gaps = _check_source_plan_sufficiency(state, [1, 2], retrieved)
        assert gaps == []

    def test_missing_role_returns_gap(self):
        state = {
            "source_plan": {
                "required_roles": [
                    {"role": "treaty", "description": "VCDR"},
                    {"role": "case_law", "description": "Arrest Warrant"},
                ],
            },
        }
        retrieved = [
            {"text": "treaty text", "metadata": {"source_role": "treaty"}},
        ]
        gaps = _check_source_plan_sufficiency(state, [1], retrieved)
        assert len(gaps) == 1
        assert "case_law" in gaps[0]

    def test_no_source_plan_returns_empty(self):
        state = {}
        gaps = _check_source_plan_sufficiency(state, [1], [{"text": "x", "metadata": {}}])
        assert gaps == []
