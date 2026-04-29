"""Adapter for OpenNyAI Indian Legal NLP enrichment."""
from __future__ import annotations

from typing import Any
from pathlib import Path


def enrich_text(text: str) -> dict[str, Any]:
    """Best-effort local OpenNyAI enrichment.

    The OpenNyAI package is optional and heavy. Runtime callers can use this
    helper after fetching Indian judgments; if the package is unavailable, the
    result is explicit and non-fatal.
    """
    try:
        import opennyai  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "reason": f"OpenNyAI package unavailable: {type(exc).__name__}: {exc}",
            "entities": [],
            "rhetorical_roles": [],
        }

    try:
        # OpenNyAI has had a few public APIs across releases. Keep the call
        # defensive and return metadata rather than failing ingestion.
        if hasattr(opennyai, "Pipeline"):
            pipeline = opennyai.Pipeline()
            result = pipeline(text)
            return {"available": True, "raw": result}
        return {
            "available": True,
            "reason": "OpenNyAI imported, but no known Pipeline API was found.",
            "entities": [],
            "rhetorical_roles": [],
        }
    except Exception as exc:
        return {
            "available": False,
            "reason": f"OpenNyAI enrichment failed: {type(exc).__name__}: {exc}",
            "entities": [],
            "rhetorical_roles": [],
        }

def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int,
    max_bytes: int,
    mode: str,
    checkpoint: dict[str, dict[str, Any]],
    resume: bool,
    ingest: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Report OpenNyAI availability for enrichment.

    OpenNyAI is an enrichment stage for Indian judgments rather than a primary
    legal authority source. It should not create standalone legal sources.
    """
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    
    source_name = record.name if hasattr(record, "name") else "OpenNyAI"
    availability = enrich_text("Sample Indian legal judgment text for availability check.")
    events.append({
        "type": "enrichment_adapter",
        "source": source_name,
        "available": availability.get("available", False),
        "reason": availability.get("reason", "OpenNyAI enrichment adapter ready"),
    })
    
    return chunks, events
