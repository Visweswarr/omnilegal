"""Backfill production metadata fields on existing Qdrant payloads."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import ALL_COLLECTIONS, DATA_DIR
from src.rag.vector_store import get_client, payload_with_ingestion_defaults


REQUIRED_FIELDS = (
    "doc_hash",
    "canonical_doc_id",
    "source_fingerprint",
    "legal_type",
    "source_version",
    "version_date",
    "language",
    "translation_status",
    "importance_score",
    "importance_reason",
    "importance_signals",
)


def _missing_required(payload: dict[str, Any]) -> bool:
    return any(field not in payload for field in REQUIRED_FIELDS)


def repair_collection(collection: str, *, dry_run: bool = False, batch_size: int = 128) -> dict[str, Any]:
    client = get_client()
    scanned = 0
    updated = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            offset=offset,
            limit=batch_size,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break

        for point in points:
            payload = dict(point.payload or {})
            scanned += 1
            if not _missing_required(payload):
                continue
            chunk = {
                "text": payload.get("text", ""),
                "raw_text": payload.get("raw_text", payload.get("text", "")),
                "metadata": {k: v for k, v in payload.items() if k not in {"text", "raw_text"}},
            }
            repaired = payload_with_ingestion_defaults(collection, chunk)
            update = {field: repaired[field] for field in REQUIRED_FIELDS if field in repaired}
            if not dry_run:
                client.set_payload(collection_name=collection, payload=update, points=[point.id])
            updated += 1

        if offset is None:
            break
    return {"collection": collection, "scanned": scanned, "updated": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill missing production metadata in Qdrant payloads")
    parser.add_argument("--collections", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    selected = args.collections or ALL_COLLECTIONS
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "collections": [],
    }
    for collection in selected:
        result["collections"].append(repair_collection(collection, dry_run=args.dry_run))

    out_dir = DATA_DIR / "evals" / "ingestion_quality"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_metadata_repair.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    result["artifact_path"] = str(path)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
