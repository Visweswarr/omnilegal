"""One-command OmniLegal knowledge-base rebuild."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))


def _normalise_backend(value: str) -> str:
    backend = (value or "embedded-qdrant").lower().replace("_", "-")
    return {
        "embedded": "embedded_qdrant",
        "embedded-qdrant": "embedded_qdrant",
        "local-qdrant": "embedded_qdrant",
        "server": "server_qdrant",
        "server-qdrant": "server_qdrant",
        "qdrant-server": "server_qdrant",
        "sqlite": "sqlite",
    }.get(backend, backend.replace("-", "_"))


def _configure_environment(args: argparse.Namespace) -> None:
    os.environ["OMNILEGAL_VECTOR_BACKEND"] = _normalise_backend(args.backend)
    os.environ.setdefault("OMNILEGAL_ALLOW_SQLITE_FALLBACK", "0")
    os.environ["OMNILEGAL_USE_DENSE_RETRIEVAL"] = "1"
    if args.full_shaw:
        os.environ["OMNILEGAL_SHAW_MAX_WORDS"] = ""
    if args.contextual:
        os.environ["OMNILEGAL_ENABLE_CONTEXTUAL_RETRIEVAL"] = "1"
    if args.best_quality:
        os.environ["OMNILEGAL_QUALITY_MODE"] = "best_quality"
        os.environ["OMNILEGAL_ENABLE_HEAVY_MODELS"] = "1"
        os.environ["OMNILEGAL_ENABLE_NLI_VERIFIER"] = "1"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Rebuild the OmniLegal local knowledge base")
    parser.add_argument("--backend", default="embedded-qdrant", help="embedded-qdrant, server-qdrant, or sqlite")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate configured collections")
    parser.add_argument("--full-shaw", action="store_true", help="Index the full Malcolm Shaw PDF instead of applying a word cap")
    parser.add_argument("--contextual", action="store_true", help="Store contextual retrieval summaries in index_text only")
    parser.add_argument("--best-quality", action="store_true", help="Enable dense retrieval, reranker, and NLI verifier mode")
    parser.add_argument("--case-limit", type=int, default=0, help="Number of local JSONL cases to stream; 0 means all")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--skip-core-pdfs", action="store_true")
    parser.add_argument("--skip-full-case-jsonl", action="store_true")
    parser.add_argument("--skip-source-catalog", action="store_true")
    parser.add_argument("--lexical-only", action="store_true")
    args = parser.parse_args()

    _configure_environment(args)

    from src.cli.build_legal_knowledge_base import build_and_ingest

    result = build_and_ingest(
        recreate=args.recreate,
        batch_size=args.batch_size,
        case_limit=args.case_limit,
        skip_core_pdfs=args.skip_core_pdfs,
        skip_full_case_jsonl=args.skip_full_case_jsonl,
        skip_source_catalog=args.skip_source_catalog,
        lexical_only=args.lexical_only,
        contextual=args.contextual,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
