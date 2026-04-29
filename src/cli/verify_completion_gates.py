"""Report production completion gates."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.services.completion_gates import evaluate_completion_gates


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify OmniLegal production completion gates")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any gate is not passing")
    args = parser.parse_args()
    result = evaluate_completion_gates()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if args.strict and result.get("overall") != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
