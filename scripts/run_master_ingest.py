"""OmniLegal master ingestion orchestrator.

Tiered, budget-aware, resumable, polite. Single entry point that drives the
elite-density strategy laid out in the corpus plan.

Usage:
    python -m scripts.run_master_ingest --tier S 1 2 3
    python -m scripts.run_master_ingest --tier all
    python -m scripts.run_master_ingest --tier all --dry-run
    python -m scripts.run_master_ingest --tier 1 --max-items 20

What it does (per tier):
    1. Loads the catalog file(s) for that tier
    2. Builds plans, applies budget guards
    3. Runs adapters concurrently (politely)
    4. Builds the citation graph (Kuzu) from new chunks
    5. Reports a structured summary
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.env import load_environment

load_environment()

from src.config import OMNILEGAL_REMOTE_BUDGET_GB
from src.services.remote_sources import run_remote_ingestion


TIER_CATALOGS: dict[str, list[str]] = {
    "S": ["tier_s_doctrinal.json"],
    "1": ["tier_1_india.json", "national_in.json", "national_us.json", "national_uk.json", "national_eu.json", "national_russia.json", "national_israel.json", "international.json", "mix.json"],
    "2": ["tier_2_hf_datasets.json", "hugging_face.json"],
    "3": ["tier_s_doctrinal.json"],  # IGO already in tier-S
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Master tiered ingestion for OmniLegal")
    parser.add_argument("--tier", nargs="+", default=["S", "1"], help="Tiers: S, 1, 2, 3, all")
    parser.add_argument("--max-items", type=int, default=80, help="Max items per source (per tier)")
    parser.add_argument("--budget-gb", type=float, default=OMNILEGAL_REMOTE_BUDGET_GB)
    parser.add_argument("--mode", default="licensed", choices=["safe", "licensed", "metadata-only"])
    parser.add_argument("--dry-run", action="store_true", help="Plan only — do not download")
    parser.add_argument("--no-citation-graph", action="store_true")
    parser.add_argument("--lexical-only", action="store_true", help="Skip embedding (zero-vector upsert)")
    parser.add_argument("--reset-checkpoint", action="store_true")
    args = parser.parse_args()

    tiers = args.tier
    if "all" in tiers:
        tiers = ["S", "1", "2", "3"]

    catalogs: list[str] = []
    seen: set[str] = set()
    for t in tiers:
        for cat in TIER_CATALOGS.get(t, []):
            if cat not in seen:
                seen.add(cat)
                catalogs.append(cat)

    overall_start = time.time()
    overall: dict[str, dict] = {}

    for cat_name in catalogs:
        cat_path = Path(__file__).resolve().parents[1] / "caselaws" / cat_name
        if not cat_path.exists():
            print(f"[skip] catalog not found: {cat_path}")
            continue
        print(f"\n=== Ingesting from {cat_name} ===")
        start = time.time()
        try:
            result = run_remote_ingestion(
                catalog=str(cat_path),
                budget_gb=args.budget_gb,
                mode=args.mode,
                download=not args.dry_run,
                ingest=not args.dry_run,
                max_items_per_source=args.max_items,
                resume=True,
                reset_checkpoint=args.reset_checkpoint,
                quality_gate="standard",
                update_mode="overwrite_same_source_version",
                dedupe="off",
                importance_ranking=True,
                lexical_only=args.lexical_only,
            )
            elapsed = time.time() - start
            sources = len(result.get("events", []))
            chunks_total = sum(int(e.get("chunks") or 0) for e in result.get("events", []))
            upserted = result.get("upserted_by_collection", {})
            print(f"  duration: {elapsed:.1f}s   sources processed: {sources}   chunks produced: {chunks_total}")
            for col, n in upserted.items():
                print(f"    upserted into {col}: {n}")
            overall[cat_name] = {
                "elapsed_s": round(elapsed, 1),
                "sources": sources,
                "chunks": chunks_total,
                "upserted_by_collection": upserted,
            }
        except Exception as exc:
            elapsed = time.time() - start
            print(f"  ERROR after {elapsed:.1f}s: {type(exc).__name__}: {exc}")
            overall[cat_name] = {"error": f"{type(exc).__name__}: {exc}", "elapsed_s": round(elapsed, 1)}

    if not args.no_citation_graph and not args.dry_run and not args.lexical_only:
        try:
            print("\n=== Building citation graph (Kuzu) from Qdrant ===")
            from src.services.citation_graph import build_from_chunks, graph_stats
            from src.rag.vector_store import get_store
            store = get_store()
            chunks_for_graph: list[dict] = []
            for col in store.available_collections():
                try:
                    points, _ = store.client.scroll(
                        collection_name=col,
                        limit=10000,
                        with_payload=True,
                        with_vectors=False,
                    )
                except Exception:
                    continue
                for p in points:
                    payload = p.payload or {}
                    chunks_for_graph.append({
                        "text": payload.get("text", ""),
                        "metadata": payload.get("metadata", payload),
                    })
            if chunks_for_graph:
                stats_built = build_from_chunks(chunks_for_graph)
                print(f"  built from {len(chunks_for_graph)} chunks: {stats_built}")
            stats = graph_stats()
            print(f"  graph: {stats['documents']} documents, {stats['edges']} edges")
            overall["_citation_graph"] = stats
        except Exception as exc:
            print(f"  citation graph error: {type(exc).__name__}: {exc}")

    overall_elapsed = time.time() - overall_start
    summary = {
        "tiers": tiers,
        "catalogs": catalogs,
        "duration_s": round(overall_elapsed, 1),
        "results": overall,
    }
    summary_path = Path(__file__).resolve().parents[1] / "data" / "ingestion_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n=== DONE in {overall_elapsed:.1f}s — summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
