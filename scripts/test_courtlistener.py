"""Focused test: run only CourtListener adapter to verify it works."""
import sys
import types
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Stub src.services to avoid heavy __init__.py
if "src.services" not in sys.modules:
    stub = types.ModuleType("src.services")
    stub.__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "services")]
    stub.__package__ = "src.services"
    sys.modules["src.services"] = stub

import io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

print("Loading modules...", flush=True)
from src.services.remote_sources import (
    load_source_catalog, plan_for_record, BudgetManager, REMOTE_SOURCES_DIR,
)

print("Loading catalog...", flush=True)
records = load_source_catalog()
print(f"  {len(records)} source records found", flush=True)

# Find CourtListener record
cl_records = [r for r in records if "courtlistener" in r.name.lower()]
print(f"  CourtListener records: {len(cl_records)}", flush=True)

if cl_records:
    record = cl_records[0]
    plan = plan_for_record(record)
    print(f"  Record: {record.name}", flush=True)
    print(f"  Adapter: {plan.adapter}", flush=True)
    print(f"  Allowed: {plan.allowed_to_fetch}", flush=True)
    print(f"  Collection: {plan.collection}", flush=True)

    budget = BudgetManager(
        root=REMOTE_SOURCES_DIR,
        budget_bytes=1 * 1024 * 1024 * 1024,  # 1GB
        min_free_bytes=1 * 1024 * 1024 * 1024,
    )

    print("\nCalling CourtListener adapter...", flush=True)
    t = time.time()
    try:
        from src.services.adapters.courtlistener import fetch
        chunks, events = fetch(
            record, plan,
            root=REMOTE_SOURCES_DIR,
            budget=budget,
            max_items=2,
            max_bytes=5 * 1024 * 1024,
        )
        elapsed = time.time() - t
        print(f"  Done in {elapsed:.1f}s", flush=True)
        print(f"  Chunks: {len(chunks)}", flush=True)
        print(f"  Events: {len(events)}", flush=True)
        for evt in events:
            print(f"    {evt.get('status', '?')}: {evt.get('query', evt.get('source', ''))}", flush=True)
            if evt.get("reason"):
                print(f"      Reason: {evt['reason']}", flush=True)
        if chunks:
            print(f"\n  Sample chunk metadata:", flush=True)
            meta = chunks[0].get("metadata", {})
            for key in ["case_name", "court", "jurisdiction", "doc_type", "year"]:
                print(f"    {key}: {meta.get(key)}", flush=True)
            print(f"    Text preview: {chunks[0].get('text', '')[:200]}...", flush=True)
    except Exception as exc:
        elapsed = time.time() - t
        print(f"  FAILED in {elapsed:.1f}s", flush=True)
        traceback.print_exc()
else:
    print("  No CourtListener records found!", flush=True)

print("\nDone!", flush=True)
