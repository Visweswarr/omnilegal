"""Create missing OmniLegal Qdrant collections without deleting existing data."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import ALL_COLLECTIONS, EMBEDDING_DIM, QDRANT_URL


def _request(method: str, path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{QDRANT_URL.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _existing() -> set[str]:
    data = _request("GET", "/collections")
    return {item["name"] for item in data.get("result", {}).get("collections", [])}


def _create(name: str) -> None:
    from src.rag.vector_store import create_collection

    create_collection(name, recreate=False)


def main() -> None:
    try:
        existing = _existing()
    except (urllib.error.URLError, TimeoutError) as exc:
        print(f"Qdrant is not reachable at {QDRANT_URL}: {exc}")
        raise SystemExit(1)

    created = []
    for name in ALL_COLLECTIONS:
        if name in existing:
            continue
        _create(name)
        created.append(name)

    print(json.dumps({
        "qdrant_url": QDRANT_URL,
        "created": created,
        "already_present": sorted(existing & set(ALL_COLLECTIONS)),
        "production_collections": ALL_COLLECTIONS,
    }, indent=2))


if __name__ == "__main__":
    main()
