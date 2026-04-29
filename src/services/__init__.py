"""Service package exports.

Keep this module light: importing ``src.services.remote_sources`` or any
adapter should not initialize retrieval models or Qdrant clients.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS: dict[str, tuple[str, str]] = {
    "build_argument_map": ("src.services.argument_mining", "build_argument_map"),
    "build_debate_card": ("src.services.argument_mining", "build_debate_card"),
    "analyze_conflict": ("src.services.conflict_detection", "analyze_conflict"),
    "analyze_text": ("src.services.entity_intake", "analyze_text"),
    "answer_question": ("src.services.retrieval_qa", "answer_question"),
    "donor_registry_summary": ("src.services.donor_registry", "donor_registry_summary"),
    "generate_issue_brief": ("src.services.brief_generation", "generate_issue_brief"),
    "list_benchmark_runs": ("src.services.benchmarks", "list_benchmark_runs"),
    "load_latest_evaluation_artifact": ("src.services.evaluation", "load_latest_evaluation_artifact"),
    "load_donor_registry": ("src.services.donor_registry", "load_donor_registry"),
    "predict_indian_stance": ("src.services.stance_prediction", "predict_indian_stance"),
    "retrieve_passages": ("src.services.retrieval_qa", "retrieve_passages"),
    "run_model_council": ("src.services.model_council", "run_model_council"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = _EXPORTS[name]
    value = getattr(import_module(module_name), attr)
    globals()[name] = value
    return value
