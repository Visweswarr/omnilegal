"""Rebuild OmniLegal's global corpus collections with granular targets."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import (
    ALL_COLLECTIONS,
    CASELAWS_DIR,
    DATA_DIR,
    GRANULAR_COLLECTIONS,
    POLLUTED_COLLECTIONS_TO_REBUILD,
    PRESERVED_CORPUS_COLLECTIONS,
    COLLECTION_CASE_LAW,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
)
from src.rag.ingestion import ingest_case_law_jsonl
from src.rag.vector_store import create_collection, upsert_chunks
from src.rag.vector_store import get_client
from src.services.remote_sources import run_remote_ingestion


def _write_manifest(payload: dict[str, Any], *, name: str) -> Path:
    root = DATA_DIR / "global_rebuild"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{stamp}_{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = root / f"latest_{name}.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _group_by_metadata_collection(chunks: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in chunks:
        collection = str((chunk.get("metadata") or {}).get("collection") or COLLECTION_CASE_LAW)
        grouped.setdefault(collection, []).append(chunk)
    return grouped


def _hash_text(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8", errors="ignore")).hexdigest()


def _legal_type_for_payload(payload: dict[str, Any]) -> str:
    doc_type = str(payload.get("doc_type") or "").lower()
    collection = str(payload.get("collection") or "").upper()
    if doc_type == "treaty" or collection == COLLECTION_INTL_TREATIES:
        return "treaty"
    if doc_type in {"constitutional_text", "statute", "legislation"} or collection == COLLECTION_NATIONAL_IN:
        return "statute"
    if doc_type == "case_law":
        return "case_law"
    return "commentary"


def _importance_for_payload(payload: dict[str, Any]) -> tuple[float, str]:
    text = f"{payload.get('source_name', '')} {payload.get('citation', '')} {payload.get('text', '')}".lower()
    if any(name in text for name in ["un charter", "iccp", "icescr", "constitution of india"]):
        return 1.0, "major treaty/constitutional material"
    if str(payload.get("collection") or "").upper() == COLLECTION_SHAW_PRIVATE:
        return 0.6, "licensed doctrinal commentary"
    if str(payload.get("doc_type") or "").lower() == "treaty":
        return 0.8, "primary treaty material"
    return 0.5, "preserved corpus material"


def _enrich_preserved_collection(collection: str) -> dict[str, Any]:
    client = get_client()
    updated = 0
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            offset=offset,
            limit=128,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for point in points:
            payload = dict(point.payload or {})
            text = str(payload.get("text") or "")
            if not text.strip():
                continue
            source_name = str(payload.get("source_name") or payload.get("citation") or collection)
            year = payload.get("year") or payload.get("date") or "undated"
            article = payload.get("article_number") or payload.get("section") or ""
            doc_hash = payload.get("doc_hash") or _hash_text(text)
            canonical_seed = "|".join([collection, source_name, str(year), str(article), str(payload.get("citation") or "")])
            canonical_doc_id = payload.get("canonical_doc_id") or hashlib.sha256(canonical_seed.encode("utf-8", errors="ignore")).hexdigest()
            legal_type = payload.get("legal_type") or _legal_type_for_payload({**payload, "collection": collection})
            importance_score, importance_reason = _importance_for_payload({**payload, "collection": collection})
            update = {
                "doc_hash": doc_hash,
                "canonical_doc_id": canonical_doc_id,
                "source_fingerprint": payload.get("source_fingerprint") or hashlib.sha256(canonical_seed.lower().encode("utf-8", errors="ignore")).hexdigest(),
                "legal_type": legal_type,
                "source_version": payload.get("source_version") or str(year),
                "version_date": payload.get("version_date") or str(year),
                "language": payload.get("language") or "en",
                "translation_status": payload.get("translation_status") or "original_only",
                "importance_score": float(payload.get("importance_score", importance_score)),
                "importance_reason": payload.get("importance_reason") or importance_reason,
                "importance_signals": payload.get("importance_signals") or [importance_reason],
            }
            client.set_payload(collection_name=collection, payload=update, points=[point.id])
            updated += 1
        if offset is None:
            break
    return {"collection": collection, "updated_payloads": updated}


def main() -> None:
    parser = argparse.ArgumentParser(description="Purge polluted collections and rebuild the granular global legal corpus")
    parser.add_argument("--staged", action="store_true", help="Run sources in the configured priority order")
    parser.add_argument("--full", action="store_true", help="Use full local case JSONL and full-source remote streaming")
    parser.add_argument("--write-purge-manifest", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Report the destructive actions without applying them")
    parser.add_argument("--skip-remote", action="store_true", help="Only purge/rebuild local case-law collections")
    parser.add_argument("--catalog", default=str(CASELAWS_DIR))
    parser.add_argument("--budget-gb", type=float, default=50.0)
    parser.add_argument("--case-limit", type=int, default=None, help="Override local case JSONL limit; 0 means no limit")
    args = parser.parse_args()

    purge_targets = list(dict.fromkeys(POLLUTED_COLLECTIONS_TO_REBUILD + GRANULAR_COLLECTIONS))
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "preserved": PRESERVED_CORPUS_COLLECTIONS,
        "purge_targets": purge_targets,
        "all_collections": ALL_COLLECTIONS,
        "local_case_limit": 0 if args.full and args.case_limit is None else args.case_limit,
        "remote_requested": not args.skip_remote,
        "events": [],
    }

    if args.write_purge_manifest or args.dry_run:
        manifest["purge_manifest_path"] = str(_write_manifest(manifest, name="purge_manifest"))

    if args.dry_run:
        print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
        return

    for collection in ALL_COLLECTIONS:
        recreate = collection in purge_targets and collection not in PRESERVED_CORPUS_COLLECTIONS
        create_collection(collection, recreate=recreate)
        manifest["events"].append({"collection": collection, "recreated": recreate})

    manifest["preserved_enrichment"] = [
        _enrich_preserved_collection(collection)
        for collection in PRESERVED_CORPUS_COLLECTIONS
    ]

    case_limit = args.case_limit
    if args.full and case_limit is None:
        case_limit = 0
    case_chunks = ingest_case_law_jsonl(limit=case_limit, add_context=False)
    grouped = _group_by_metadata_collection(case_chunks)
    local_upserted: dict[str, int] = {}
    for collection, chunks in grouped.items():
        local_upserted[collection] = upsert_chunks(collection, chunks, batch_size=16)
    manifest["local_case_chunks"] = len(case_chunks)
    manifest["local_upserted_by_collection"] = local_upserted

    if not args.skip_remote:
        remote = run_remote_ingestion(
            catalog=args.catalog,
            budget_gb=args.budget_gb,
            mode="licensed",
            download=True,
            ingest=True,
            full_source=args.full,
            quality_gate="strict",
            update_mode="overwrite_same_source_version",
            dedupe="strict",
            importance_ranking=True,
        )
        manifest["remote_manifest"] = remote

    path = _write_manifest(manifest, name="global_rebuild")
    manifest["artifact_path"] = str(path)
    print(json.dumps(manifest, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
