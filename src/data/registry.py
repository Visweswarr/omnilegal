from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "dataset_registry.json"


class DatasetRecord(BaseModel):
    dataset_id: str
    title: str
    source: str
    split: str
    license_note: str
    task_usage: list[str] = Field(default_factory=list)
    jurisdiction: str = "mixed"
    document_type: str = "mixed_legal_text"
    preprocess_recipe: str
    documents: list[str] = Field(default_factory=list)
    local_path: str | None = None
    donor_repo: str | None = None
    usage_modes: list[str] = Field(default_factory=list)
    benchmark_only: bool = False


def load_dataset_registry() -> list[DatasetRecord]:
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [DatasetRecord(**item) for item in payload.get("datasets", [])]


def get_datasets_for_task(task: str) -> list[DatasetRecord]:
    return [record for record in load_dataset_registry() if task in record.task_usage]


def get_datasets_for_usage_mode(mode: str) -> list[DatasetRecord]:
    return [record for record in load_dataset_registry() if mode in record.usage_modes]


def dataset_registry_summary() -> dict[str, Any]:
    records = load_dataset_registry()
    local_records = [record for record in records if record.documents or record.local_path]
    return {
        "total_datasets": len(records),
        "local_records": len(local_records),
        "runtime_datasets": len(get_datasets_for_usage_mode("runtime")),
        "training_datasets": len(get_datasets_for_usage_mode("training")),
        "evaluation_datasets": len(get_datasets_for_usage_mode("evaluation")),
        "task_coverage": sorted({task for record in records for task in record.task_usage}),
        "donor_repos": sorted({record.donor_repo for record in records if record.donor_repo}),
    }
