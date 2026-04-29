from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


JurisdictionLabel = Literal["international", "indian", "mixed", "unknown"]
UsageMode = Literal["runtime", "training", "evaluation", "reference"]
DocumentTypeLabel = Literal[
    "treaty",
    "constitutional_text",
    "case_law",
    "commentary",
    "resolution",
    "mixed_legal_text",
    "unknown",
]
ConflictLabel = Literal["alignment", "qualified_alignment", "conflict", "neutral"]
StanceLabel = Literal["support", "qualified_support", "oppose", "insufficient_signal"]


class Citation(BaseModel):
    marker: str | None = None
    source_name: str
    jurisdiction: str = "N/A"
    page: str | int | None = None
    excerpt: str = ""
    article: str | None = None
    notes: str | None = None


class ProvenanceRecord(BaseModel):
    donor_id: str
    donor_label: str
    capability: str
    usage_mode: UsageMode = "reference"
    notes: str | None = None


class RetrievedPassage(BaseModel):
    citation: Citation
    content: str
    rank: int
    relevance_score: float | None = None
    document_type: str | None = None
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class EntityTag(BaseModel):
    text: str
    label: str
    start: int
    end: int
    source: str = "hybrid"


class EntityIntakeResult(BaseModel):
    original_text: str
    entities: list[EntityTag] = Field(default_factory=list)
    jurisdiction: JurisdictionLabel = "unknown"
    document_type: DocumentTypeLabel = "unknown"
    confidence: float | None = None
    html: str | None = None


class QaResult(BaseModel):
    query: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sources: list[RetrievedPassage] = Field(default_factory=list)
    jurisdictions_considered: list[str] = Field(default_factory=list)
    legal_domains: list[str] = Field(default_factory=list)
    grounding_status: Literal["primary_present", "secondary_only", "no_authority"] = "no_authority"
    authority_gaps: list[str] = Field(default_factory=list)
    answer_style: Literal["short", "long"] = "long"
    insufficient_context: bool = True
    sections: dict[str, str] = Field(default_factory=dict)
    used_model: str
    used_groq: bool = False
    comparative: bool = False
    retrieval_strategy: str = "hybrid"
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class CouncilSubmission(BaseModel):
    expert: str
    answer: str
    source: str
    confidence: float | None = None


class CouncilResult(BaseModel):
    query: str
    verdict: str
    council_answers: list[CouncilSubmission] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    supporting_context: list[RetrievedPassage] = Field(default_factory=list)
    supporting_qa: QaResult | None = None
    used_model: str = "hybrid_council"
    used_groq: bool = False


class ConflictResult(BaseModel):
    domestic_text: str
    international_text: str
    label: ConflictLabel
    status: str
    confidence: float
    color: str
    explanation: str
    counterpart_citation: Citation | None = None
    rationale_spans: list[str] = Field(default_factory=list)
    source_citations: list[Citation] = Field(default_factory=list)
    raw_label: str = ""


class StanceResult(BaseModel):
    issue: str
    stance_label: StanceLabel
    confidence: float
    rationale: str
    top_domestic_authorities: list[Citation] = Field(default_factory=list)
    supporting_international_authorities: list[Citation] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    used_model: str = "baseline"


class BriefSection(BaseModel):
    heading: str
    content: str


class BriefResult(BaseModel):
    issue: str
    sections: list[BriefSection] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    stance: StanceResult | None = None
    conflict: ConflictResult | None = None
    supporting_qa: QaResult | None = None
    extractive_fallback: str | None = None
    summary_mode: str = "template"
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    used_model: str = "template_baseline"


class EvaluationMetric(BaseModel):
    name: str
    value: float | None = None
    display_value: str | None = None
    notes: str | None = None


class EvaluationArtifact(BaseModel):
    task: str
    benchmark: str
    split: str
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_file: str | None = None
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


class ArgumentSpan(BaseModel):
    label: Literal["claim", "premise", "authority", "counterargument", "rebuttal", "policy"]
    text: str
    citation: Citation | None = None
    importance: float = 0.0
    notes: str | None = None


class ArgumentMap(BaseModel):
    issue: str
    spans: list[ArgumentSpan] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    used_model: str = "heuristic_argument_miner"


class DebateLine(BaseModel):
    text: str
    purpose: Literal["opening", "poi", "rebuttal", "red_line"]
    citations: list[Citation] = Field(default_factory=list)


class DebateCard(BaseModel):
    issue: str
    opening_bullets: list[DebateLine] = Field(default_factory=list)
    likely_pois: list[DebateLine] = Field(default_factory=list)
    rebuttals: list[DebateLine] = Field(default_factory=list)
    negotiation_red_lines: list[DebateLine] = Field(default_factory=list)
    argument_map: ArgumentMap | None = None
    brief: BriefResult | None = None
    provenance: list[ProvenanceRecord] = Field(default_factory=list)
    used_model: str = "template_debate_coach"


class BenchmarkRun(BaseModel):
    task: str
    title: str
    status: Literal["ready", "completed", "manual_review", "error"]
    datasets: list[str] = Field(default_factory=list)
    summary: str
    notes: list[str] = Field(default_factory=list)
    artifact: EvaluationArtifact | None = None
    provenance: list[ProvenanceRecord] = Field(default_factory=list)


# ── New schemas for the full LangGraph pipeline ────────────────────────────


class InputClass(str, Enum):
    question = "question"
    treaty = "treaty"
    news_claim = "news_claim"
    statement = "statement"


class LegalIssueLabel(str, Enum):
    use_of_force = "use_of_force_jus_ad_bellum"
    ihl = "ihl_jus_in_bello"
    human_rights = "human_rights"
    criminal_procedure = "criminal_procedure"
    traffic_offences = "traffic_offences"
    immigration_mobility = "immigration_and_mobility"
    consular_assistance = "consular_assistance"
    law_of_the_sea = "law_of_the_sea"
    treaty_interpretation = "treaty_interpretation"
    state_responsibility = "state_responsibility"
    statehood_and_recognition = "statehood_and_recognition"
    jurisdiction_and_immunity = "jurisdiction_and_immunity"
    international_criminal_law = "international_criminal_law"
    diplomatic_relations = "diplomatic_relations"
    environment_intl = "international_environmental_law"
    trade_wto = "trade_and_wto"
    refugee_asylum = "refugee_and_asylum"
    arms_control = "arms_control_and_disarmament"
    cyber_law = "cyber_and_digital_law"
    general_intl_law = "general_international_law"


class JurisdictionAnalysis(BaseModel):
    jurisdiction: str
    applicable_rules: list[str] = Field(default_factory=list)
    application: str = ""
    conclusion: Literal["lawful", "unlawful", "indeterminate", "lawful_if_conditions"] = "indeterminate"
    conditions_if_any: str | None = None
    confidence: float = 0.0
    citations: list[Citation] = Field(default_factory=list)


class ChunkMetadata(BaseModel):
    source_name: str
    collection: str
    jurisdiction: str = "international"
    doc_type: str = "unknown"
    year: int | None = None
    article_number: str | None = None
    page: int | None = None
    chunk_index: int = 0
    context_prefix: str = ""


class PipelineState(BaseModel):
    raw_input: str
    input_class: InputClass | None = None
    input_confidence: float = 0.0
    entities: EntityIntakeResult | None = None
    issue_labels: list[LegalIssueLabel] = Field(default_factory=list)
    queries: dict[str, Any] = Field(default_factory=dict)
    retrieved: list[RetrievedPassage] = Field(default_factory=list)
    jurisdiction_analyses: list[JurisdictionAnalysis] = Field(default_factory=list)
    draft: str = ""
    verified_draft: str = ""
    citation_grades: dict[str, str] = Field(default_factory=dict)
    final: QaResult | None = None


# ── Council Quality-First Contracts ───────────────────────────────────────────


class AnswerMode(str, Enum):
    tourist_practical = "tourist_practical"
    law_student_case_law = "law_student_case_law"
    comparative_research = "comparative_research"
    source_discovery = "source_discovery"


class CitationGrade(BaseModel):
    citation_text: str
    status: Literal["verified", "unverified", "fabricated", "not_found"]
    reporter_match: bool = False
    api_verified: bool = False
    source_excerpt: str = ""


class CouncilVote(BaseModel):
    drafter_id: str
    provider: str
    model: str
    position: Literal["agree", "disagree", "partial"]
    confidence: float = 0.0
    notes: str = ""


class ResearchAnswer(BaseModel):
    answer_sections: dict[str, str] = Field(default_factory=dict)
    sources: list[RetrievedPassage] = Field(default_factory=list)
    citation_grades: list[CitationGrade] = Field(default_factory=list)
    council_votes: list[CouncilVote] = Field(default_factory=list)
    confidence: float = 0.0
    missing_facts: list[str] = Field(default_factory=list)
    authority_gaps: list[str] = Field(default_factory=list)
    fallback_reason: str = ""
    answer_mode: AnswerMode = AnswerMode.tourist_practical
    skipped_sources: list[str] = Field(default_factory=list)
    degraded_coverage: bool = False
    used_models: list[str] = Field(default_factory=list)
    retrieval_time_ms: int = 0
    total_time_ms: int = 0
    safety_blocked: bool = False
    safety_refusal: str = ""
