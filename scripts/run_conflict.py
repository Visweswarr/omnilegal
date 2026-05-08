"""Run a one-shot multi-jurisdiction conflict analysis and emit JSON.

Used by the FastAPI ``POST /api/conflict/analyze`` endpoint as a short-lived
subprocess so it doesn't compete with Chainlit for the embedded Qdrant lock.

Usage:
    python scripts/run_conflict.py "<query>" "india,us,uk,russia,israel"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: run_conflict.py <query> [<jurisdictions_csv>]", file=sys.stderr)
        return 2
    query = sys.argv[1]
    jurisdictions = (
        [j.strip() for j in sys.argv[2].split(",") if j.strip()]
        if len(sys.argv) > 2 else
        ["india", "us", "uk", "russia", "israel"]
    )
    try:
        from src.services.conflict_detection import analyze_multi_jurisdiction_conflict

        payload = analyze_multi_jurisdiction_conflict(query, jurisdictions)
    except Exception as exc:
        payload = {
            "error": f"{type(exc).__name__}: {exc}",
            "query": query,
            "verdict": "error",
            "verdict_human": str(exc),
        }
    print("<<<JSON")
    print(json.dumps(payload, ensure_ascii=False))
    print("JSON>>>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
