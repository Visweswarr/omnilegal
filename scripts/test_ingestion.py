"""Quick test to diagnose where the ingestion pipeline hangs."""
import sys
import time
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Bypass the heavy src/services/__init__.py by importing directly
print("1. Importing remote_sources (direct)...", flush=True)
t = time.time()

# We need to prevent src.services.__init__ from running its eager imports.
# Pre-register the package module as already loaded with a lightweight stub.
import types
if "src.services" not in sys.modules:
    stub = types.ModuleType("src.services")
    stub.__path__ = [str(Path(__file__).resolve().parent.parent / "src" / "services")]
    stub.__package__ = "src.services"
    sys.modules["src.services"] = stub

remote_sources = importlib.import_module("src.services.remote_sources")
print(f"   Done in {time.time()-t:.1f}s", flush=True)

print("2. Running audit...", flush=True)
t = time.time()
result = remote_sources.source_audit_summary()
print(f"   Done in {time.time()-t:.1f}s", flush=True)
print(f"   Fetchable: {result['summary']['fetchable']}", flush=True)

print("3. Running download-only (no ingest, max_items=2)...", flush=True)
t = time.time()
manifest = remote_sources.run_remote_ingestion(
    download=True,
    ingest=False,
    max_items_per_source=2,
    budget_gb=5,
    resume=False,
)
elapsed = time.time() - t
print(f"   Done in {elapsed:.1f}s", flush=True)
print(f"   Remote chunks: {manifest.get('remote_chunks', 0)}", flush=True)
print(f"   Catalog chunks: {manifest.get('catalog_chunks', 0)}", flush=True)
print(f"   Budget used: {manifest.get('budget_used_bytes', 0) / 1024:.1f} KB", flush=True)

# Show events summary
events = manifest.get("events", [])
for evt in events:
    if isinstance(evt, dict):
        name = evt.get("source_name", "?")
        status = evt.get("status", "?")
        chunks = evt.get("chunks", "?")
        sub_events = evt.get("events", [])
        adapter_info = evt.get("adapter", "")
        if sub_events:
            for se in sub_events:
                print(f"   [{adapter_info}] {name}: {se.get('status', '?')}", flush=True)
        else:
            print(f"   {name}: {status} (chunks={chunks})", flush=True)

print(f"\n4. Manifest: {manifest.get('manifest_path', 'N/A')}", flush=True)
print("Done!", flush=True)
