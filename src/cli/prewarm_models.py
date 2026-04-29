"""Prewarm Phase 4 Hugging Face model caches."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment
from src.services.model_cache import prewarm_phase4_models, print_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Prewarm OmniLegal Hugging Face model caches.")
    parser.add_argument("--phase4", action="store_true", help="Download/cache Phase 4 reranker, NLI, classifier, and GLiNER assets.")
    parser.add_argument("--no-gliner", action="store_true", help="Skip GLiNER model snapshot download.")
    args = parser.parse_args()

    load_environment()
    if not args.phase4:
        parser.error("Use --phase4 to confirm the Phase 4 model prewarm.")

    result = prewarm_phase4_models(include_gliner=not args.no_gliner)
    print_json(result)
    failed = [item for item in result.get("downloads", []) if item.get("status") == "failed"]
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
