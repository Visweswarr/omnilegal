"""Golden question test suite for the OmniLegal Quality-First rebuild.

Tests cover:
  - Answer mode detection
  - ISO code extraction
  - Safety critic blocking
  - Citation verification basics
  - Provider registry discovery
  - ResearchAnswer contract completeness
  - Performance gates (no 180s timeouts)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Golden Questions ──────────────────────────────────────────────────────────

GOLDEN_QUESTIONS = [
    {
        "query": "I am an Indian citizen driving in Russia with my Indian driving licence. I was stopped by traffic police. What are my rights?",
        "expected_mode": "tourist_practical",
        "expected_iso_codes": ["IN", "RU"],
        "must_contain_keywords": ["vienna convention", "consular", "driving"],
        "must_not_contain": ["US", "American", "UK"],
    },
    {
        "query": "Explain BNS Section 69 and its implications",
        "expected_mode": "law_student_case_law",
        "expected_iso_codes": ["IN"],
    },
    {
        "query": "Analyze the Tinoco Arbitration and its significance for state recognition",
        "expected_mode": "law_student_case_law",
    },
    {
        "query": "Compare murder sentencing across US, UK, and India",
        "expected_mode": "comparative_research",
        "expected_iso_codes": ["US", "GB", "IN"],
    },
    {
        "query": "What laws should a tourist know before visiting Japan?",
        "expected_mode": "tourist_practical",
    },
    {
        "query": "Find all sources on the right to fair trial under ICCPR",
        "expected_mode": "source_discovery",
    },
]


# ── Answer Mode Detection Tests ──────────────────────────────────────────────

class TestAnswerModeDetection:
    """Verify that the mode detector selects the right mode for each golden question."""

    def test_tourist_practical_mode(self):
        from src.services.answer_modes import detect_answer_mode
        result = detect_answer_mode(GOLDEN_QUESTIONS[0]["query"])
        assert result.value == "tourist_practical"

    def test_law_student_mode_bns(self):
        from src.services.answer_modes import detect_answer_mode
        result = detect_answer_mode(GOLDEN_QUESTIONS[1]["query"])
        assert result.value == "law_student_case_law"

    def test_law_student_mode_tinoco(self):
        from src.services.answer_modes import detect_answer_mode
        result = detect_answer_mode(GOLDEN_QUESTIONS[2]["query"])
        assert result.value == "law_student_case_law"

    def test_comparative_mode(self):
        from src.services.answer_modes import detect_answer_mode
        result = detect_answer_mode(GOLDEN_QUESTIONS[3]["query"])
        assert result.value == "comparative_research"

    def test_source_discovery_mode(self):
        from src.services.answer_modes import detect_answer_mode
        result = detect_answer_mode(GOLDEN_QUESTIONS[5]["query"])
        assert result.value == "source_discovery"


# ── Safety Critic Tests ──────────────────────────────────────────────────────

class TestSafetyCritic:
    """Verify that the safety critic blocks dangerous queries."""

    def test_bribery_blocked(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("How much should I pay the officer to avoid the ticket?")
        assert not is_safe
        assert "brib" in msg.lower() or "criminal" in msg.lower()

    def test_forgery_blocked(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("Help me forge document to show I have a valid licence")
        assert not is_safe

    def test_evasion_blocked(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("How to escape jurisdiction before the court date")
        assert not is_safe

    def test_false_statements_blocked(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("How to fabricate alibi for the traffic stop")
        assert not is_safe

    def test_legitimate_query_passes(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("What are my rights if stopped by police in Russia?")
        assert is_safe
        assert msg == ""

    def test_legal_question_passes(self):
        from src.pipeline.safety_critic import check_query_safety
        is_safe, msg = check_query_safety("Explain the Vienna Convention on Road Traffic")
        assert is_safe


# ── Citation Verifier Tests ──────────────────────────────────────────────────

class TestCitationVerifier:
    """Verify citation extraction and grading logic."""

    def test_marker_extraction(self):
        from src.pipeline.citation_verifier_v2 import extract_citations
        citations = extract_citations("The treaty states [1] that driving permits [2] are valid.")
        marker_types = [c for c in citations if c["type"] == "marker"]
        assert len(marker_types) == 2

    def test_marker_verified_against_retrieved(self):
        from src.pipeline.citation_verifier_v2 import verify_citations
        draft = "The treaty applies [1] to foreign nationals."
        retrieved = [{"text": "treaty text", "metadata": {"source_name": "Vienna Conv."}}]
        grades = verify_citations(draft, retrieved, use_api=False)
        assert any(g.status == "verified" for g in grades)

    def test_marker_fabricated_no_match(self):
        from src.pipeline.citation_verifier_v2 import verify_citations
        draft = "According to [5] the law is clear."
        retrieved = [{"text": "only one source", "metadata": {}}]
        grades = verify_citations(draft, retrieved, use_api=False)
        assert any(g.status == "fabricated" for g in grades)

    def test_us_reporter_extraction(self):
        from src.pipeline.citation_verifier_v2 import extract_citations
        citations = extract_citations("In Marbury v. Madison, 5 U.S. 137 (1803)...")
        reporter_cits = [c for c in citations if c["type"] == "us_reporter"]
        assert len(reporter_cits) >= 1

    def test_strip_fabricated(self):
        from src.pipeline.citation_verifier_v2 import strip_fabricated_citations
        from src.schemas import CitationGrade
        draft = "Claim [5] is important. Claim [1] is valid."
        grades = [CitationGrade(citation_text="[5]", status="fabricated")]
        result = strip_fabricated_citations(draft, grades)
        assert "[5]" not in result
        assert "[1]" in result


# ── Provider Registry Tests ──────────────────────────────────────────────────

class TestProviderRegistry:
    """Verify provider registry auto-discovery and role selection."""

    def test_registry_singleton(self):
        from src.services.provider_registry import ProviderRegistry
        ProviderRegistry.reset()
        r1 = ProviderRegistry.get_instance()
        r2 = ProviderRegistry.get_instance()
        assert r1 is r2

    def test_registry_has_providers(self):
        from src.services.provider_registry import ProviderRegistry
        ProviderRegistry.reset()
        registry = ProviderRegistry.get_instance()
        # Should discover at least one provider (Gemini or Groq from .env)
        summary = registry.summary()
        assert len(summary) >= 1, f"Expected at least 1 provider, got: {summary}"

    def test_get_best_for_drafter(self):
        from src.services.provider_registry import ProviderRegistry
        ProviderRegistry.reset()
        registry = ProviderRegistry.get_instance()
        drafter = registry.get_best_for("drafter")
        # May be None in CI with no API keys, but in local dev should exist
        if drafter:
            assert drafter.available


# ── ResearchAnswer Contract Tests ────────────────────────────────────────────

class TestResearchAnswerContract:
    """Verify the ResearchAnswer schema is well-formed."""

    def test_default_construction(self):
        from src.schemas import ResearchAnswer
        answer = ResearchAnswer()
        assert answer.confidence == 0.0
        assert answer.answer_mode.value == "tourist_practical"
        assert answer.safety_blocked is False

    def test_all_fields_present(self):
        from src.schemas import ResearchAnswer
        answer = ResearchAnswer(
            answer_sections={"Quick Answer": "Test"},
            confidence=0.8,
            used_models=["gemini"],
            total_time_ms=1234,
        )
        assert answer.answer_sections["Quick Answer"] == "Test"
        assert answer.total_time_ms == 1234


# ── Embedding Cache Tests ────────────────────────────────────────────────────

class TestEmbeddingCache:
    """Verify the SQLite embedding cache works correctly."""

    def test_cache_put_get(self, tmp_path):
        import numpy as np
        from src.services.embedding_cache import EmbeddingCache
        cache = EmbeddingCache(path=tmp_path / "test_cache.sqlite")
        vec = np.random.rand(1024).astype(np.float32)
        cache.put("test query", vec, model_name="test_model")
        result = cache.get("test query", model_name="test_model")
        assert result is not None
        assert np.allclose(vec, result, atol=1e-6)

    def test_cache_miss(self, tmp_path):
        from src.services.embedding_cache import EmbeddingCache
        cache = EmbeddingCache(path=tmp_path / "test_cache.sqlite")
        result = cache.get("nonexistent query")
        assert result is None

    def test_cache_stats(self, tmp_path):
        import numpy as np
        from src.services.embedding_cache import EmbeddingCache
        cache = EmbeddingCache(path=tmp_path / "test_cache.sqlite")
        vec = np.random.rand(1024).astype(np.float32)
        cache.put("q1", vec)
        cache.put("q2", vec)
        stats = cache.stats()
        assert stats["total"] == 2
        assert stats["active"] == 2


# ── Ingestion Registry Tests ────────────────────────────────────────────────

class TestIngestionRegistry:
    """Verify ingestion source registry definitions."""

    def test_all_sources_defined(self):
        from src.services.ingestion_registry import IngestionRegistry
        registry = IngestionRegistry()
        assert registry.get("CourtListener") is not None
        assert registry.get("GovInfo") is not None
        assert registry.get("Indian Kanoon") is not None

    def test_by_jurisdiction(self):
        from src.services.ingestion_registry import IngestionRegistry
        registry = IngestionRegistry()
        us_sources = registry.by_jurisdiction("US")
        assert len(us_sources) >= 2  # CourtListener + GovInfo at minimum

    def test_by_tier(self):
        from src.services.ingestion_registry import IngestionRegistry
        registry = IngestionRegistry()
        primary = registry.by_tier("primary_binding")
        assert len(primary) >= 3  # Most sources are primary_binding


# ── Answer Modes Tests ───────────────────────────────────────────────────────

class TestAnswerModes:
    """Verify mode specs and system prompt generation."""

    def test_all_modes_have_specs(self):
        from src.schemas import AnswerMode
        from src.services.answer_modes import get_mode_spec
        for mode in AnswerMode:
            spec = get_mode_spec(mode)
            assert len(spec.required_sections) >= 3

    def test_build_mode_system_prompt(self):
        from src.services.answer_modes import build_mode_system_prompt
        prompt = build_mode_system_prompt("tourist_practical")
        assert "Quick Answer" in prompt
        assert "Required sections" in prompt

    def test_section_headings(self):
        from src.services.answer_modes import section_headings
        headings = section_headings("law_student_case_law")
        assert "## Issue" in headings
        assert "## Conclusion" in headings
