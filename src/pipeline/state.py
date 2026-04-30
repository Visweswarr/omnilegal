"""LangGraph TypedDict state for the legal analysis pipeline."""
from __future__ import annotations

from typing import Any
from typing_extensions import TypedDict


class PipelineStateDict(TypedDict, total=False):
    raw_input: str
    answer_style: str                      # legacy: "short" | "long"
    answer_mode: str                       # "tourist_practical"|"law_student_case_law"|"researcher"|"layman"
    input_class: str                        # InputClass enum value
    input_confidence: float
    entities: dict[str, Any]               # EntityIntakeResult serialized
    issue_labels: list[str]                # LegalIssueLabel enum values
    issue_profile: dict[str, Any]          # issue labels, temporal frame, jurisdictions
    queries: dict[str, str]                # jurisdiction → rewritten query
    retrieved: list[dict[str, Any]]        # RetrievedPassage-like dicts
    jurisdiction_analyses: list[dict[str, Any]]  # JurisdictionAnalysis dicts
    conflicts: list[dict[str, Any]]        # structured conflict callouts
    draft: str
    draft_before_refinement: str           # raw Groq draft before Gemini polish
    gemini_refined: bool                   # whether Gemini refinement was applied
    gemini_mode: str                       # "refinement" or "knowledge_generation"
    gemini_model: str
    gemini_error: str
    refinement_provider: str               # "gemini" or "groq"
    refinement_model: str
    refinement_error: str
    verified_draft: str
    citation_grades: dict[str, str]        # marker → CORRECT|AMBIGUOUS|INCORRECT
    verification_grades: dict[str, Any]    # quote/NLI/self-critique verifier details
    grounding_status: str                  # "primary_present" | "secondary_only" | "no_authority"
    authority_gaps: list[str]
    jurisdictions_considered: list[str]
    legal_domains: list[str]
    answer_sections: dict[str, str]
    insufficient_context: bool
    pipeline_errors: list[str]
    final: dict[str, Any] | None           # QaResult serialized
    query_intent: dict[str, Any]           # {primary: list[str], labels: list[str], priority_collections: dict[str, float], iso_codes: list[str]}
    comparison_mode: bool
    gemini_fallback_used: bool
    gemini_fallback_model: str
    gemini_fallback_cache_hit: bool
    gemini_fallback_error: str
    # Evidence-first pipeline additions
    source_plan: dict[str, Any]            # required roles, target collections, missing sources
    source_availability: dict[str, Any]    # {ok: bool, missing: list[str]}
    regeneration_attempt: int              # citation retry counter (0 = first attempt)
    # Merged pipeline additions (from pipeline_v2)
    mode: str                              # "tourist" | "conflict" | "research"
    jurisdictions: list[str]              # ISO codes detected (e.g. ["US", "IN"])
    doc_types: list[str]                  # detected doc type intents
    provider: str                          # LLM provider used for synthesis
    grounded_ratio: float                 # fraction of cited sentences with valid [S#] tags
    confidence_badge: str                 # visual badge: "🟢 …" | "🟡 …" | "🔴 …"

