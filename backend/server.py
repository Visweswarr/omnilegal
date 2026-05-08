"""OmniLegal sidecar on port 8001.

The PRIMARY OmniLegal app is the Chainlit console on port 3000, which now
mounts ``/api/*`` routes directly on its own FastAPI server (see
``src.api_router.attach_to_chainlit_app``). Embedded Qdrant is single-process,
so the production-correct architecture is "one process owns Qdrant".

This sidecar runs in supervisor's ``backend`` slot purely to satisfy the
Kubernetes ingress contract (``/api/*`` → 8001). It transparently proxies
every request to ``http://localhost:3000/api/...`` so callers don't need to
care.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import Response

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env", override=False)

log = logging.getLogger("omnilegal.sidecar")

CHAINLIT_PORT = int(os.environ.get("CHAINLIT_PORT", "3000"))
CHAINLIT_BASE = f"http://127.0.0.1:{CHAINLIT_PORT}"
PROXY_TIMEOUT_SECONDS = float(os.environ.get("OMNILEGAL_PROXY_TIMEOUT_SECONDS", "300"))

app = FastAPI(
    title="OmniLegal Backend Sidecar",
    description="Transparent /api/* proxy to the Chainlit console.",
    version="2.0.0",
)


@app.get("/api/__sidecar_health")
async def sidecar_health() -> dict:
    return {"status": "ok", "proxies_to": CHAINLIT_BASE}


_HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "transfer-encoding",
    "upgrade",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
}


@app.api_route(
    "/api/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
)
async def proxy_to_chainlit(path: str, request: Request) -> Response:
    """Forward every /api/* request to Chainlit's mounted router."""
    method = request.method.upper()
    qs = request.url.query
    target = f"{CHAINLIT_BASE}/api/{path}"
    if qs:
        target = f"{target}?{qs}"

    body_bytes = await request.body()
    fwd_headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    fwd_headers.setdefault("X-OmniLegal-Forwarded", "true")

    timeout = httpx.Timeout(PROXY_TIMEOUT_SECONDS, connect=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            upstream = await client.request(
                method, target, content=body_bytes, headers=fwd_headers,
            )
    except httpx.TimeoutException as exc:
        log.warning("Chainlit upstream timeout: %s", exc)
        return Response(
            status_code=504,
            content=f'{{"detail":"Chainlit upstream timed out: {exc}"}}',
            media_type="application/json",
        )
    except httpx.HTTPError as exc:
        log.warning("Chainlit upstream error: %s", exc)
        return Response(
            status_code=502,
            content=f'{{"detail":"Chainlit upstream unreachable: {exc}"}}',
            media_type="application/json",
        )

    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in _HOP_BY_HOP_HEADERS
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )
