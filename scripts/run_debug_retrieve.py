"""Run a one-shot retrieval test and emit JSON.

Usage:
    python scripts/run_debug_retrieve.py "<query>" "STATUTES_IN,COMMENTARY_GLOBAL" 6
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
        print("usage: run_debug_retrieve.py <query> [<collections_csv>] [<k>]", file=sys.stderr)
        return 2
    query = sys.argv[1]
    collections_csv = sys.argv[2] if len(sys.argv) > 2 else ""
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    cols = [c.strip().upper() for c in collections_csv.split(",") if c.strip()] or None
    try:
        from src.services.retrieval_qa import retrieve_passages

        passages = retrieve_passages(query, k=k, comparative=False, collections=cols)
        payload = {
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
    except Exception as exc:
        payload = {"error": f"{type(exc).__name__}: {exc}", "query": query}
    print("<<<JSON")
    print(json.dumps(payload, ensure_ascii=False))
    print("JSON>>>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
