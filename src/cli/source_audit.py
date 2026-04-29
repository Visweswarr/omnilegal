"""Audit OmniLegal remote source catalogs without downloading content."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.services.remote_sources import source_audit_summary, write_json_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit caselaws JSON source catalogs")
    parser.add_argument("--catalog", default=None, help="Catalog directory or JSON file. Default: omnilegal/caselaws")
    parser.add_argument("--mode", default="licensed", choices=["safe", "licensed", "metadata-only"])
    args = parser.parse_args()

    audit = source_audit_summary(args.catalog, mode=args.mode)
    path = write_json_artifact("source_audit", audit)
    payload = {
        "artifact_path": str(path),
        **audit["summary"],
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
