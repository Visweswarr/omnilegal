"""OmniLegal v3 — Tier-2 pillars router.

Adds endpoints for:
  • /api/diff/compare        — Statute Diff Engine (Pillar 09)
  • /api/reports/*           — Saved Reports + public share (Pillar 13)
  • /api/redteam/analyze     — Argument Workbench (Pillar 11)
  • /api/doctrine/track      — Doctrine Time Machine (Pillar 08)
  • /api/graph/build         — Citation Graph (Pillar 07)
  • /api/reading/annotate    — Reading Studio (Pillar 12)
  • /api/voice/verify_chunk  — Voice Coach streaming verify (Pillar 10)
  • /api/voice/finalize      — Voice Coach final report

All endpoints are async wrappers around CPU/IO-bound service calls.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("omnilegal.api_v3")

router = APIRouter(prefix="/api", tags=["omnilegal_v3_tier2"])


# ── Schemas ────────────────────────────────────────────────────────────────


class DiffRequest(BaseModel):
    left: str
    right: str
    left_label: str = "Left"
    right_label: str = "Right"


class ReportSaveRequest(BaseModel):
    kind: str
    title: str
    payload: dict[str, Any]


class ReportListQuery(BaseModel):
    kind: str | None = None
    limit: int = 100


class RedteamRequest(BaseModel):
    text: str
    mode: str = Field(default="argument", description="argument | contract | treaty")


class DoctrineRequest(BaseModel):
    doctrine: str
    jurisdiction: str = "Comparative"


class GraphRequest(BaseModel):
    seed: str
    max_nodes: int = 40


class ReadingRequest(BaseModel):
    text: str


class VoiceChunkRequest(BaseModel):
    text: str


class VoiceFinalizeRequest(BaseModel):
    transcript: str


# ── Diff (Pillar 09) ───────────────────────────────────────────────────────


@router.post("/diff/compare")
async def diff_compare(req: DiffRequest) -> dict[str, Any]:
    try:
        from src.services.diff_service import diff_statutes
        return await asyncio.to_thread(
            diff_statutes,
            req.left, req.right,
            left_label=req.left_label, right_label=req.right_label,
        )
    except Exception as exc:
        log.exception("diff_compare failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Reports (Pillar 13) ────────────────────────────────────────────────────


@router.post("/reports")
async def reports_save(req: ReportSaveRequest) -> dict[str, Any]:
    try:
        from src.services.reports_service import save_report
        return await asyncio.to_thread(save_report, req.kind, req.title, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        log.exception("reports_save failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/reports")
async def reports_list(kind: str | None = None, limit: int = 100) -> dict[str, Any]:
    try:
        from src.services.reports_service import list_reports
        items = await asyncio.to_thread(list_reports, kind, limit)
        return {"items": items, "count": len(items)}
    except Exception as exc:
        log.exception("reports_list failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/reports/{report_id}")
async def reports_get(report_id: str) -> dict[str, Any]:
    from src.services.reports_service import get_report
    rec = await asyncio.to_thread(get_report, report_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Report not found.")
    return rec


@router.delete("/reports/{report_id}")
async def reports_delete(report_id: str) -> dict[str, Any]:
    from src.services.reports_service import delete_report
    ok = await asyncio.to_thread(delete_report, report_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Report not found.")
    return {"deleted": report_id}


@router.get("/share/{token}")
async def reports_share(token: str) -> dict[str, Any]:
    from src.services.reports_service import get_by_share_token
    rec = await asyncio.to_thread(get_by_share_token, token)
    if not rec:
        raise HTTPException(status_code=404, detail="Share link is invalid.")
    return rec


# ── Red Team (Pillar 11) ───────────────────────────────────────────────────


@router.post("/redteam/analyze")
async def redteam_analyze(req: RedteamRequest) -> dict[str, Any]:
    try:
        from src.services.redteam_service import redteam
        return await asyncio.to_thread(redteam, req.text, req.mode)
    except Exception as exc:
        log.exception("redteam_analyze failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Doctrine Time Machine (Pillar 08) ──────────────────────────────────────


@router.post("/doctrine/track")
async def doctrine_track(req: DoctrineRequest) -> dict[str, Any]:
    try:
        from src.services.doctrine_service import track_doctrine
        return await asyncio.to_thread(track_doctrine, req.doctrine, req.jurisdiction)
    except Exception as exc:
        log.exception("doctrine_track failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Graph (Pillar 07) ──────────────────────────────────────────────────────


@router.post("/graph/build")
async def graph_build(req: GraphRequest) -> dict[str, Any]:
    try:
        from src.services.graph_service import build_graph
        return await asyncio.to_thread(build_graph, req.seed, req.max_nodes)
    except Exception as exc:
        log.exception("graph_build failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Reading Studio (Pillar 12) ─────────────────────────────────────────────


@router.post("/reading/annotate")
async def reading_annotate(req: ReadingRequest) -> dict[str, Any]:
    try:
        from src.services.reading_service import annotate
        return await asyncio.to_thread(annotate, req.text)
    except Exception as exc:
        log.exception("reading_annotate failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Voice Coach (Pillar 10) ────────────────────────────────────────────────


@router.post("/voice/verify_chunk")
async def voice_verify_chunk(req: VoiceChunkRequest) -> dict[str, Any]:
    try:
        from src.services.voice_service import verify_chunk
        return await asyncio.to_thread(verify_chunk, req.text)
    except Exception as exc:
        log.exception("voice_verify_chunk failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/voice/finalize")
async def voice_finalize(req: VoiceFinalizeRequest) -> dict[str, Any]:
    try:
        from src.services.voice_service import finalize_session
        return await asyncio.to_thread(finalize_session, req.transcript)
    except Exception as exc:
        log.exception("voice_finalize failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
