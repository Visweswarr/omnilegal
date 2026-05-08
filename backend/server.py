"""OmniLegal v3 backend — direct FastAPI host on port 8001.

The earlier proxy-to-Chainlit dance is gone. The backend now owns the
embedded Qdrant client, all retrieval, all LLM calls, and serves the
React shell via the `/api/*` ingress contract.

Routes live in two routers:
  - ``src.api_router.router``      — health, ingestion, conflict, irac, debug
  - ``src.api_router_v2.router``   — atlas, forensics, advocacy, live,
                                     council, research, overview
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env BEFORE importing any module that reads env vars at import time.
load_dotenv(_PROJECT_ROOT / ".env", override=False)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("omnilegal.backend")

app = FastAPI(
    title="OmniLegal API",
    description="Verified legal intelligence — Atlas, Forensics, Advocacy, Live, Council, Research.",
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/__sidecar_health")
async def sidecar_health() -> dict[str, str]:
    return {"status": "ok", "service": "omnilegal-backend"}


# Wire routers — failure to import the heavy stack should NOT prevent the
# backend from booting (we want curl /api/__sidecar_health to keep working).
try:
    from src.api_router import router as legacy_router  # noqa: E402

    app.include_router(legacy_router)
    log.info("Mounted legacy router (health, ingestion, conflict, irac, debug).")
except Exception as exc:  # noqa: BLE001
    log.exception("Failed to mount legacy router: %s", exc)

try:
    from src.api_router_v2 import router as v3_router  # noqa: E402

    app.include_router(v3_router)
    log.info("Mounted v3 router (atlas, forensics, advocacy, live, council, research, overview).")
except Exception as exc:  # noqa: BLE001
    log.exception("Failed to mount v3 router: %s", exc)

try:
    from src.api_router_v3 import router as tier2_router  # noqa: E402

    app.include_router(tier2_router)
    log.info("Mounted Tier-2 router (diff, reports, redteam, doctrine, graph, reading, voice).")
except Exception as exc:  # noqa: BLE001
    log.exception("Failed to mount Tier-2 router: %s", exc)

try:
    from src.api_router_v4 import router as sota_router  # noqa: E402

    app.include_router(sota_router)
    log.info("Mounted SOTA router (adversarial, arbitrage, drift, sentinel, stress).")
except Exception as exc:  # noqa: BLE001
    log.exception("Failed to mount SOTA router: %s", exc)


@app.get("/api")
async def index() -> dict[str, object]:
    return {
        "service": "OmniLegal API v3",
        "tagline": "The Verdict, the Map, the Proof.",
        "endpoints": {
            "health":        "/api/health",
            "overview":      "/api/overview",
            "atlas":         "POST /api/atlas/analyze",
            "forensics":     "POST /api/forensics/verify",
            "advocacy":      "POST /api/advocacy/generate",
            "live":          "POST /api/live/search",
            "council":       "POST /api/council/debate",
            "research":      "POST /api/research/ask",
            "ingestion":     "GET /api/ingestion/status",
            "conflict":      "POST /api/conflict/analyze",
            "irac":          "POST /api/irac/analyze",
            "debug":         "GET /api/debug/retrieve",
        },
        "council_members": [
            "Claude Sonnet 4.5 (Emergent)",
            "Gemini 2.5 Flash (Google)",
            "Llama 3.3 70B (Groq)",
        ],
        "live_sources": [
            "Indian Kanoon", "CourtListener", "GovInfo",
            "EUR-Lex", "HUDOC (ECHR)", "UN Treaty Index",
        ],
        "vector_backend": os.environ.get("OMNILEGAL_VECTOR_BACKEND", "embedded_qdrant"),
    }
