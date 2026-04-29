"""Prepare optional translated indexes for multilingual corpora."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import COLLECTION_NATIONAL_IL, COLLECTION_NATIONAL_RU
from src.services.translation import prepare_translation


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare optional English translations for RU/HE corpora")
    parser.add_argument("--collections", nargs="+", default=[COLLECTION_NATIONAL_RU, COLLECTION_NATIONAL_IL])
    parser.add_argument("--provider", default="auto", choices=["auto", "deepl", "azure", "google"])
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()
    result = prepare_translation(
        collections=args.collections,
        provider=args.provider,
        limit=args.limit,
        ingest=not args.no_ingest,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
