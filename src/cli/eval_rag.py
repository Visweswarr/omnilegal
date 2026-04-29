"""Stratified retrieval evaluation for expected legal source coverage."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import DATA_DIR
from src.rag.retriever import search_documents


def _load_suite(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _match_terms(expected: str) -> list[str]:
    stop = {"the", "case", "art", "article", "v", "vs", "and", "of"}
    return [
        token
        for token in re.findall(r"[a-z0-9]+", expected.lower())
        if token not in stop and (len(token) > 2 or token.isdigit())
    ]


def _hit_haystack(hit: dict[str, Any]) -> str:
    metadata = hit.get("metadata") or {}
    parts = [
        hit.get("text", ""),
        metadata.get("source_name", ""),
        metadata.get("citation", ""),
        metadata.get("collection", ""),
        metadata.get("article_number", ""),
        metadata.get("heading", ""),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _source_hit(expected: str, hits: list[dict[str, Any]]) -> bool:
    terms = _match_terms(expected)
    if not terms:
        return False
    for hit in hits:
        haystack = _hit_haystack(hit)
        if all(term in haystack for term in terms):
            return True
        if len(terms) >= 3 and sum(1 for term in terms if term in haystack) >= len(terms) - 1:
            return True
    return False


def _evaluate_row(row: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    query = str(row.get("query") or "")
    key_sources = [str(item) for item in row.get("key_sources") or []]
    hits = search_documents(query, k=top_k)
    found = [source for source in key_sources if _source_hit(source, hits)]
    missing = [source for source in key_sources if source not in found]
    return {
        "id": row.get("id"),
        "area": row.get("area"),
        "difficulty": row.get("difficulty"),
        "query": query,
        "top_k": top_k,
        "expected_key_sources": key_sources,
        "found_key_sources": found,
        "missing_key_sources": missing,
        "passed": not missing,
        "retrieved": [
            {
                "source_name": (hit.get("metadata") or {}).get("source_name"),
                "citation": (hit.get("metadata") or {}).get("citation"),
                "collection": (hit.get("metadata") or {}).get("collection"),
                "score": hit.get("score"),
                "preview": " ".join(str(hit.get("text") or "").split())[:260],
            }
            for hit in hits
        ],
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Evaluate top-k retrieval against expected key legal sources")
    parser.add_argument("--suite", type=Path, default=DATA_DIR / "evals" / "stratified_queries.jsonl")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="Evaluate first N rows; 0 means all")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero if any row misses an expected source")
    args = parser.parse_args()

    suite = _load_suite(args.suite)
    if args.limit > 0:
        suite = suite[: args.limit]

    results = [_evaluate_row(row, top_k=args.top_k) for row in suite]
    passed = sum(1 for row in results if row["passed"])
    total = len(results)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "suite": str(args.suite),
        "top_k": args.top_k,
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate": (passed / total) if total else 0.0,
        "results": results,
    }

    out_dir = DATA_DIR / "evals" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_rag_key_source_eval.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = out_dir / "latest_rag_key_source_eval.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(json.dumps({k: payload[k] for k in ["suite", "top_k", "total", "passed", "failed", "pass_rate"]}, indent=2))
    print(f"artifact: {path}")
    if args.strict and payload["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
