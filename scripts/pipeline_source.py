#!/usr/bin/env python3
"""Per-source bulk-ingestion launcher (P0 corpus growth jobs).

Wraps ``run_remote_ingestion`` so an operator can run a single working
adapter end-to-end against the merged pipeline's Qdrant store.

Examples:
    python scripts/pipeline_source.py courtlistener --max-items 200 --download --ingest
    python scripts/pipeline_source.py govinfo --max-items 500 --download --ingest
    python scripts/pipeline_source.py eurlex --max-items 500 --download --ingest
    python scripts/pipeline_source.py uk-legislation --max-items 500 --download --ingest
    python scripts/pipeline_source.py indian-kanoon --max-items 500 --download --ingest
    python scripts/pipeline_source.py all --max-items 200 --download --ingest
"""
from __future__ import annotations

import argparse
import io
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import types as _types
if "src.services" not in sys.modules:
    _stub = _types.ModuleType("src.services")
    _stub.__path__ = [str(_PROJECT_ROOT / "src" / "services")]
    _stub.__package__ = "src.services"
    sys.modules["src.services"] = _stub

from src.config import SOURCE_ALIASES

P0_SOURCES = [
    "courtlistener",
    "govinfo",
    "eurlex",
    "uk-legislation",
    "indian-kanoon",
]


def _resolve(source: str) -> list[str]:
    cleaned = source.strip().lower()
    if cleaned in {"all", "p0"}:
        return [SOURCE_ALIASES[name] for name in P0_SOURCES]
    if cleaned in SOURCE_ALIASES:
        return [SOURCE_ALIASES[cleaned]]
    # Allow passing a raw adapter label too.
    return [cleaned]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Per-source bulk-ingestion launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Friendly source names: "
            + ", ".join(P0_SOURCES)
            + ", all"
        ),
    )
    parser.add_argument("source", help="Friendly source name (or 'all') or raw adapter label")
    parser.add_argument("--max-items", type=int, default=200, help="Max items per source (default: 200)")
    parser.add_argument("--budget-gb", type=float, default=50.0, help="Disk budget in GB")
    parser.add_argument("--mode", default="licensed", choices=["licensed", "metadata-only"])
    parser.add_argument("--download", action="store_true", help="Download remote content")
    parser.add_argument("--ingest", action="store_true", help="Upsert into Qdrant after download")
    parser.add_argument("--fresh", action="store_true", help="Ignore checkpoint, start fresh")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Delete checkpoint before running")
    args = parser.parse_args()

    adapter_labels = _resolve(args.source)
    print(f"Adapter target: {adapter_labels}")
    print(f"Max items per source: {args.max_items}, budget: {args.budget_gb} GB, mode: {args.mode}")
    print(f"Download: {args.download}, Ingest: {args.ingest}\n")

    start = time.time()
    from src.services.remote_sources import run_remote_ingestion

    result = run_remote_ingestion(
        catalog=None,
        download=args.download,
        ingest=args.ingest,
        max_items_per_source=args.max_items,
        budget_gb=args.budget_gb,
        mode=args.mode,
        resume=not args.fresh,
        reset_checkpoint=args.reset_checkpoint,
        adapter_filter=adapter_labels,
    )
    elapsed = time.time() - start

    print(f"\n=== Result (in {elapsed:.1f}s) ===")
    print(f"Sources processed:   {result.get('source_count', 0)}")
    print(f"Catalog chunks:      {result.get('catalog_chunks', 0)}")
    print(f"Remote chunks:       {result.get('remote_chunks', 0)}")
    print(f"Budget used:         {result.get('budget_used_bytes', 0) / 1024 / 1024:.1f} MB")
    upserted = result.get("upserted_by_collection", {})
    if upserted:
        print("\nUpserted to Qdrant:")
        for coll, count in sorted(upserted.items()):
            print(f"  {coll:30s} -> {count} points")

    events = result.get("events", [])
    errors = [e for e in events if isinstance(e, dict) and e.get("status") in {"error", "adapter_error", "http_error"}]
    if errors:
        print(f"\n{len(errors)} error(s):")
        for err in errors[:10]:
            print(f"  - {err.get('source_name', err.get('adapter', 'unknown'))}: {err.get('reason', err.get('status'))}")

    print(f"\nManifest: {result.get('manifest_path', 'N/A')}")


if __name__ == "__main__":
    main()
