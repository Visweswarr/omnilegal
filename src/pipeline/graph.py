"""
LangGraph state machine — assembles the evidence-first legal analysis pipeline.

**OmniLegal Architecture Standard**:
This ``compiled_graph`` serves as the single source of truth for the RAG and legal
analysis orchestration. ALL user interfaces (Streamlit Pages, Chainlit agents,
FastAPI endpoints) MUST route their primary end-to-end question answering and
analysis workloads through this graph, passing a ``PipelineStateDict``. Do not use
isolated service-layer functions (e.g., calling ``answer_question`` directly).

Pipeline flow:
  START -> classify -> extract_entities -> source_gate -> retrieve
        -> analyze_jurisdictions -> synthesize -> verify_citations -> END

The source_gate node may short-circuit the pipeline when required source
bundles are missing from the vector store.

Usage:
    from src.pipeline.graph import compiled_graph
    result = compiled_graph.invoke({
        "raw_input": "Is anticipatory self-defense lawful?",
        "answer_style": "long",
    })
    answer = result.get("final", {}).get("answer", "")
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.pipeline.classifier import classify_input
from src.pipeline.citation_verifier import verify_citations
from src.pipeline.entity_extractor import extract_entities
from src.pipeline.jurisdiction_analyzer import analyze_jurisdictions
from src.pipeline.retriever_node import retrieve
from src.pipeline.source_gate import source_gate
from src.pipeline.state import PipelineStateDict
from src.pipeline.synthesizer import synthesize
from src.services.gemini_fallback import apply_gemini_fallback


def _should_continue_after_gate(state: PipelineStateDict) -> str:
    """Conditional edge: skip to END if source gate failed."""
    if state.get("insufficient_context"):
        return "end"
    return "retrieve"


def _should_continue_after_retrieve(state: PipelineStateDict) -> str:
    """Conditional edge: skip generation when retrieval sufficiency failed."""
    if state.get("insufficient_context"):
        return "end"
    return "analyze_jurisdictions"


try:
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(PipelineStateDict)

    graph.add_node("classify", classify_input)
    graph.add_node("extract_entities", extract_entities)
    graph.add_node("source_gate", source_gate)
    graph.add_node("retrieve", retrieve)
    graph.add_node("analyze_jurisdictions", analyze_jurisdictions)
    graph.add_node("synthesize", synthesize)
    graph.add_node("verify_citations", verify_citations)
    graph.add_node("gemini_fallback", apply_gemini_fallback)

    graph.add_edge(START, "classify")
    graph.add_edge("classify", "extract_entities")
    graph.add_edge("extract_entities", "source_gate")

    # Conditional: source_gate passes → retrieve; fails → END
    graph.add_conditional_edges(
        "source_gate",
        _should_continue_after_gate,
        {"retrieve": "retrieve", "end": END},
    )

    graph.add_conditional_edges(
        "retrieve",
        _should_continue_after_retrieve,
        {"analyze_jurisdictions": "analyze_jurisdictions", "end": END},
    )
    graph.add_edge("analyze_jurisdictions", "synthesize")
    graph.add_edge("synthesize", "verify_citations")
    graph.add_edge("verify_citations", "gemini_fallback")
    graph.add_edge("gemini_fallback", END)

    compiled_graph = graph.compile()

except ImportError as _exc:
    # Graceful fallback when langgraph is not yet installed
    import traceback
    print(f"Warning: LangGraph not available ({_exc}). Using sequential fallback.")

    class _FallbackGraph:
        def invoke(self, state: dict) -> dict:
            state = classify_input(state)          # type: ignore[arg-type]
            state = extract_entities(state)        # type: ignore[arg-type]
            state = source_gate(state)             # type: ignore[arg-type]
            if state.get("insufficient_context"):
                return state
            state = retrieve(state)                # type: ignore[arg-type]
            if state.get("insufficient_context"):
                return state
            state = analyze_jurisdictions(state)   # type: ignore[arg-type]
            state = synthesize(state)              # type: ignore[arg-type]
            state = verify_citations(state)        # type: ignore[arg-type]
            state = apply_gemini_fallback(state)   # type: ignore[arg-type]
            return state

        async def ainvoke(self, state: dict) -> dict:
            return self.invoke(state)

    compiled_graph = _FallbackGraph()  # type: ignore[assignment]
