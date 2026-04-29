#!/usr/bin/env python3
"""
Seed the embedded Qdrant database with all curated JSONL corpora.

Usage (from the omnilegal/ directory):
    python scripts/seed_qdrant.py
    python scripts/seed_qdrant.py --dry-run      # count records, no upsert
    python scripts/seed_qdrant.py --collection CASE_LAW_GLOBAL  # one collection only
    python scripts/seed_qdrant.py --verify        # check source availability after seeding
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    CORPUS_DIR,
)

# Directory name → Qdrant collection name
_DIR_COLLECTION_MAP: dict[str, str] = {
    "intl_treaties": COLLECTION_INTL_TREATIES,
    "national_us": COLLECTION_NATIONAL_US,
    "national_uk": COLLECTION_NATIONAL_UK,
    "national_eu": COLLECTION_NATIONAL_EU,
    "national_in": COLLECTION_NATIONAL_IN,
    "national_ru": COLLECTION_NATIONAL_RU,
    "national_il": COLLECTION_NATIONAL_IL,
    "statutes_us": COLLECTION_STATUTES_US,
    "statutes_uk": COLLECTION_STATUTES_UK,
    "statutes_eu": COLLECTION_STATUTES_EU,
    "statutes_in": COLLECTION_STATUTES_IN,
    "statutes_ru": COLLECTION_STATUTES_RU,
    "statutes_il": COLLECTION_STATUTES_IL,
    "case_law_global": COLLECTION_CASE_LAW_GLOBAL,
    "case_law_us": COLLECTION_CASE_LAW_US,
    "case_law_uk": COLLECTION_CASE_LAW_UK,
    "case_law_eu": COLLECTION_CASE_LAW_EU,
    "case_law_in": COLLECTION_CASE_LAW_IN,
    "case_law_ru": COLLECTION_CASE_LAW_RU,
    "case_law_il": COLLECTION_CASE_LAW_IL,
    "commentary_global": COLLECTION_COMMENTARY_GLOBAL,
    "shaw_private": COLLECTION_SHAW_PRIVATE,
}

# Curated-authority doc_type + jurisdiction → collection
_DOCTYPE_JURISDICTION_MAP: dict[tuple[str, str], str] = {
    ("treaty", "international"): COLLECTION_INTL_TREATIES,
    ("case_law", "international"): COLLECTION_CASE_LAW_GLOBAL,
    ("case_law", "us"): COLLECTION_CASE_LAW_US,
    ("case_law", "india"): COLLECTION_CASE_LAW_IN,
    ("case_law", "uk"): COLLECTION_CASE_LAW_UK,
    ("case_law", "eu"): COLLECTION_CASE_LAW_EU,
    ("case_law", "russia"): COLLECTION_CASE_LAW_RU,
    ("case_law", "israel"): COLLECTION_CASE_LAW_IL,
    ("statute", "india"): COLLECTION_STATUTES_IN,
    ("statute", "us"): COLLECTION_STATUTES_US,
    ("statute", "uk"): COLLECTION_STATUTES_UK,
    ("statute", "eu"): COLLECTION_STATUTES_EU,
    ("statute", "russia"): COLLECTION_STATUTES_RU,
    ("statute", "israel"): COLLECTION_STATUTES_IL,
    ("official_guidance", "india"): COLLECTION_NATIONAL_IN,
    ("official_guidance", "russia"): COLLECTION_NATIONAL_RU,
    ("official_guidance", "us"): COLLECTION_NATIONAL_US,
    ("official_guidance", "uk"): COLLECTION_NATIONAL_UK,
    ("official_guidance", "eu"): COLLECTION_NATIONAL_EU,
    ("official_guidance", "israel"): COLLECTION_NATIONAL_IL,
    ("commentary", "international"): COLLECTION_COMMENTARY_GLOBAL,
    ("commentary", "global"): COLLECTION_COMMENTARY_GLOBAL,
    ("commentary", ""): COLLECTION_COMMENTARY,
}


def _record_to_chunk(record: dict, collection: str, chunk_index: int = 0) -> dict:
    meta = record.get("metadata", {})
    text = record.get("text", "")
    source_name = meta.get("source_name") or record.get("title") or record.get("source_name", "Unknown")
    citation = meta.get("citation") or record.get("citation") or source_name
    jurisdiction = meta.get("jurisdiction") or record.get("jurisdiction", "international")
    doc_type = meta.get("doc_type") or record.get("doc_type", "case_law")
    year = meta.get("year") or record.get("year")
    article_number = meta.get("article_number") or record.get("article_number")

    metadata: dict = {
        "source_name": source_name,
        "collection": collection,
        "jurisdiction": jurisdiction,
        "doc_type": doc_type,
        "year": year,
        "article_number": article_number,
        "citation": citation,
        "chunk_index": chunk_index,
        "parent_id": None,
        "footnote_ids": [],
        "context_prefix": "",
        "license_note": "public/legal source; verify upstream license before redistribution",
        "private_public": "public",
        "tags": meta.get("tags") or record.get("tags") or [],
        "source_url": record.get("source_url", ""),
        "importance_score": record.get("importance_score", 0.5),
    }

    # Enrich index text with citation metadata
    metadata_lines = [f"Source: {source_name}", f"Citation: {citation}"]
    if jurisdiction:
        metadata_lines.append(f"Jurisdiction: {jurisdiction}")
    if year:
        metadata_lines.append(f"Year: {year}")
    index_parts = []
    if metadata_lines:
        index_parts.append("[LOCAL METADATA]\n" + "\n".join(metadata_lines))
    index_parts.append(f"[CHUNK TEXT]\n{text}")
    index_text = "\n\n".join(index_parts)

    return {
        "text": text,
        "raw_text": text,
        "index_text": index_text,
        "metadata": metadata,
    }


def _resolve_curated_collection(record: dict) -> str:
    """Map a curated-authority record to its target collection."""
    meta = record.get("metadata", {})
    doc_type = (meta.get("doc_type") or record.get("doc_type", "")).lower()
    jurisdiction = (meta.get("jurisdiction") or record.get("jurisdiction", "")).lower()
    key = (doc_type, jurisdiction)
    if key in _DOCTYPE_JURISDICTION_MAP:
        return _DOCTYPE_JURISDICTION_MAP[key]
    # Fallback: try doc_type only
    for (dt, _jur), coll in _DOCTYPE_JURISDICTION_MAP.items():
        if dt == doc_type:
            return coll
    return COLLECTION_COMMENTARY_GLOBAL


def load_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  [WARN] {path.name}:{i}: {e}")
    return records


def collect_chunks(only_collection: str | None = None) -> dict[str, list[dict]]:
    """Return {collection_name: [chunk, ...]} for all corpus JSONL files."""
    batches: dict[str, list[dict]] = {}

    # 1. Subdirectory-mapped collections
    for subdir in sorted(CORPUS_DIR.iterdir()):
        if not subdir.is_dir():
            continue
        dir_name = subdir.name.lower()
        collection = _DIR_COLLECTION_MAP.get(dir_name)
        if collection is None:
            continue  # skip unmapped directories (e.g. curated_authorities)
        if only_collection and collection != only_collection:
            continue
        for jsonl_file in sorted(subdir.glob("*.jsonl")):
            records = load_jsonl(jsonl_file)
            chunks = [_record_to_chunk(r, collection, i) for i, r in enumerate(records)]
            batches.setdefault(collection, []).extend(chunks)
            print(f"  {jsonl_file.relative_to(_PROJECT_ROOT)}: {len(records)} records → {collection}")

    # 2. seed_cases.jsonl
    seed_path = _PROJECT_ROOT / "configs" / "seed_cases.jsonl"
    if seed_path.exists():
        records = load_jsonl(seed_path)
        collection = COLLECTION_CASE_LAW_GLOBAL
        if not only_collection or only_collection == collection:
            chunks = [_record_to_chunk(r, collection, i) for i, r in enumerate(records)]
            batches.setdefault(collection, []).extend(chunks)
            print(f"  configs/seed_cases.jsonl: {len(records)} records → {collection}")

    return batches


def _run_verify() -> None:
    """Run source availability checks for all known topics."""
    print("\nRunning source availability verification...")
    from src.pipeline.source_registry import IndexedSourcesRegistry, _get_registry

    registry_map = _get_registry()
    idx_registry = IndexedSourcesRegistry()
    all_topics = [t for t in registry_map if t != "default"]

    all_ok = True
    for topic in sorted(all_topics):
        result = idx_registry.check_availability([topic])
        status = "✓" if result.ok else "✗"
        print(f"  {status} {topic}")
        if result.missing:
            all_ok = False
            for m in result.missing:
                print(f"      {m}")
        for p in result.present:
            print(f"      ✓ {p}")

    if all_ok:
        print("\nAll required sources are indexed.")
    else:
        print("\nSome required sources are missing. Ingest the needed documents and re-seed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed embedded Qdrant with curated corpora")
    parser.add_argument("--dry-run", action="store_true", help="Count records only, no upsert")
    parser.add_argument("--collection", default=None, help="Limit to one collection name")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate collections before upserting")
    parser.add_argument("--verify", action="store_true", help="Check source availability after seeding")
    args = parser.parse_args()

    print("OmniLegal Qdrant Seed Script")
    print("=" * 60)
    print(f"Corpus dir: {CORPUS_DIR}")
    print()

    print("Scanning corpus files...")
    batches = collect_chunks(only_collection=args.collection)

    total_records = sum(len(v) for v in batches.values())
    print(f"\nTotal chunks to upsert: {total_records}")
    for coll, chunks in sorted(batches.items()):
        print(f"  {coll:30s}: {len(chunks)}")

    if args.dry_run:
        print("\n[dry-run] No upsert performed.")
        if args.verify:
            _run_verify()
        return

    if total_records == 0:
        print("\nNothing to ingest. Check that JSONL files exist under data/corpus/")
        return

    print("\nLoading vector store (this triggers BGE-M3 model download on first run)...")
    from src.rag.vector_store import get_store
    store = get_store()
    print(f"Vector store: {type(store).__name__}")

    # Ensure collections exist
    existing = set(store.available_collections())
    for collection in batches:
        if collection not in existing or args.recreate:
            print(f"  Creating collection: {collection}")
            store.create_collection(collection, recreate=args.recreate)

    print("\nUpserting chunks...")
    total_upserted = 0
    for collection, chunks in sorted(batches.items()):
        print(f"  {collection}: upserting {len(chunks)} chunks...", end="", flush=True)
        n = store.upsert_chunks(collection, chunks)
        print(f" done ({n} points)")
        total_upserted += n

    print(f"\nDone. {total_upserted} total points upserted into Qdrant.")

    if args.verify:
        from src.pipeline.source_registry import reload_registry
        reload_registry()
        _run_verify()

    print("You can now run: chainlit run chainlit_app.py")


if __name__ == "__main__":
    main()
