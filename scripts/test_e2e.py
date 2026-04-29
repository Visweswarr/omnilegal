"""Minimal e2e test: download 1 opinion from CourtListener, embed, upsert to Qdrant."""
import sys, types, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if "src.services" not in sys.modules:
    stub = types.ModuleType("src.services")
    stub.__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "services")]
    stub.__package__ = "src.services"
    sys.modules["src.services"] = stub

import io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("Step 1: Fetch 1 opinion from CourtListener...", flush=True)
t = time.time()
from src.services.remote_sources import (
    load_source_catalog, plan_for_record, BudgetManager, REMOTE_SOURCES_DIR,
)
from src.services.adapters.courtlistener import fetch

records = load_source_catalog()
cl = [r for r in records if "courtlistener" in r.name.lower()][0]
plan = plan_for_record(cl)
budget = BudgetManager(root=REMOTE_SOURCES_DIR, budget_bytes=1*1024*1024*1024, min_free_bytes=1*1024*1024*1024)

chunks, events = fetch(cl, plan, root=REMOTE_SOURCES_DIR, budget=budget, max_items=1)
print(f"   Got {len(chunks)} chunks in {time.time()-t:.1f}s", flush=True)

if chunks:
    # Take only first 5 chunks to keep embedding fast
    chunks = chunks[:5]
    print(f"Step 2: Embedding + upserting {len(chunks)} chunks to Qdrant...", flush=True)
    t = time.time()
    from src.rag.vector_store import upsert_chunks
    collection = chunks[0]["metadata"]["collection"]
    count = upsert_chunks(collection, chunks, batch_size=4)
    print(f"   Upserted {count} points to {collection} in {time.time()-t:.1f}s", flush=True)

    print("Step 3: Verifying...", flush=True)
    from qdrant_client import QdrantClient
    client = QdrantClient(url="http://localhost:6333")
    info = client.get_collection(collection)
    print(f"   Collection {collection}: {info.points_count} total points", flush=True)

print("\nDone!", flush=True)
