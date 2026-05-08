"""Print indexed-collection sizes as a JSON payload (for /api/ingestion/status)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    try:
        from src.config import ALL_COLLECTIONS
        from src.rag.vector_store import get_store

        store = get_store()
        existing = set(store.available_collections())
        rows = []
        total = 0
        for col in ALL_COLLECTIONS:
            count = store.collection_point_count(col) if col in existing else 0
            rows.append({"name": col, "points": count})
            total += count
        payload = {"collections": rows, "total_points": total}
    except Exception as exc:
        payload = {"error": f"{type(exc).__name__}: {exc}", "collections": [], "total_points": 0}
    print("<<<JSON")
    print(json.dumps(payload))
    print("JSON>>>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
