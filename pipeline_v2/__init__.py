"""OmniLegal pipeline_v2 — lean, verification-first legal RAG.

Public entrypoint: `pipeline_v2.run_query(query, mode, style) -> dict`.
"""
from pipeline_v2.orchestrator import run_query

__all__ = ["run_query"]
