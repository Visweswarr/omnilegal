"""OmniLegal v5 — Comparative Answer mode router (Pillar 19).

Adds:
  POST /api/compare/analyze   — full parallel IRAC-per-jurisdiction with
                                 Kuzu citation-graph cross-citations.
  GET  /api/compare/jurisdictions — list of supported jurisdictions.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("omnilegal.api_v5")

router = APIRouter(prefix="/api", tags=["omnilegal_v5_comparative"])


# ── Schemas ────────────────────────────────────────────────────────────────


class CompareRequest(BaseModel):
    query: str = Field(..., description="Legal research question to compare across jurisdictions.")
    jurisdictions: list[str] | None = Field(
        default=None,
        description=(
            "List of jurisdiction keys, e.g. ['india', 'us', 'uk']. "
            "Defaults to ['india', 'us', 'uk'] if not specified."
        ),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/compare/analyze")
async def compare_analyze(req: CompareRequest) -> dict[str, Any]:
    """Run parallel IRAC for each requested jurisdiction and synthesise.

    The pipeline:
      1. Fan-out Qdrant retrieval per jurisdiction.
      2. Kuzu citation-graph traversal for cross-jurisdiction precedents.
      3. Per-jurisdiction IRAC (LLM) in a ThreadPoolExecutor.
      4. Cross-jurisdiction synthesis (LLM).
    """
    if not req.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")

    try:
        from src.services.comparative_service import run_comparative
        return await asyncio.to_thread(
            run_comparative,
            req.query.strip(),
            req.jurisdictions,
        )
    except Exception as exc:
        log.exception("compare_analyze failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/compare/jurisdictions")
async def compare_jurisdictions() -> dict[str, Any]:
    """Return the catalogue of supported jurisdictions."""
    try:
        from src.services.comparative_service import SUPPORTED_JURISDICTIONS
        return {"jurisdictions": SUPPORTED_JURISDICTIONS}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Longitudinal schemas ───────────────────────────────────────────────────


class LongitudinalRequest(BaseModel):
    query: str = Field(..., description="Legal concept or question to track over time.")
    jurisdictions: list[str] | None = Field(
        default=None,
        description="Jurisdiction keys, e.g. ['india','us','uk']. Defaults to India, US, UK.",
    )
    periods: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Custom period list: [{label, year_start?, year_end?}]. "
            "If omitted, the preset or default 4-period century view is used."
        ),
    )
    preset: str | None = Field(
        default=None,
        description="Period preset: 'century' | 'postwar' | 'modern'.",
    )


@router.post("/compare/longitudinal")
async def compare_longitudinal(req: LongitudinalRequest) -> dict[str, Any]:
    """Run parallel IRAC + heat-map for every jurisdiction × time-period combination.

    Returns a structured timeline showing how each jurisdiction's recognition
    of the legal concept evolved across the requested periods.
    """
    if not req.query.strip():
        raise HTTPException(status_code=422, detail="query must not be empty")
    try:
        from src.services.longitudinal_service import run_longitudinal
        return await asyncio.to_thread(
            run_longitudinal,
            req.query.strip(),
            req.jurisdictions,
            req.periods,
            req.preset,
        )
    except Exception as exc:
        log.exception("compare_longitudinal failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/compare/period-presets")
async def compare_period_presets() -> dict[str, Any]:
    """Return available period presets for the longitudinal view."""
    try:
        from src.services.longitudinal_service import PERIOD_PRESETS
        return {"presets": {k: [p["label"] for p in v] for k, v in PERIOD_PRESETS.items()}}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
