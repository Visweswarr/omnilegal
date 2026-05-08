"""OmniLegal v4 — STATE OF THE ART pillars router.

Adds endpoints for capabilities ChatGPT structurally cannot replicate:

  • POST /api/adversarial/find  — Adversarial Case Finder (Pillar 14)
  • POST /api/arbitrage/scan    — Jurisdiction Arbitrage (Pillar 15)
  • POST /api/drift/analyze     — Authority Drift Tracker (Pillar 16)
  • POST /api/sentinel/scan     — Compliance Sentinel (Pillar 17)
  • GET  /api/sentinel/rules    — Sentinel rule catalogue
  • POST /api/stress/test       — Statute Stress Test (Pillar 18)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("omnilegal.api_v4")

router = APIRouter(prefix="/api", tags=["omnilegal_v4_sota"])


# ── Schemas ────────────────────────────────────────────────────────────────


class AdversarialRequest(BaseModel):
    claim: str = Field(..., description="The user's argument or position to attack.")


class ArbitrageRequest(BaseModel):
    scenario: str = Field(..., description="Transaction/business scenario to analyse.")


class DriftRequest(BaseModel):
    query: str = Field(..., description="Doctrine, case name, or rule to track over time.")
    registries: list[str] | None = Field(default=None,
        description="Subset of ['indian_kanoon','courtlistener']. Default: both.")


class SentinelRequest(BaseModel):
    text: str = Field(..., description="Contract / policy / regulation text to scan.")
    max_findings: int = Field(default=24, ge=1, le=80)


class StressTestRequest(BaseModel):
    clause: str = Field(..., description="Statute / regulation clause to stress-test.")


# ── Adversarial ────────────────────────────────────────────────────────────


@router.post("/adversarial/find")
async def adversarial_find(req: AdversarialRequest) -> dict[str, Any]:
    try:
        from src.services.adversarial_service import find_adversarial
        return await asyncio.to_thread(find_adversarial, req.claim)
    except Exception as exc:
        log.exception("adversarial_find failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Arbitrage ──────────────────────────────────────────────────────────────


@router.post("/arbitrage/scan")
async def arbitrage_scan(req: ArbitrageRequest) -> dict[str, Any]:
    try:
        from src.services.arbitrage_service import scan_arbitrage
        return await asyncio.to_thread(scan_arbitrage, req.scenario)
    except Exception as exc:
        log.exception("arbitrage_scan failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Drift ──────────────────────────────────────────────────────────────────


@router.post("/drift/analyze")
async def drift_analyze(req: DriftRequest) -> dict[str, Any]:
    try:
        from src.services.drift_service import analyze_drift
        return await asyncio.to_thread(analyze_drift, req.query, req.registries)
    except Exception as exc:
        log.exception("drift_analyze failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Sentinel ───────────────────────────────────────────────────────────────


@router.post("/sentinel/scan")
async def sentinel_scan(req: SentinelRequest) -> dict[str, Any]:
    try:
        from src.services.sentinel_service import scan as run_scan
        return await asyncio.to_thread(run_scan, req.text, max_findings=req.max_findings)
    except Exception as exc:
        log.exception("sentinel_scan failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/sentinel/rules")
async def sentinel_rules() -> dict[str, Any]:
    try:
        from src.services.sentinel_service import list_rules
        rules = await asyncio.to_thread(list_rules)
        return {"count": len(rules), "rules": rules}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Stress Test ────────────────────────────────────────────────────────────


@router.post("/stress/test")
async def stress_test(req: StressTestRequest) -> dict[str, Any]:
    try:
        from src.services.stress_test_service import stress_test as run_stress
        return await asyncio.to_thread(run_stress, req.clause)
    except Exception as exc:
        log.exception("stress_test failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
