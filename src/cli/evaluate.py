from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.services.evaluation import evaluate_records, save_evaluation_artifact


def _load_records(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle if line.strip()]
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if isinstance(payload, dict) and "records" in payload:
        return payload["records"]
    return payload


def main():
    parser = argparse.ArgumentParser(description="OmniLegal evaluation CLI")
    parser.add_argument("--input", required=True, help="JSON or JSONL file with evaluation records")
    parser.add_argument("--task", required=True, help="Task name")
    parser.add_argument("--benchmark", default="custom", help="Benchmark or dataset name")
    parser.add_argument("--split", default="eval", help="Data split name")
    parser.add_argument("--output", default=None, help="Optional output artifact path")
    args = parser.parse_args()

    input_path = Path(args.input)
    records = _load_records(input_path)
    artifact = evaluate_records(records, task=args.task, benchmark=args.benchmark, split=args.split)
    artifact.source_file = str(input_path)
    output_path = save_evaluation_artifact(artifact, output_path=args.output)
    print(f"Wrote evaluation artifact to {output_path}")


if __name__ == "__main__":
    main()
