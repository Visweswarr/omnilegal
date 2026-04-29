from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.data.registry import get_datasets_for_task, load_dataset_registry


def main():
    parser = argparse.ArgumentParser(description="OmniLegal training CLI scaffold")
    parser.add_argument("--task", required=True, help="Task name, e.g. conflict_detection or brief_generation")
    parser.add_argument("--config", default=None, help="Optional path to a JSON config file")
    parser.add_argument("--dataset", action="append", default=None, help="Optional dataset_id override(s)")
    parser.add_argument("--output-dir", default="omnilegal/data/evaluation/training_runs", help="Directory for run manifests")
    parser.add_argument("--notes", default="", help="Optional run notes")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and datasets without training")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config_payload = {}
    if args.config:
        with Path(args.config).open("r", encoding="utf-8") as handle:
            config_payload = json.load(handle)

    registry_records = load_dataset_registry()
    selected = []
    if args.dataset:
        selected = [record.model_dump() for record in registry_records if record.dataset_id in set(args.dataset)]
    else:
        selected = [record.model_dump() for record in get_datasets_for_task(args.task)]

    run_manifest = {
        "task": args.task,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "config": config_payload,
        "selected_datasets": selected,
        "notes": args.notes,
        "status": "validated" if args.dry_run else "scaffold_created",
        "next_step": "Attach task-specific training loops and prepared datasets to this manifest.",
    }

    output_path = output_dir / f"{args.task}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(run_manifest, handle, indent=2)

    print(f"Wrote training manifest to {output_path}")


if __name__ == "__main__":
    main()
