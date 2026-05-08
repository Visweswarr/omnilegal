"""OmniLegal Saved Reports & Public Share (Pillar 13).

File-backed report library. Stores Atlas / Forensics / Advocacy / Council /
Diff / Doctrine / Graph outputs as JSON, with a public read-only share
token for each.

We use a JSON file at ``./data/reports/reports.json`` instead of MongoDB so
the project has zero new infrastructure dependencies.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

log = logging.getLogger("omnilegal.reports")


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_REPORTS_DIR = _PROJECT_ROOT / "data" / "reports_store"
_REPORTS_FILE = _REPORTS_DIR / "reports.json"
_LOCK = threading.RLock()


_VALID_KINDS = {
    "atlas", "forensics", "advocacy", "live", "council",
    "research", "diff", "doctrine", "graph", "redteam", "reading",
}


def _ensure() -> None:
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not _REPORTS_FILE.exists():
        _REPORTS_FILE.write_text("[]", encoding="utf-8")


def _load() -> list[dict[str, Any]]:
    _ensure()
    try:
        data = json.loads(_REPORTS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(data: list[dict[str, Any]]) -> None:
    _ensure()
    tmp = _REPORTS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_REPORTS_FILE)


_DEFAULT_MAX_BYTES = 750_000  # ~0.75 MB per report


def _trim_strings(obj: Any, max_str_chars: int) -> Any:
    """Recursively trim long strings while preserving JSON structure."""
    if isinstance(obj, str):
        return obj if len(obj) <= max_str_chars else obj[:max_str_chars] + "…[truncated]"
    if isinstance(obj, list):
        return [_trim_strings(x, max_str_chars) for x in obj]
    if isinstance(obj, dict):
        return {k: _trim_strings(v, max_str_chars) for k, v in obj.items()}
    return obj


def _strip_payload(payload: Any, max_bytes: int = _DEFAULT_MAX_BYTES) -> Any:
    """Cap payload size while preserving structure.

    First tries the payload as-is. If too big, recursively shortens long
    string fields. Only as a last resort does it switch to a flat preview.
    """
    encoded = json.dumps(payload, ensure_ascii=False)
    if len(encoded) <= max_bytes:
        return payload
    for limit in (4000, 1500, 600):
        trimmed = _trim_strings(payload, limit)
        encoded = json.dumps(trimmed, ensure_ascii=False)
        if len(encoded) <= max_bytes:
            trimmed = trimmed if isinstance(trimmed, dict) else {"value": trimmed}
            if isinstance(trimmed, dict):
                trimmed["_truncated"] = True
            return trimmed
    # Last resort: flat preview
    return {"_truncated": True, "_preview": encoded[:max_bytes]}


def save_report(
    kind: str,
    title: str,
    payload: dict[str, Any],
    *,
    owner: str | None = None,
) -> dict[str, Any]:
    if kind not in _VALID_KINDS:
        raise ValueError(f"Invalid report kind: {kind}")
    record = {
        "id": uuid4().hex,
        "kind": kind,
        "title": (title or "Untitled").strip()[:240],
        "owner": owner,
        "created_at": int(time.time()),
        "share_token": secrets.token_urlsafe(16),
        "payload": _strip_payload(payload),
    }
    with _LOCK:
        data = _load()
        data.append(record)
        _save(data)
    log.info("saved report id=%s kind=%s", record["id"], kind)
    return {k: v for k, v in record.items() if k != "payload"} | {
        "preview_keys": list(payload.keys()) if isinstance(payload, dict) else [],
    }


def list_reports(kind: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    with _LOCK:
        data = _load()
    items = [d for d in data if not kind or d.get("kind") == kind]
    items.sort(key=lambda r: r.get("created_at", 0), reverse=True)
    return [
        {
            "id": r["id"], "kind": r["kind"], "title": r["title"],
            "created_at": r["created_at"], "share_token": r["share_token"],
        }
        for r in items[:limit]
    ]


def get_report(report_id: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
    for r in data:
        if r.get("id") == report_id:
            return r
    return None


def get_by_share_token(token: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _load()
    for r in data:
        if r.get("share_token") == token:
            return {k: v for k, v in r.items() if k != "owner"}
    return None


def delete_report(report_id: str) -> bool:
    with _LOCK:
        data = _load()
        new_data = [r for r in data if r.get("id") != report_id]
        if len(new_data) == len(data):
            return False
        _save(new_data)
    return True
