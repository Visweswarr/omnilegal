"""OmniLegal supporting REST API.

Runs on port 8001 (supervisor 'backend' slot). The PRIMARY user surface is
the Chainlit console on port 3000 — this backend is a thin sidecar that
exposes ingestion / health / conflict-analysis endpoints without competing
with Chainlit for the embedded Qdrant lock.

Strategy: the backend NEVER imports the vector store directly. Anything
that needs Qdrant is launched as a short-lived subprocess so the lock is
released the moment the request completes. The Chainlit process keeps a
long-lived Qdrant connection in parallel; both can share the on-disk
database because subprocesses run only on demand and Chainlit re-opens
its store after any subprocess exits.

We keep that "subprocess only on demand" rule for:
    POST /api/ingestion/run         → runs scripts/ingest_law_text_files.py
    POST /api/conflict/analyze      → runs scripts/run_conflict.py
    GET  /api/ingestion/status      → runs scripts/print_status.py
    GET  /api/debug/retrieve        → runs scripts/run_debug_retrieve.py

Each subprocess relies on Chainlit having released the embedded Qdrant
lock (Chainlit's qdrant_client opens the path lazily and is happy to
re-open after the lock churn).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env", override=False)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

app = FastAPI(
    title="OmniLegal Backend API",
    description="Supporting REST endpoints for the Chainlit-first OmniLegal console.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_PYTHON_EXEC = "/root/.venv/bin/python"


# ── Schemas ────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    chainlit_port: int
    qdrant_backend: str
    emergent_llm_configured: bool
    gemini_configured: bool
    groq_configured: bool


class IngestionRunRequest(BaseModel):
    include_law_text_files: bool = True
    include_pdfs: bool = False
    include_corpus_seeds: bool = False
    add_context: bool = False


class CollectionStat(BaseModel):
    name: str
    points: int


class IngestionStatusResponse(BaseModel):
    collections: list[CollectionStat]
    total_points: int
    law_text_files_present: int
    pdfs_present: int


class ConflictAnalyzeRequest(BaseModel):
    query: str = Field(..., description="Domestic-law clause or research question.")
    domestic_jurisdictions: list[str] = Field(
        default_factory=lambda: ["india", "us", "uk", "russia", "israel"],
        description="Domestic jurisdictions to compare against international authority.",
    )


class IngestionRunResponse(BaseModel):
    written_chunks_per_collection: dict[str, int]
    total_chunks: int
    elapsed_seconds: float
    notes: list[str]


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


def _run_subprocess(
    script_path: Path,
    extra_args: list[str] | None = None,
    timeout: int = 240,
) -> tuple[int, str, str]:
    """Run a project script in a fresh subprocess so it doesn't compete with
    Chainlit for the embedded Qdrant lock."""
    cmd = [_PYTHON_EXEC, str(script_path)]
    if extra_args:
        cmd.extend(extra_args)
    proc = subprocess.run(
        cmd,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _parse_last_json_block(stdout: str) -> dict[str, Any] | None:
    """Find the last '<<<JSON' / 'JSON>>>' block in script stdout."""
    start_marker = "<<<JSON"
    end_marker = "JSON>>>"
    idx_start = stdout.rfind(start_marker)
    idx_end = stdout.rfind(end_marker)
    if idx_start == -1 or idx_end == -1 or idx_end <= idx_start:
        return None
    payload = stdout[idx_start + len(start_marker) : idx_end].strip()
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


# ── Routes ─────────────────────────────────────────────────────────────────


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        chainlit_port=int(os.environ.get("CHAINLIT_PORT", "3000")),
        qdrant_backend=os.environ.get("OMNILEGAL_VECTOR_BACKEND", "embedded_qdrant"),
        emergent_llm_configured=bool(os.environ.get("EMERGENT_LLM_KEY")),
        gemini_configured=bool(os.environ.get("GEMINI_API_KEY")),
        groq_configured=bool(os.environ.get("GROQ_API_KEY")),
    )


@app.get("/api/ingestion/status", response_model=IngestionStatusResponse)
async def ingestion_status() -> IngestionStatusResponse:
    import asyncio as _asyncio

    def _run() -> tuple[int, str, str]:
        return _run_subprocess(
            _PROJECT_ROOT / "scripts" / "print_status.py",
            timeout=60,
        )

    rc, stdout, stderr = await _asyncio.to_thread(_run)
    payload = _parse_last_json_block(stdout) or {}
    if rc != 0 and not payload:
        return IngestionStatusResponse(
            collections=[], total_points=0,
            law_text_files_present=_law_text_files_count(),
            pdfs_present=_pdfs_count(),
        )
    raw_cols = payload.get("collections") or []
    return IngestionStatusResponse(
        collections=[CollectionStat(**c) for c in raw_cols],
        total_points=int(payload.get("total_points", 0)),
        law_text_files_present=_law_text_files_count(),
        pdfs_present=_pdfs_count(),
    )


@app.post("/api/ingestion/run", response_model=IngestionRunResponse)
async def run_ingestion(req: IngestionRunRequest) -> IngestionRunResponse:
    import asyncio as _asyncio

    started = time.time()
    written: dict[str, int] = {}
    notes: list[str] = []

    if req.include_law_text_files:
        def _run_law() -> tuple[int, str, str]:
            return _run_subprocess(
                _PROJECT_ROOT / "scripts" / "ingest_law_text_files.py",
                timeout=2400,
            )

        rc, stdout, _stderr = await _asyncio.to_thread(_run_law)
        if rc != 0:
            notes.append("Law Text Files ingestion failed (see backend logs).")
        # Parse summary from stdout
        for line in stdout.splitlines():
            if line.strip().startswith("[ok] ") and "→" in line and ":" in line:
                # e.g. "[ok] Indian Law → STATUTES_IN: 3155 chunks indexed"
                try:
                    after_arrow = line.split("→", 1)[1].strip()
                    col, rest = after_arrow.split(":", 1)
                    n = int(rest.strip().split()[0])
                    written[col.strip()] = written.get(col.strip(), 0) + n
                except Exception:
                    pass
        notes.append("Law Text Files: ingestion subprocess complete.")

    if req.include_pdfs:
        def _run_pdfs() -> tuple[int, str, str]:
            return _run_subprocess(
                _PROJECT_ROOT / "scripts" / "bootstrap_corpus.py",
                timeout=3600,
            )

        rc, stdout, _stderr = await _asyncio.to_thread(_run_pdfs)
        notes.append(
            "PDF bootstrap: subprocess complete." if rc == 0 else
            "PDF bootstrap: failed (see backend logs)."
        )

    return IngestionRunResponse(
        written_chunks_per_collection=written,
        total_chunks=sum(written.values()),
        elapsed_seconds=round(time.time() - started, 2),
        notes=notes,
    )


@app.post("/api/conflict/analyze")
async def conflict_analyze(req: ConflictAnalyzeRequest) -> dict[str, Any]:
    import asyncio as _asyncio

    def _run() -> tuple[int, str, str]:
        args = [req.query, ",".join(req.domestic_jurisdictions)]
        return _run_subprocess(
            _PROJECT_ROOT / "scripts" / "run_conflict.py",
            extra_args=args,
            timeout=240,
        )

    rc, stdout, stderr = await _asyncio.to_thread(_run)
    payload = _parse_last_json_block(stdout)
    if rc != 0 or payload is None:
        raise HTTPException(
            status_code=500,
            detail=f"Conflict subprocess rc={rc}; stderr={stderr[-1200:]}",
        )
    return payload


@app.get("/api/debug/retrieve")
async def debug_retrieve(
    query: str,
    collections: str = "",
    k: int = 6,
) -> dict[str, Any]:
    import asyncio as _asyncio

    def _run() -> tuple[int, str, str]:
        args = [query, collections, str(k)]
        return _run_subprocess(
            _PROJECT_ROOT / "scripts" / "run_debug_retrieve.py",
            extra_args=args,
            timeout=120,
        )

    rc, stdout, stderr = await _asyncio.to_thread(_run)
    payload = _parse_last_json_block(stdout)
    if rc != 0 or payload is None:
        raise HTTPException(
            status_code=500,
            detail=f"Debug retrieve subprocess rc={rc}; stderr={stderr[-1200:]}",
        )
    return payload


@app.get("/api/")
async def root() -> dict[str, Any]:
    return {
        "service": "OmniLegal Backend",
        "primary_ui": "Chainlit research console on port 3000",
        "endpoints": [
            "/api/health",
            "/api/ingestion/status",
            "POST /api/ingestion/run",
            "POST /api/conflict/analyze",
            "/api/debug/retrieve?query=...&collections=COL1,COL2&k=6",
        ],
    }
