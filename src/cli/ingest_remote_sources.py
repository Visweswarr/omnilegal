"""Bounded remote source ingestion for OmniLegal."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import OMNILEGAL_REMOTE_BUDGET_GB, OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE
from src.services.remote_sources import run_remote_ingestion


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and/or ingest approved remote legal sources")
    parser.add_argument("--catalog", default=None, help="Catalog directory or JSON file. Default: omnilegal/caselaws")
    parser.add_argument("--budget-gb", type=float, default=OMNILEGAL_REMOTE_BUDGET_GB)
    parser.add_argument("--mode", default="licensed", choices=["safe", "licensed", "metadata-only"])
    parser.add_argument("--download", action="store_true", help="Fetch linked content for eligible sources")
    parser.add_argument("--ingest", action="store_true", help="Upsert source catalog rows and fetched chunks into Qdrant")
    parser.add_argument(
        "--max-items-per-source",
        type=int,
        default=OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE,
        help="Maximum HF/API rows per source. Use 0 to stream until budget or source exhaustion.",
    )
    parser.add_argument("--max-bytes-per-item", type=int, default=10 * 1024 * 1024)
    parser.add_argument("--no-resume", action="store_true", help="Ignore the remote ingestion checkpoint for this run")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Delete the existing remote ingestion checkpoint before running")
    parser.add_argument("--full-source", action="store_true", help="Set max-items-per-source to 0 and stream until budget/source exhaustion")
    parser.add_argument("--quality-gate", default="standard", choices=["off", "standard", "strict"])
    parser.add_argument("--target-collection-group", default="all", choices=["case_law", "statutes", "commentary", "all"])
    parser.add_argument("--update-mode", default="overwrite_same_source_version", choices=["overwrite_same_source_version", "append_new_version"])
    parser.add_argument("--dedupe", default="strict", choices=["off", "strict"])
    parser.add_argument("--importance-ranking", action="store_true", default=True)
    parser.add_argument("--no-importance-ranking", action="store_false", dest="importance_ranking")
    parser.add_argument("--lexical-only", action="store_true", help="Upsert zero-vector payloads for lexical retrieval without loading embedding models")
    args = parser.parse_args()

    result = run_remote_ingestion(
        catalog=args.catalog,
        budget_gb=args.budget_gb,
        mode=args.mode,
        download=args.download and args.mode != "metadata-only",
        ingest=args.ingest,
        max_items_per_source=args.max_items_per_source,
        max_bytes_per_item=args.max_bytes_per_item,
        resume=not args.no_resume,
        reset_checkpoint=args.reset_checkpoint,
        full_source=args.full_source,
        target_collection_group=args.target_collection_group,
        quality_gate=args.quality_gate,
        update_mode=args.update_mode,
        dedupe=args.dedupe,
        importance_ranking=args.importance_ranking,
        lexical_only=args.lexical_only,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
