"""OmniLegal extra REST endpoints, mounted directly on Chainlit's FastAPI
``chainlit.server.app`` instance.

Why mount here? The OmniLegal pipeline (vector store, retrieval, LLM) lives
inside the Chainlit process. Embedded Qdrant is single-process, so any
external sidecar that re-opens the path falls back to an empty SQLite
store. Mounting our routes here lets ``/api/*`` reuse the same Qdrant
client Chainlit already holds.

The supervisor 'backend' slot on port 8001 proxies ``/api/*`` here so the
Kubernetes ingress contract (``/api/* → 8001``) keeps working.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("omnilegal.api")

router = APIRouter(prefix="/api", tags=["omnilegal"])

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Schemas ────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    chainlit_port: int
    qdrant_backend: str
    emergent_llm_configured: bool
    gemini_configured: bool
    groq_configured: bool


class CollectionStat(BaseModel):
    name: str
    points: int


class IngestionStatusResponse(BaseModel):
    collections: list[CollectionStat]
    total_points: int
    law_text_files_present: int
    pdfs_present: int


class IngestionRunRequest(BaseModel):
    include_law_text_files: bool = True
    include_pdfs: bool = False


class IngestionRunResponse(BaseModel):
    written_chunks_per_collection: dict[str, int]
    total_chunks: int
    elapsed_seconds: float
    notes: list[str]


class ConflictAnalyzeRequest(BaseModel):
    query: str = Field(..., description="Domestic-law clause or research question.")
    domestic_jurisdictions: list[str] = Field(
        default_factory=lambda: ["india", "us", "uk", "russia", "israel"],
        description="Domestic jurisdictions to compare against international authority.",
    )


class IRACAnalyzeRequest(BaseModel):
    query: str
    domestic_jurisdictions: list[str] = Field(
        default_factory=lambda: ["india", "us", "uk", "russia", "israel"],
    )


# ── Helpers ────────────────────────────────────────────────────────────────


def _law_text_files_count() -> int:
    base = _PROJECT_ROOT / "Law Text Files"
    if not base.exists():
        return 0
    return sum(1 for p in base.rglob("*.txt") if p.is_file())


def _pdfs_count() -> int:
    base = _PROJECT_ROOT / "data" / "pdfs"
    if not base.exists():
        return 0
    return sum(1 for p in base.glob("*.pdf") if p.is_file())


# ── Routes ─────────────────────────────────────────────────────────────────


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        chainlit_port=int(os.environ.get("CHAINLIT_PORT", "3000")),
        qdrant_backend=os.environ.get("OMNILEGAL_VECTOR_BACKEND", "embedded_qdrant"),
        emergent_llm_configured=bool(os.environ.get("EMERGENT_LLM_KEY")),
        gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
        groq_configured=bool(os.environ.get("GROQ_API_KEY")),
    )


@router.get("/ingestion/status", response_model=IngestionStatusResponse)
async def ingestion_status() -> IngestionStatusResponse:
    from src.config import ALL_COLLECTIONS
    from src.rag.vector_store import get_store

    def _scan() -> tuple[list[CollectionStat], int]:
        store = get_store()
        existing = set(store.available_collections())
        rows: list[CollectionStat] = []
        total = 0
        for col in ALL_COLLECTIONS:
            count = store.collection_point_count(col) if col in existing else 0
            rows.append(CollectionStat(name=col, points=count))
            total += count
        return rows, total

    rows, total = await asyncio.to_thread(_scan)
    return IngestionStatusResponse(
        collections=rows,
        total_points=total,
        law_text_files_present=_law_text_files_count(),
        pdfs_present=_pdfs_count(),
    )


@router.post("/ingestion/run", response_model=IngestionRunResponse)
async def run_ingestion(req: IngestionRunRequest) -> IngestionRunResponse:
    started = time.time()
    written: dict[str, int] = {}
    notes: list[str] = []

    if req.include_law_text_files:
        try:
            from scripts.ingest_law_text_files import ingest_all_law_text_files

            result = await asyncio.to_thread(ingest_all_law_text_files)
            for col, n in result.items():
                written[col] = written.get(col, 0) + n
            notes.append(f"Law Text Files: {len(result)} collections updated.")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Law Text Files ingestion failed: {type(exc).__name__}: {exc}")

    if req.include_pdfs:
        try:
            from src.config import (
                COLLECTION_INTL_TREATIES,
                COLLECTION_NATIONAL_IN,
                COLLECTION_SHAW_PRIVATE,
            )
            from src.rag.ingestion import ingest_collection
            from src.rag.vector_store import upsert_chunks

            for col in (
                COLLECTION_INTL_TREATIES,
                COLLECTION_NATIONAL_IN,
                COLLECTION_SHAW_PRIVATE,
            ):
                try:
                    chunks = await asyncio.to_thread(ingest_collection, col)
                    if chunks:
                        n = await asyncio.to_thread(upsert_chunks, col, chunks)
                        written[col] = written.get(col, 0) + n
                except Exception as exc:  # noqa: BLE001
                    notes.append(f"PDF {col}: {type(exc).__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"PDF block: {type(exc).__name__}: {exc}")

    return IngestionRunResponse(
        written_chunks_per_collection=written,
        total_chunks=sum(written.values()),
        elapsed_seconds=round(time.time() - started, 2),
        notes=notes,
    )


@router.post("/conflict/analyze")
async def conflict_analyze(req: ConflictAnalyzeRequest) -> dict[str, Any]:
    try:
        from src.services.conflict_detection import analyze_multi_jurisdiction_conflict

        return await asyncio.to_thread(
            analyze_multi_jurisdiction_conflict,
            req.query,
            req.domestic_jurisdictions,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.post("/irac/analyze")
async def irac_analyze(req: IRACAnalyzeRequest) -> dict[str, Any]:
    try:
        from src.services.cross_jurisdiction import comparison_payload

        return await asyncio.to_thread(
            comparison_payload, req.query, req.domestic_jurisdictions,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@router.get("/debug/retrieve")
async def debug_retrieve(
    query: str,
    collections: str = "",
    k: int = 6,
) -> dict[str, Any]:
    from src.services.retrieval_qa import retrieve_passages

    cols = [c.strip().upper() for c in collections.split(",") if c.strip()] or None

    def _run() -> list:
        return retrieve_passages(query, k=k, comparative=False, collections=cols)

    passages = await asyncio.to_thread(_run)
    return {
        "query": query,
        "collections": cols,
        "passage_count": len(passages),
        "passages": [
            {
                "source_name": p.citation.source_name,
                "jurisdiction": p.citation.jurisdiction,
                "marker": p.citation.marker,
                "excerpt": p.citation.excerpt or p.content[:240],
            }
            for p in passages
        ],
    }


@router.get("/")
async def index() -> dict[str, Any]:
    return {
        "service": "OmniLegal API",
        "primary_ui": "Chainlit research console on port 3000 (this server).",
        "endpoints": [
            "/api/health",
            "/api/ingestion/status",
            "POST /api/ingestion/run",
            "POST /api/conflict/analyze",
            "POST /api/irac/analyze",
            "/api/debug/retrieve?query=...&collections=COL1,COL2&k=6",
        ],
    }


def attach_to_chainlit_app() -> None:
    """Mount this router onto Chainlit's FastAPI ``app`` instance.

    Chainlit registers a catch-all SPA route ``/{full_path:path}`` at app
    boot, which would otherwise swallow our ``/api/*`` requests. We work
    around that by inserting our router's routes at the FRONT of the route
    table so FastAPI matches them first.
    """
    try:
        from chainlit.server import app as chainlit_app
    except Exception as exc:  # noqa: BLE001
        log.error("Could not import chainlit.server.app: %s", exc)
        return
    chainlit_app.include_router(router)
    # Move our newly added routes ahead of any catch-all paths Chainlit
    # registered earlier so they win the match.
    new_routes = [r for r in chainlit_app.routes if getattr(r, "path", "").startswith("/api")]
    other_routes = [r for r in chainlit_app.routes if r not in new_routes]
    chainlit_app.router.routes = new_routes + other_routes
    log.info(
        "OmniLegal /api/* routes mounted on Chainlit FastAPI app (%d routes promoted).",
        len(new_routes),
    )
