"""Deterministic jurisdiction analysis from retrieved evidence.

This node intentionally does not call DSPy, Groq, Gemini, zero-shot models, or
any other generative service. Normal chat must stay evidence-first: retrieve
verified sources, summarize what jurisdictions are represented, and let the
citation verifier decide whether a final answer is sufficiently grounded.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.pipeline.state import PipelineStateDict


_JURISDICTION_ALIASES = {
    "india": "in",
    "indian": "in",
    "russia": "ru",
    "russian": "ru",
    "russian federation": "ru",
    "united states": "us",
    "usa": "us",
    "u.s.": "us",
    "american": "us",
    "uk": "gb",
    "united kingdom": "gb",
    "british": "gb",
    "international": "international",
}


def _normalize_jurisdiction(value: Any) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    return _JURISDICTION_ALIASES.get(cleaned, cleaned)


def _source_role(meta: dict[str, Any]) -> str:
    role = str(meta.get("source_role") or "").strip().lower()
    if role:
        return role
    doc_type = str(meta.get("doc_type") or "").strip().lower()
    collection = str(meta.get("collection") or "").strip().upper()
    if doc_type == "treaty" or collection == "INTL_TREATIES":
        return "treaty"
    if doc_type == "case_law":
        return "case_law" if collection == "CASE_LAW_GLOBAL" else "local_case"
    if doc_type in {"statute", "legislation", "code"} or collection.startswith("STATUTES_"):
        return "local_statute"
    if doc_type in {"guidance", "official_guidance"}:
        return "official_guidance"
    if "SHAW" in collection or doc_type == "commentary":
        return "commentary"
    return doc_type or "unknown"


def _clean_excerpt(text: str, *, limit: int = 260) -> str:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return ""
    sentences = re.findall(r"[^.!?\n]{24,500}(?:[.!?]|\n|$)", normalized)
    candidate = sentences[0].strip() if sentences else normalized
    return candidate[:limit].strip()


def _detect_jurisdictions(retrieved: list[dict[str, Any]], iso_codes: list[str]) -> list[str]:
    """Infer jurisdictions strictly from detected ISO codes and retrieved metadata."""
    seen: set[str] = {
        code for code in (_normalize_jurisdiction(code) for code in iso_codes) if code
    }
    for passage in retrieved:
        jurisdiction = _normalize_jurisdiction((passage.get("metadata") or {}).get("jurisdiction"))
        if jurisdiction and jurisdiction not in {"unknown", ""}:
            seen.add(jurisdiction)
    if not seen:
        seen.add("international")
    return sorted(seen)


def _analyze_jurisdiction(jurisdiction: str, passages: list[dict[str, Any]]) -> dict[str, Any]:
    relevant: list[dict[str, Any]] = []
    for passage in passages:
        meta = passage.get("metadata") or {}
        passage_jurisdiction = _normalize_jurisdiction(meta.get("jurisdiction"))
        if passage_jurisdiction == jurisdiction or (
            jurisdiction != "international" and passage_jurisdiction == "international"
        ):
            relevant.append(passage)
    if not relevant and jurisdiction == "international":
        relevant = [
            passage
            for passage in passages
            if _normalize_jurisdiction((passage.get("metadata") or {}).get("jurisdiction")) == "international"
        ]

    applicable_rules: list[dict[str, Any]] = []
    for passage in relevant[:4]:
        meta = passage.get("metadata") or {}
        quote = _clean_excerpt(passage.get("text", ""))
        if not quote:
            continue
        applicable_rules.append(
            {
                "rule": quote,
                "source_name": meta.get("source_name") or meta.get("citation") or "Retrieved source",
                "source_role": _source_role(meta),
                "retrieved_chunk_id": passage.get("id") or meta.get("chunk_id") or meta.get("parent_id"),
                "quote": quote,
            }
        )

    if not applicable_rules:
        return {
            "jurisdiction": jurisdiction,
            "applicable_rules": [],
            "application": "insufficient evidence: no retrieved source for this jurisdiction survived filtering.",
            "conclusion": "indeterminate",
            "conditions_if_any": [],
            "confidence": 0.0,
            "citations": [],
        }

    primary_roles = {"treaty", "case_law", "local_case", "local_statute"}
    has_primary = any(rule.get("source_role") in primary_roles for rule in applicable_rules)
    return {
        "jurisdiction": jurisdiction,
        "applicable_rules": applicable_rules,
        "application": "Evidence summary only; final legal explanation must cite these retrieved source spans.",
        "conclusion": "evidence_available" if has_primary else "secondary_only",
        "conditions_if_any": [],
        "confidence": 0.75 if has_primary else 0.45,
        "citations": [
            {
                "source_name": rule.get("source_name", ""),
                "excerpt": rule.get("quote", ""),
                "retrieved_chunk_id": rule.get("retrieved_chunk_id"),
            }
            for rule in applicable_rules
        ],
    }


def analyze_jurisdictions(state: PipelineStateDict) -> PipelineStateDict:
    retrieved = state.get("retrieved", []) or []
    entities = state.get("entities") or {}
    iso_codes = entities.get("iso_country_codes") or state.get("jurisdictions") or []
    jurisdictions = _detect_jurisdictions(retrieved, iso_codes)
    analyses = [_analyze_jurisdiction(jurisdiction, retrieved) for jurisdiction in jurisdictions]
    return {**state, "jurisdiction_analyses": analyses}
