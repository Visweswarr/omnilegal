"""Launcher: start Chainlit with a middleware that normalises bad language codes.

Browsers sometimes send `language=en-US@posix` which trips Chainlit 2.x's
strict validator. We strip the @… suffix before the request hits the route.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("CHAINLIT_APP_ROOT", "/app")


def _patch_language_middleware() -> None:
    """Add a Starlette middleware that normalises the `language` query param."""
    from chainlit.server import app

    @app.middleware("http")
    async def fix_language(request, call_next):
        # Pre-normalise the `language` query parameter in-place
        qp = request.scope.get("query_string", b"")
        if qp:
            q = qp.decode("latin-1")
            q2 = re.sub(
                r"(language=)([^&]+)",
                lambda m: m.group(1) + re.sub(r"[@;].*$", "", m.group(2)),
                q,
            )
            if q2 != q:
                request.scope["query_string"] = q2.encode("latin-1")
        return await call_next(request)


def main() -> None:
    # Import chainlit's CLI config and bootstrap without running the CLI itself.
    from chainlit.cli import run_chainlit

    # Apply the middleware BEFORE chainlit takes over — we import the server
    # which triggers app construction.
    _patch_language_middleware()

    # Mount OmniLegal /api/* routes on Chainlit's FastAPI app so external
    # callers (FastAPI sidecar proxy on :8001) and internal Chainlit code
    # share the same Qdrant client (embedded mode is single-process).
    try:
        from src.api_router import attach_to_chainlit_app

        attach_to_chainlit_app()
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger("omnilegal.run_chainlit").exception(
            "Failed to attach OmniLegal API router: %s", exc
        )

    target = Path(__file__).resolve().parent / "chainlit_app.py"
    # Preserve CLI-like args for run_chainlit
    sys.argv = [
        "chainlit",
        "run",
        str(target),
        "--host",
        os.environ.get("CHAINLIT_HOST", "0.0.0.0"),
        "--port",
        os.environ.get("CHAINLIT_PORT", "3000"),
        "--headless",
    ]
    run_chainlit(str(target))


if __name__ == "__main__":
    main()
