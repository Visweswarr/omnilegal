from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.services.evaluation import save_evaluation_artifact
from src.services.retrieval_evaluation import evaluate_retrieval_baseline
from src.config import COLLECTION_PROFILES


def main():
    parser = argparse.ArgumentParser(description="Run OmniLegal all-corpus retrieval smoke evaluation.")
    parser.add_argument(
        "--profile",
        default="local-production",
        choices=sorted(COLLECTION_PROFILES),
        help="Collection profile to evaluate when --collection is not supplied",
    )
    parser.add_argument("--limit", type=int, default=10, help="Evaluation record limit")
    parser.add_argument(
        "--collection",
        action="append",
        default=None,
        help="Optional collection override. Repeat for multiple collections.",
    )
    parser.add_argument("--output", default=None, help="Optional output artifact path")
    args = parser.parse_args()

    collections = args.collection or COLLECTION_PROFILES.get(args.profile)
    artifact = evaluate_retrieval_baseline(limit=args.limit, collections=collections)
    output_path = save_evaluation_artifact(artifact, output_path=args.output)
    print(json.dumps(artifact.model_dump(), indent=2, ensure_ascii=False))
    print(f"Wrote retrieval evaluation artifact to {output_path}")


if __name__ == "__main__":
    main()
