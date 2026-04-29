"""Phase 4 local verification runner."""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.cli.doctor import run_checks
from src.config import ALL_COLLECTIONS, COLLECTION_CASE_LAW, COLLECTION_CASE_LAW_GLOBAL, OMNILEGAL_DIR, QDRANT_URL
from src.rag.retriever import search_documents
from src.services.model_cache import gliner_status, model_cache_status


def _run(cmd: list[str]) -> dict:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "cmd": cmd,
        "returncode": proc.returncode,
        "stdout_tail": proc.stdout[-2000:],
        "stderr_tail": proc.stderr[-2000:],
    }


def _qdrant_counts() -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for collection in ALL_COLLECTIONS:
        try:
            with urllib.request.urlopen(f"{QDRANT_URL.rstrip('/')}/collections/{collection}", timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            counts[collection] = payload.get("result", {}).get("points_count")
        except Exception:
            counts[collection] = None
    return counts


def _retrieval_smoke() -> list[dict]:
    queries = [
        "tell me about corfu channel case",
        "Is anticipatory self-defense lawful under Article 51?",
        "Compare international law, Indian law, and EU law on use of force in self-defense.",
        "What Russian legal materials are available in the corpus?",
        "What Israeli Supreme Court sources were ingested?",
    ]
    results = []
    for query in queries:
        hits = search_documents(query, k=3)
        results.append({
            "query": query,
            "hits": len(hits),
            "top_sources": [
                hit.get("metadata", {}).get("source_name", "Unknown")
                for hit in hits[:3]
            ],
        })
    return results


def main() -> None:
    doctor = run_checks()
    pip_check = _run([sys.executable, "-m", "pip", "check"])
    counts = _qdrant_counts()
    retrieval = _retrieval_smoke()
    payload = {
        "doctor_status": doctor.get("status"),
        "doctor_ok": doctor.get("ok"),
        "model_cache": model_cache_status(),
        "gliner": gliner_status(),
        "pip_check": pip_check,
        "qdrant_url": QDRANT_URL,
        "collection_counts": counts,
        "retrieval_smoke": retrieval,
        "artifact_root": str(OMNILEGAL_DIR / "data" / "evals" / "results"),
    }
    print(json.dumps(payload, indent=2, default=str))
    case_law_ready = (counts.get(COLLECTION_CASE_LAW) or 0) > 0 or (counts.get(COLLECTION_CASE_LAW_GLOBAL) or 0) > 0
    local_required_nonzero = all((counts.get(name) or 0) > 0 for name in ["INTL_TREATIES", "NATIONAL_IN", "SHAW_PRIVATE"]) and case_law_ready
    ok = bool(doctor.get("ok")) and pip_check["returncode"] == 0 and local_required_nonzero and all(item["hits"] > 0 for item in retrieval)
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
