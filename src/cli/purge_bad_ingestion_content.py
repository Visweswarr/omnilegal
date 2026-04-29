"""Remove already-ingested web boilerplate chunks from Qdrant.

The remote ingestion path rejects these chunks before upsert, but older runs may
have stored them already. This command applies the same style of quality gate to
existing payloads and writes an audit artifact for the purge.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qdrant_client import models

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import ALL_COLLECTIONS, DATA_DIR
from src.rag.vector_store import get_client

BAD_CONTENT_PATTERNS = [
    "use another email",
    "api documentation",
    "github.com",
    "sign in",
    "login",
    "enable javascript",
    "cookie policy",
    "devsecops",
    "skip to main content",
    "swagger",
    "openapi",
    "developer guide",
]

SOURCE_METADATA_TYPES = {"source_catalog", "source_map", "project_reference", "ingestion_manifest"}


def _bad_hits(payload: dict[str, Any]) -> list[str]:
    if str(payload.get("doc_type") or "") in SOURCE_METADATA_TYPES:
        return []
    if payload.get("not_legal_authority"):
        return []
    text = str(payload.get("text") or "")
    lowered = text.lower()
    return [pattern for pattern in BAD_CONTENT_PATTERNS if pattern in lowered]


def _scan_collection(client: Any, collection: str) -> list[dict[str, Any]]:
    offset = None
    findings: list[dict[str, Any]] = []
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=512,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in points:
            payload = dict(point.payload or {})
            hits = _bad_hits(payload)
            if not hits:
                continue
            preview = re.sub(r"\s+", " ", str(payload.get("text") or ""))[:240]
            findings.append(
                {
                    "id": point.id,
                    "source_name": payload.get("source_name"),
                    "doc_type": payload.get("doc_type"),
                    "jurisdiction": payload.get("jurisdiction"),
                    "hits": hits,
                    "preview": preview,
                }
            )
        if offset is None:
            break
    return findings


def purge_bad_content(*, apply: bool) -> dict[str, Any]:
    client = get_client()
    collections: list[dict[str, Any]] = []
    total = 0

    for collection in ALL_COLLECTIONS:
        findings = _scan_collection(client, collection)
        deleted = 0
        if apply and findings:
            ids = [finding["id"] for finding in findings]
            client.delete(
                collection_name=collection,
                points_selector=models.PointIdsList(points=ids),
                wait=True,
            )
            deleted = len(ids)
        total += len(findings)
        collections.append(
            {
                "collection": collection,
                "matched": len(findings),
                "deleted": deleted,
                "findings": findings,
            }
        )

    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied": apply,
        "total_matched": total,
        "total_deleted": sum(int(item["deleted"]) for item in collections),
        "collections": collections,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Purge non-legal web boilerplate chunks from Qdrant")
    parser.add_argument("--apply", action="store_true", help="Delete matched points. Without this flag, only report.")
    args = parser.parse_args()

    result = purge_bad_content(apply=args.apply)
    out_dir = DATA_DIR / "evals" / "ingestion_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "bad_content_purge" if args.apply else "bad_content_scan"
    path = out_dir / f"{stamp}_{suffix}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = out_dir / f"latest_{suffix}.json"
    latest.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    result["artifact_path"] = str(path)
    result["latest_artifact_path"] = str(latest)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
