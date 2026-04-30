"""Golden query tests — end-to-end pipeline validation.

These tests require:
  - Qdrant to be seeded (python scripts/seed_qdrant.py)
  - GROQ_API_KEY to be set in .env
  - BGE-M3 model to be downloaded

Run with: python -m pytest tests/test_golden_queries.py -v --timeout=600
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Skip all tests if GROQ_API_KEY is not set
pytestmark = pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="GROQ_API_KEY not set — golden tests require live LLM",
)


def _invoke_pipeline(query: str, answer_style: str = "long") -> dict:
    """Run a query through the compiled LangGraph pipeline."""
    from src.pipeline.graph import compiled_graph

    state = {
        "raw_input": query,
        "answer_style": answer_style,
    }
    return compiled_graph.invoke(state)


def _answer_text(result: dict) -> str:
    final = result.get("final") or {}
    return str(final.get("answer", "") or result.get("verified_draft", "") or result.get("draft", ""))


class TestDiplomaticImmunity:
    """Diplomatic immunity — VCDR + Arrest Warrant required."""

    def test_short(self):
        result = _invoke_pipeline("What is diplomatic immunity?", "short")
        answer = _answer_text(result)
        assert answer.strip(), "Pipeline should produce an answer"
        assert not result.get("insufficient_context"), "Should not be insufficient"

    def test_long(self):
        result = _invoke_pipeline("What is diplomatic immunity under the Vienna Convention?", "long")
        answer = _answer_text(result)
        assert answer.strip(), "Pipeline should produce an answer"
        # Check for section structure
        assert "##" in answer, "Long answer should have section headers"


class TestIndiaRussiaDriving:
    """Driving with Indian licence in Russia — treaty + local statutes."""

    def test_short(self):
        result = _invoke_pipeline(
            "Can an Indian tourist drive in Russia with an Indian licence?", "short"
        )
        answer = _answer_text(result)
        assert answer.strip()

    def test_long(self):
        result = _invoke_pipeline(
            "Can an Indian drive in Russia with an Indian driving licence?", "long"
        )
        answer = _answer_text(result)
        assert answer.strip()
        # Should mention relevant legal concepts
        lower = answer.lower()
        assert any(term in lower for term in ["driving", "licence", "license", "permit", "road traffic"])


class TestBNS69:
    """BNS Section 69 — Indian local statute."""

    def test_long(self):
        result = _invoke_pipeline("Explain BNS Section 69 in India", "long")
        answer = _answer_text(result)
        assert answer.strip()
        lower = answer.lower()
        assert any(term in lower for term in ["section 69", "bns", "bharatiya", "deceitful"])


class TestMurderSentencing:
    """Murder sentencing comparison — India + UK + US."""

    def test_comparison(self):
        result = _invoke_pipeline(
            "Compare murder sentencing in India, UK, and US", "long"
        )
        answer = _answer_text(result)
        assert answer.strip()
        lower = answer.lower()
        assert "murder" in lower


class TestTinoco:
    """Tinoco arbitration — case law + optional commentary."""

    def test_long(self):
        result = _invoke_pipeline(
            "Analyze the Tinoco arbitration and state recognition", "long"
        )
        answer = _answer_text(result)
        assert answer.strip()
        lower = answer.lower()
        assert "tinoco" in lower


class TestWallAdvisory:
    """Wall Advisory Opinion — ICJ case law."""

    def test_long(self):
        result = _invoke_pipeline(
            "Explain the Wall Advisory Opinion and self-determination", "long"
        )
        answer = _answer_text(result)
        assert answer.strip()
        lower = answer.lower()
        assert any(term in lower for term in ["wall", "advisory", "palestinian"])


class TestUnsupportedJurisdiction:
    """Unsupported jurisdiction — must fail early."""

    def test_brazil_local_law_fails_early(self):
        result = _invoke_pipeline("What is Brazil's local driving law?")
        answer = _answer_text(result)
        assert result.get("insufficient_context") is True
        assert "missing required source" in answer.lower() or "insufficient" in answer.lower()
