"""Seed a few landmark public international-law case summaries into Qdrant."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.config import COLLECTION_CASE_LAW, OMNILEGAL_DIR

SEED_PATH = OMNILEGAL_DIR / "data" / "seeds" / "core_cases_seed.jsonl"


def _ensure_case_collection() -> None:
    from src.cli.ensure_collections import main as ensure_main

    ensure_main()


def main() -> None:
    if not SEED_PATH.exists():
        print(f"Seed file not found: {SEED_PATH}")
        raise SystemExit(1)

    _ensure_case_collection()
    chunks = []
    for index, line in enumerate(SEED_PATH.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        seed = json.loads(line)
        text = seed["text"]
        metadata = {
            "text": text,
            "source_name": seed["case_name"],
            "collection": COLLECTION_CASE_LAW,
            "jurisdiction": seed.get("jurisdiction", "international"),
            "doc_type": "case_law",
            "court": seed.get("court"),
            "year": seed.get("year"),
            "citation": seed.get("citation"),
            "article_number": None,
            "page": None,
            "parent_id": None,
            "footnote_ids": [],
            "license_note": "short locally curated public case summary; verify against official report before external use",
            "private_public": "public",
            "chunk_index": 0,
            "context_prefix": "",
        }
        chunks.append({"text": text, "metadata": metadata})

    from src.rag.vector_store import upsert_chunks

    inserted = upsert_chunks(COLLECTION_CASE_LAW, chunks, batch_size=8)
    print(json.dumps({
        "collection": COLLECTION_CASE_LAW,
        "seeded_points": inserted,
        "embedding_path": "BGE-M3 dense+sparse upsert",
        "seed_path": str(SEED_PATH),
    }, indent=2))


if __name__ == "__main__":
    main()
