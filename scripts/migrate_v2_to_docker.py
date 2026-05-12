"""Migrate pipeline_v2 embedded Qdrant data → Docker Qdrant (localhost:6333).

Reads all 3,855 points from the embedded omnilegal_v2 collection, groups them
by their target collection (CASE_LAW_US, STATUTES_US, SCHOLARLY_WORKS, etc.),
re-embeds with BGE-m3 (1024-dim) and upserts into the corresponding Docker
Qdrant collections so both backends have the same data.

Usage:
    python scripts/migrate_v2_to_docker.py [--batch-size 16] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# ── Force FlagEmbedding (BGE-m3, 1024-dim) before any imports touch config ──
os.environ["OMNILEGAL_EMBED_PROVIDER"] = "flagembedding"
os.environ["OMNILEGAL_EMBEDDING_DIM"] = "1024"

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qdrant_client import QdrantClient


EMBEDDED_PATH = Path(r"C:\app\data\qdrant_v2")
SOURCE_COLLECTION = "omnilegal_v2"
DOCKER_URL = "http://localhost:6333"
TARGET_DIM = 1024  # BGE-m3 dimension

# Collections that need to be created if they don't exist yet
KNOWN_COLLECTIONS = {
    "CASE_LAW_US", "CASE_LAW_EU", "CASE_LAW_UK", "CASE_LAW_IN",
    "CASE_LAW_RU", "CASE_LAW_IL", "CASE_LAW_GLOBAL",
    "STATUTES_US", "STATUTES_EU", "STATUTES_UK", "STATUTES_IN",
    "STATUTES_RU", "STATUTES_IL",
    "INTL_TREATIES", "COMMENTARY_GLOBAL",
    "SCHOLARLY_WORKS", "LEGAL_NLP_PAPERS",
    "SHAW_PRIVATE", "NATIONAL_IN", "NATIONAL_US", "NATIONAL_UK",
    "NATIONAL_EU", "NATIONAL_RU", "NATIONAL_IL",
}


def read_all_points(client: QdrantClient, collection: str) -> list[dict]:
    """Scroll through all points and return payload + text."""
    all_points = []
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection,
            limit=500,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for p in points:
            payload = dict(p.payload or {})
            all_points.append(payload)
        if offset is None:
            break
    return all_points


def route_point(payload: dict) -> str:
    """Determine which Docker collection this point belongs to."""
    collection = str(payload.get("collection") or "").upper()
    if collection in KNOWN_COLLECTIONS:
        return collection

    doc_type = str(payload.get("doc_type") or "").lower()
    jurisdiction = str(payload.get("jurisdiction") or "").upper()

    if doc_type == "commentary" or doc_type == "scholarly":
        return "SCHOLARLY_WORKS"
    if doc_type == "statute" or doc_type == "legislation":
        jmap = {"US": "STATUTES_US", "EU": "STATUTES_EU", "UK": "STATUTES_UK",
                "IN": "STATUTES_IN", "RU": "STATUTES_RU", "IL": "STATUTES_IL"}
        return jmap.get(jurisdiction, "STATUTES_US")
    if doc_type == "case_law":
        jmap = {"US": "CASE_LAW_US", "EU": "CASE_LAW_EU", "UK": "CASE_LAW_UK",
                "IN": "CASE_LAW_IN", "RU": "CASE_LAW_RU", "IL": "CASE_LAW_IL",
                "INTL": "CASE_LAW_GLOBAL"}
        return jmap.get(jurisdiction, "CASE_LAW_GLOBAL")

    return "COMMENTARY_GLOBAL"


def ensure_collection_at_dim(docker_client: QdrantClient, name: str, dim: int) -> None:
    """Ensure a collection exists with the correct vector dimension.

    If it exists at the wrong dimension (and is empty), recreate it.
    """
    from qdrant_client.models import Distance, SparseIndexParams, SparseVectorParams, VectorParams

    try:
        info = docker_client.get_collection(name)
        existing_dim = None
        vectors_config = info.config.params.vectors
        if isinstance(vectors_config, dict) and "dense" in vectors_config:
            existing_dim = vectors_config["dense"].size
        elif hasattr(vectors_config, "size"):
            existing_dim = vectors_config.size

        if existing_dim == dim:
            return  # Already correct

        # Wrong dimension — only recreate if empty
        count = info.points_count if info.points_count is not None else 0
        if count == 0:
            print(f"  [WARN] Collection {name} has dim={existing_dim}, need {dim}. Recreating (empty).")
            try:
                docker_client.delete_collection(name)
                time.sleep(0.5)  # Give Qdrant a moment
            except Exception as del_exc:
                print(f"    Delete failed: {del_exc}")
        else:
            print(f"  [WARN] Collection {name} has dim={existing_dim} with {count} points!")
            print(f"    Cannot recreate non-empty collection. Skipping dimension fix.")
            return
    except Exception:
        pass  # Collection doesn't exist yet

    docker_client.create_collection(
        collection_name=name,
        vectors_config={"dense": VectorParams(size=dim, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
    )
    print(f"  [OK] Created {name} at dim={dim}")


def main():
    parser = argparse.ArgumentParser(description="Migrate v2 embedded data to Docker Qdrant")
    parser.add_argument("--batch-size", type=int, default=16, help="Embedding batch size")
    parser.add_argument("--dry-run", action="store_true", help="Just show counts, don't ingest")
    parser.add_argument("--skip-collections", nargs="*", default=[], help="Collections to skip (already done)")
    args = parser.parse_args()

    print(f"[1/5] Opening embedded Qdrant at {EMBEDDED_PATH}")
    embedded = QdrantClient(path=str(EMBEDDED_PATH))
    info = embedded.get_collection(SOURCE_COLLECTION)
    print(f"       Found {info.points_count} points in '{SOURCE_COLLECTION}'")

    print(f"[2/5] Reading all points...")
    all_points = read_all_points(embedded, SOURCE_COLLECTION)
    embedded.close()
    print(f"       Read {len(all_points)} points")

    # Group by target collection
    grouped: dict[str, list[dict]] = defaultdict(list)
    for payload in all_points:
        target = route_point(payload)
        grouped[target].append(payload)

    print(f"\n[3/5] Routing breakdown:")
    for col in sorted(grouped.keys()):
        skip_tag = " [SKIP]" if col in args.skip_collections else ""
        print(f"       {col}: {len(grouped[col])} points{skip_tag}")

    # Remove skipped collections
    for col in args.skip_collections:
        grouped.pop(col, None)

    if args.dry_run:
        print("\n[DRY RUN] Skipping ingestion.")
        return

    print(f"\n[4/5] Connecting to Docker Qdrant at {DOCKER_URL}")
    docker_client = QdrantClient(url=DOCKER_URL, timeout=120)
    existing = {c.name for c in docker_client.get_collections().collections}
    print(f"       Docker has {len(existing)} existing collections")

    # Load embedding model (forced to FlagEmbedding / BGE-m3)
    from src.rag.vector_store import (
        get_embed_model,
        payload_with_ingestion_defaults,
        _stable_point_id,
    )
    from qdrant_client.models import PointStruct, SparseVector

    embed = get_embed_model()
    # Verify we got the right model
    test_out = embed.encode(["test"], return_dense=True, return_sparse=True, return_colbert_vecs=False)
    actual_dim = len(test_out["dense_vecs"][0])
    print(f"       Embedding model loaded (actual dim={actual_dim})")
    if actual_dim != TARGET_DIM:
        print(f"  ERROR: Expected dim={TARGET_DIM} but got {actual_dim}. Aborting!")
        print(f"         Make sure OMNILEGAL_EMBED_PROVIDER=flagembedding is set.")
        docker_client.close()
        return

    batch_size = args.batch_size

    # Ensure all target collections exist at 1024-dim
    for col in sorted(grouped.keys()):
        ensure_collection_at_dim(docker_client, col, TARGET_DIM)

    print(f"\n[5/5] Re-embedding and upserting into Docker Qdrant...")
    grand_total = 0
    start = time.time()

    for col in sorted(grouped.keys()):
        points_data = grouped[col]
        col_start = time.time()
        col_total = 0

        for i in range(0, len(points_data), batch_size):
            batch = points_data[i:i + batch_size]

            # Build chunks
            chunks = []
            for payload in batch:
                text = str(payload.get("text") or payload.get("document") or "")
                if not text.strip():
                    continue
                chunk = {
                    "text": text,
                    "raw_text": text,
                    "index_text": text,
                    "metadata": {
                        k: v for k, v in payload.items()
                        if k not in ("text", "raw_text", "index_text", "document")
                    },
                }
                chunks.append(chunk)

            if not chunks:
                continue

            # Embed with BGE-m3
            texts = [c.get("index_text") or c.get("text") or "" for c in chunks]
            outputs = embed.encode(
                texts, return_dense=True, return_sparse=True, return_colbert_vecs=False
            )
            dense_vecs = outputs["dense_vecs"]
            sparse_weights = outputs.get("lexical_weights", [{} for _ in texts])

            # Build Qdrant points
            qdrant_points = []
            for j, chunk in enumerate(chunks):
                s_indices = [int(k) for k in sparse_weights[j].keys()]
                s_values = [float(v) for v in sparse_weights[j].values()]
                enriched_payload = payload_with_ingestion_defaults(col, chunk)
                enriched_payload["migrated_from"] = "pipeline_v2"
                qdrant_points.append(
                    PointStruct(
                        id=_stable_point_id(col, chunk),
                        vector={
                            "dense": dense_vecs[j].tolist(),
                            "sparse": SparseVector(indices=s_indices, values=s_values),
                        },
                        payload=enriched_payload,
                    )
                )

            docker_client.upsert(collection_name=col, points=qdrant_points)
            col_total += len(qdrant_points)
            grand_total += len(qdrant_points)

            done = min(i + batch_size, len(points_data))
            elapsed = time.time() - start
            rate = grand_total / elapsed if elapsed > 0 else 0
            print(
                f"  [{col}] {done}/{len(points_data)} | "
                f"Total: {grand_total} | {rate:.1f} pts/sec",
                end="\r",
            )

        col_elapsed = time.time() - col_start
        print(f"  [{col}] Done: {col_total} points in {col_elapsed:.1f}s" + " " * 40)

    total_elapsed = time.time() - start
    docker_client.close()

    print(f"\n{'='*60}")
    print(f"Migration complete!")
    print(f"  Total points upserted: {grand_total}")
    print(f"  Time: {total_elapsed:.1f}s ({grand_total/total_elapsed:.1f} pts/sec)")
    print(f"  Both Docker and embedded stores now have the data.")


if __name__ == "__main__":
    main()
