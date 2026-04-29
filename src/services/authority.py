from __future__ import annotations

from typing import Any, Iterable, Mapping


PRIMARY_CITABLE_TIERS = {"primary_authority", "case_law"}
BACKGROUND_ONLY_TIERS = {"reference_dataset"}
NON_MERITS_TIERS = {"official_source_catalog", "project_reference"}

_PROJECT_REFERENCE_DOC_TYPES = {
    "project_reference",
    "source_map",
    "ingestion_manifest",
}

_SOURCE_CATALOG_DOC_TYPES = {"source_catalog"}
_PRIMARY_DOC_TYPES = {
    "treaty",
    "constitutional_text",
    "domestic_law",
    "statute",
    "legislation",
    "resolution",
}
_CASE_LAW_DOC_TYPES = {"case_law"}


def infer_authority_tier(metadata: Mapping[str, Any] | None) -> str:
    meta = dict(metadata or {})
    explicit = str(meta.get("authority_tier") or "").strip()
    if explicit:
        return explicit

    doc_type = str(meta.get("doc_type") or "").strip().lower()
    legal_type = str(meta.get("legal_type") or "").strip().lower()
    collection = str(meta.get("collection") or "").strip().upper()

    if doc_type in _SOURCE_CATALOG_DOC_TYPES:
        return "official_source_catalog"
    if meta.get("not_legal_authority") is True:
        return "project_reference"
    if doc_type in _PROJECT_REFERENCE_DOC_TYPES:
        return "project_reference"
    if doc_type in _CASE_LAW_DOC_TYPES or legal_type == "case_law":
        return "case_law"
    if doc_type in _PRIMARY_DOC_TYPES or legal_type in {"treaty", "statute"}:
        return "primary_authority"
    if collection.startswith("REFERENCE_DATASET_"):
        return "reference_dataset"
    if doc_type == "remote_source_content" and legal_type == "commentary":
        return "reference_dataset"
    if doc_type == "commentary" or legal_type == "commentary":
        return "reference_dataset"
    return "reference_dataset"


def is_merits_citable_tier(tier: str) -> bool:
    return tier in PRIMARY_CITABLE_TIERS


def is_background_only_tier(tier: str) -> bool:
    return tier in BACKGROUND_ONLY_TIERS


def is_non_merits_tier(tier: str) -> bool:
    return tier in NON_MERITS_TIERS


def authority_rank(tier: str) -> int:
    return {
        "primary_authority": 5,
        "case_law": 4,
        "official_source_catalog": 3,
        "reference_dataset": 2,
        "project_reference": 1,
    }.get(tier, 0)


def authority_weight(tier: str) -> float:
    return {
        "primary_authority": 1.35,
        "case_law": 1.25,
        "official_source_catalog": 0.85,
        "reference_dataset": 0.65,
        "project_reference": 0.05,
    }.get(tier, 1.0)


def annotate_authority_tier(metadata: Mapping[str, Any] | None) -> dict[str, Any]:
    enriched = dict(metadata or {})
    tier = infer_authority_tier(enriched)
    enriched["authority_tier"] = tier
    return enriched


def grounding_status_from_passages(
    passages: list[dict[str, Any]],
    *,
    cited_markers: Iterable[int] | None = None,
) -> str:
    if cited_markers is not None:
        selected: list[dict[str, Any]] = []
        for marker in cited_markers:
            idx = marker - 1
            if 0 <= idx < len(passages):
                selected.append(passages[idx])
    else:
        selected = list(passages)

    if not selected:
        return "no_authority"

    tiers = {infer_authority_tier((passage.get("metadata") or {})) for passage in selected}
    if tiers & PRIMARY_CITABLE_TIERS:
        return "primary_present"
    if "reference_dataset" in tiers:
        return "secondary_only"
    return "no_authority"


def authority_gaps_from_status(
    status: str,
    passages: list[dict[str, Any]],
) -> list[str]:
    tiers = {infer_authority_tier((passage.get("metadata") or {})) for passage in passages}
    gaps: list[str] = []
    if status != "primary_present":
        gaps.append("No retrieved primary authority or case law was sufficient to support the legal merits conclusion.")
    if status == "secondary_only":
        gaps.append("The answer relies on lower-tier background material and general principles, not controlling authority.")
    if status == "no_authority":
        gaps.append("No clearly relevant legal authority was retrieved for the merits question.")
    if "project_reference" in tiers:
        gaps.append("Project-reference materials were excluded from supporting legal-merits claims.")
    return gaps
