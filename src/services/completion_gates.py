"""Completion gate reporting for OmniLegal production readiness."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import ALL_COLLECTIONS, COLLECTION_CASE_LAW, COLLECTION_CASE_LAW_GLOBAL, DATA_DIR, OMNILEGAL_DIR
from src.rag.vector_store import collection_point_count
from src.services.remote_sources import remote_status
from src.services.translation import latest_translation_manifest

THRESHOLDS = {
    "ragas_faithfulness": 0.85,
    "citation_existence": 0.95,
    "quote_match": 0.90,
    "unsupported_rate_max": 0.15,
}


def _latest_artifact(pattern: str) -> tuple[Path | None, dict[str, Any] | None]:
    root = OMNILEGAL_DIR / "data" / "evals" / "results"
    if not root.exists():
        return None, None
    files = sorted(root.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None, None
    try:
        return files[0], json.loads(files[0].read_text(encoding="utf-8"))
    except Exception:
        return files[0], None


def _metric(payload: dict[str, Any] | None, *names: str) -> float | None:
    if not payload:
        return None
    for name in names:
        value = payload.get(name)
        if isinstance(value, (int, float)):
            return float(value)
    metrics = payload.get("metrics")
    if isinstance(metrics, dict):
        for name in names:
            value = metrics.get(name)
            if isinstance(value, (int, float)):
                return float(value)
    return None


def _gate(name: str, passed: bool | None, detail: dict[str, Any]) -> dict[str, Any]:
    status = "pass" if passed is True else "fail" if passed is False else "not_ready"
    return {"name": name, "status": status, **detail}


def evaluate_completion_gates() -> dict[str, Any]:
    smoke_path, smoke = _latest_artifact("*_smoke.json")
    ragas_path, ragas = _latest_artifact("*_ragas.json")
    legalbench_path, legalbench = _latest_artifact("*legalbench*.json")
    remote = remote_status()
    translation = latest_translation_manifest()
    counts = {collection: collection_point_count(collection) for collection in ALL_COLLECTIONS}

    hallucination_rate = _metric(smoke, "hallucination_rate", "unsupported_rate")
    citation_existence = _metric(smoke, "citation_existence", "citation_existence_rate")
    quote_match = _metric(smoke, "quote_match", "quote_match_rate", "citation_existence_rate")
    faithfulness = _metric(ragas, "faithfulness", "ragas_faithfulness")

    gates = [
        _gate("remote_checkpoint", bool(remote.get("checkpoint_entries")), {
            "checkpoint_entries": remote.get("checkpoint_entries", 0),
            "checkpoint_path": remote.get("checkpoint_path"),
        }),
        _gate("required_collections_nonempty", (
            all(counts.get(c, 0) > 0 for c in ["INTL_TREATIES", "NATIONAL_IN", "SHAW_PRIVATE"])
            and ((counts.get(COLLECTION_CASE_LAW, 0) > 0) or (counts.get(COLLECTION_CASE_LAW_GLOBAL, 0) > 0))
        ), {
            "counts": counts,
        }),
        _gate("ragas_faithfulness", faithfulness is not None and faithfulness >= THRESHOLDS["ragas_faithfulness"], {
            "value": faithfulness,
            "threshold": THRESHOLDS["ragas_faithfulness"],
            "artifact": str(ragas_path) if ragas_path else None,
        }),
        _gate("citation_existence", citation_existence is not None and citation_existence >= THRESHOLDS["citation_existence"], {
            "value": citation_existence,
            "threshold": THRESHOLDS["citation_existence"],
            "artifact": str(smoke_path) if smoke_path else None,
        }),
        _gate("quote_match", quote_match is not None and quote_match >= THRESHOLDS["quote_match"], {
            "value": quote_match,
            "threshold": THRESHOLDS["quote_match"],
            "artifact": str(smoke_path) if smoke_path else None,
        }),
        _gate("unsupported_rate", hallucination_rate is not None and hallucination_rate < THRESHOLDS["unsupported_rate_max"], {
            "value": hallucination_rate,
            "threshold_max": THRESHOLDS["unsupported_rate_max"],
            "artifact": str(smoke_path) if smoke_path else None,
        }),
        _gate("legalbench_run", legalbench_path is not None, {
            "artifact": str(legalbench_path) if legalbench_path else None,
        }),
        _gate("translation_strategy_recorded", translation is not None, {
            "manifest": translation,
        }),
    ]
    overall = "pass" if all(g["status"] == "pass" for g in gates) else "not_ready"
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "overall": overall,
        "thresholds": THRESHOLDS,
        "gates": gates,
        "remote_status": remote,
    }
    out_dir = DATA_DIR / "evals" / "completion_gates"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{timestamp}_completion_gates.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = out_dir / "latest_completion_gates.json"
    latest.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    result["artifact_path"] = str(path)
    result["latest_artifact_path"] = str(latest)
    return result


def latest_completion_gates() -> dict[str, Any] | None:
    path = DATA_DIR / "evals" / "completion_gates" / "latest_completion_gates.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
