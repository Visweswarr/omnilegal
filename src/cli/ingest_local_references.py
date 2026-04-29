"""Ingest local project reference PDFs into COMMENTARY as non-authority records."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.services.local_references import ingest_local_references


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest local project PDFs as reference/source-map metadata")
    parser.add_argument("--files", nargs="+", required=True, help="PDF files to ingest")
    parser.add_argument("--no-ocr", action="store_true", help="Disable optional OCR fallback")
    parser.add_argument("--no-ingest", action="store_true", help="Build the manifest without upserting Qdrant")
    args = parser.parse_args()
    result = ingest_local_references(
        args.files,
        enable_ocr=not args.no_ocr,
        ingest=not args.no_ingest,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
