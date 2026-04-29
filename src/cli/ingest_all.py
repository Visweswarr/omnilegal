"""
Ingestion CLI - builds Qdrant collections from local corpus files.

Usage:
    cd omnilegal
    python -m src.cli.ingest_all --profile local-production --recreate
    python -m src.cli.ingest_all --profile local-production --contextual-retrieval
    python -m src.cli.ingest_all --collections INTL_TREATIES SHAW_PRIVATE
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    ALL_COLLECTIONS,
    COLLECTION_CASE_LAW,
    COLLECTION_COMMENTARY,
    COLLECTION_COMMENTARY_GLOBAL,
    CASE_LAW_COLLECTIONS,
    COLLECTION_PROFILES,
    COLLECTION_SHAW_PRIVATE,
    QDRANT_URL,
)

CONTEXTUAL_COLLECTIONS = {COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL, COLLECTION_CASE_LAW, *CASE_LAW_COLLECTIONS}


def check_qdrant() -> bool:
    try:
        from qdrant_client import QdrantClient
        client = QdrantClient(url=QDRANT_URL, timeout=5)
        client.get_collections()
        print(f"[OK] Qdrant reachable at {QDRANT_URL}")
        return True
    except Exception as exc:
        try:
            with urllib.request.urlopen(f"{QDRANT_URL.rstrip('/')}/collections", timeout=5) as response:
                json.loads(response.read().decode("utf-8"))
            print(f"[OK] Qdrant reachable at {QDRANT_URL} (REST fallback)")
            return True
        except Exception:
            print(f"[FAIL] Cannot reach Qdrant at {QDRANT_URL}: {exc}")
            print("   Start it with: docker compose up -d")
            return False


def ingest_one(
    collection: str,
    *,
    add_context: bool = True,
    recreate: bool = False,
) -> None:
    from tqdm import tqdm
    from src.rag.ingestion import ingest_collection
    from src.rag.vector_store import create_collection, upsert_chunks

    print(f"\n{'='*60}")
    print(f"Collection: {collection}")
    print(f"{'='*60}")

    create_collection(collection, recreate=recreate)
    collection_context = bool(add_context and collection in CONTEXTUAL_COLLECTIONS)
    if add_context and not collection_context:
        print(f"Contextual retrieval skipped for self-contained/statutory collection {collection}.")
    chunks = ingest_collection(collection, add_context=collection_context)

    if not chunks:
        print(f"No chunks produced for {collection}.")
        return

    print(f"Upserting {len(chunks)} chunks...")
    batch_size = 16
    total = 0
    grouped: dict[str, list[dict]] = {}
    for chunk in chunks:
        target = str((chunk.get("metadata") or {}).get("collection") or collection)
        grouped.setdefault(target, []).append(chunk)
    for target_collection, target_chunks in grouped.items():
        for i in tqdm(range(0, len(target_chunks), batch_size), desc=f"Upserting {target_collection}"):
            batch = target_chunks[i : i + batch_size]
            n = upsert_chunks(target_collection, batch)
            total += n

    print(f"[OK] {collection}: {total} points stored across {len(grouped)} physical collection(s)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest legal corpus into Qdrant")
    parser.add_argument(
        "--profile",
        default="local-production",
        choices=sorted(COLLECTION_PROFILES),
        help="Collection profile to ingest when --collections is not supplied",
    )
    parser.add_argument(
        "--collections",
        nargs="*",
        default=None,
        help=f"Collections to ingest (default: all). Choices: {ALL_COLLECTIONS}",
    )
    parser.add_argument(
        "--contextual-retrieval",
        action="store_true",
        help="Apply Anthropic/Groq 50-100 token context prefixes to SHAW_PRIVATE, COMMENTARY, and CASE_LAW.",
    )
    parser.add_argument(
        "--no-context",
        action="store_true",
        help="Compatibility alias: disable contextual retrieval even if the flag is provided.",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Drop and recreate collections before ingesting",
    )
    args = parser.parse_args()

    if not check_qdrant():
        sys.exit(1)

    collections = args.collections or COLLECTION_PROFILES.get(args.profile, ALL_COLLECTIONS)
    add_context = bool(args.contextual_retrieval and not args.no_context)

    print(f"\nCollections to ingest: {collections}")
    print(f"Contextual retrieval: {'ON' if add_context else 'OFF'}")
    if args.recreate:
        print("[WARN] Will recreate (drop+rebuild) each collection")

    # Pre-warm the embedding model so any download happens once, upfront.
    print("\n[...] Loading embedding model (one-time download if needed)...")
    try:
        from src.rag.vector_store import get_embed_model
        get_embed_model()
        print("[OK] Embedding model ready\n")
    except Exception as exc:
        print(f"[FAIL] Embedding model is unavailable: {exc}")
        print("Install the full retrieval stack with: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
        sys.exit(1)

    for col in collections:
        ingest_one(col, add_context=add_context, recreate=args.recreate)

    print("\n[OK] Ingestion complete.")
    print("Run the app: run_chainlit.bat")


if __name__ == "__main__":
    main()
