"""Sample Qdrant collections and report corpus quality problems."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import ALL_COLLECTIONS, CASE_LAW_COLLECTIONS, DATA_DIR
from src.rag.vector_store import collection_point_count, get_client

BAD_PATTERNS = [
    "use another email",
    "api documentation",
    "github.com",
    "sign in",
    "login",
    "enable javascript",
    "cookie policy",
    "devsecops",
]

EXPECTED_CASE_JURISDICTION = {
    "CASE_LAW_GLOBAL": "international",
    "CASE_LAW_US": "us",
    "CASE_LAW_IN": "in",
    "CASE_LAW_EU": "eu",
    "CASE_LAW_UK": "uk",
    "CASE_LAW_RU": "russia",
    "CASE_LAW_IL": "israel",
}

_SOURCE_METADATA_TYPES = {"source_catalog", "source_map", "project_reference", "ingestion_manifest"}
_JURISDICTION_EQUIVALENTS = {
    "in": {"in", "india", "indian"},
    "ru": {"ru", "russia", "russian federation"},
    "russia": {"ru", "russia", "russian federation"},
    "israel": {"israel", "il"},
    "uk": {"uk", "gb", "united kingdom"},
    "eu": {"eu", "european union"},
    "us": {"us", "united states", "united_states"},
    "international": {"international", "international bodies"},
}


def _sample_collection(collection: str, limit: int) -> list[dict[str, Any]]:
    try:
        client = get_client()
        points, _ = client.scroll(
            collection_name=collection,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [dict(point.payload or {}) for point in points]
    except Exception:
        return []


def _payload_problem(collection: str, payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    text = str(payload.get("text") or "")
    lowered = text.lower()
    doc_type = str(payload.get("doc_type") or "")
    is_source_metadata = doc_type in _SOURCE_METADATA_TYPES
    if not is_source_metadata:
        for pattern in BAD_PATTERNS:
            if pattern in lowered:
                problems.append(f"bad_content:{pattern}")
    if is_source_metadata and not payload.get("not_legal_authority"):
        problems.append("metadata_source_not_marked_non_authority")
    if collection in CASE_LAW_COLLECTIONS and not is_source_metadata:
        expected = EXPECTED_CASE_JURISDICTION.get(collection)
        actual = str(payload.get("jurisdiction") or "").lower()
        allowed = _JURISDICTION_EQUIVALENTS.get(expected or "", {expected or ""})
        if expected and actual not in allowed:
            problems.append(f"case_jurisdiction_mismatch:{actual or 'missing'}")
        if doc_type not in {"case_law", "remote_source_content"}:
            problems.append(f"case_collection_doc_type:{payload.get('doc_type')}")
    if not is_source_metadata:
        for required in ("doc_hash", "canonical_doc_id", "legal_type", "importance_score"):
            if required not in payload:
                problems.append(f"missing_metadata:{required}")
    return problems


def evaluate(samples: int) -> dict[str, Any]:
    counts = {collection: collection_point_count(collection) for collection in ALL_COLLECTIONS}
    collection_results: dict[str, Any] = {}
    total_problems = 0
    for collection in ALL_COLLECTIONS:
        payloads = _sample_collection(collection, samples)
        findings = []
        for payload in payloads:
            problems = _payload_problem(collection, payload)
            if problems:
                total_problems += len(problems)
                findings.append({
                    "source_name": payload.get("source_name"),
                    "doc_type": payload.get("doc_type"),
                    "jurisdiction": payload.get("jurisdiction"),
                    "problems": problems,
                    "preview": re.sub(r"\s+", " ", str(payload.get("text") or ""))[:240],
                })
        collection_results[collection] = {
            "count": counts.get(collection, 0),
            "sampled": len(payloads),
            "findings": findings,
        }
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "samples_per_collection": samples,
        "counts": counts,
        "total_problem_count": total_problems,
        "status": "pass" if total_problems == 0 else "fail",
        "collections": collection_results,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Verify OmniLegal ingestion quality by sampling Qdrant payloads")
    parser.add_argument("--samples", type=int, default=20)
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when quality problems are found")
    args = parser.parse_args()
    result = evaluate(args.samples)
    out_dir = DATA_DIR / "evals" / "ingestion_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_ingestion_quality.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = out_dir / "latest_ingestion_quality.json"
    latest.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    result["artifact_path"] = str(path)
    result["latest_artifact_path"] = str(latest)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.strict and result["status"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
