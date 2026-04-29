from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from src.schemas import ProvenanceRecord


DONOR_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "data" / "donor_registry.json"


class DonorRecord(BaseModel):
    donor_id: str
    label: str
    repo_path: str
    capabilities: list[str] = Field(default_factory=list)
    integration_mode: str = "adapter"
    usage_modes: list[str] = Field(default_factory=list)
    notes: str | None = None


def load_donor_registry() -> list[DonorRecord]:
    with DONOR_REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return [DonorRecord(**item) for item in payload.get("donors", [])]


def get_donors_for_capability(capability: str, usage_mode: str | None = None) -> list[DonorRecord]:
    donors = [record for record in load_donor_registry() if capability in record.capabilities]
    if usage_mode is None:
        return donors
    return [record for record in donors if usage_mode in record.usage_modes]


def build_provenance(
    capability: str,
    usage_mode: str = "reference",
    donor_ids: list[str] | None = None,
) -> list[ProvenanceRecord]:
    records = get_donors_for_capability(capability, usage_mode=usage_mode) or get_donors_for_capability(capability)
    if donor_ids is not None:
        allowed = set(donor_ids)
        records = [record for record in records if record.donor_id in allowed]
    return [
        ProvenanceRecord(
            donor_id=record.donor_id,
            donor_label=record.label,
            capability=capability,
            usage_mode=usage_mode,  # type: ignore[arg-type]
            notes=record.notes,
        )
        for record in records
    ]


def donor_registry_summary() -> dict[str, object]:
    donors = load_donor_registry()
    capabilities = sorted({capability for donor in donors for capability in donor.capabilities})
    return {
        "total_donors": len(donors),
        "capabilities": capabilities,
        "runtime_donors": len([donor for donor in donors if "runtime" in donor.usage_modes]),
        "evaluation_donors": len([donor for donor in donors if "evaluation" in donor.usage_modes]),
    }
