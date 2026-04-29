"""Knowledge-base readiness checks shared by CLIs and UI entry points."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import (
    CASE_LAW_COLLECTIONS,
    COLLECTION_CASE_LAW,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
    OMNILEGAL_QDRANT_EMBEDDED_PATH,
)
from src.rag.vector_store import configured_vector_backend, get_store

REBUILD_COMMAND_TEMPLATE = (
    ".\\.venv\\Scripts\\python.exe -m src.cli.rebuild_knowledge_base "
    "--backend {backend} --recreate --full-shaw --contextual "
    "--best-quality --case-limit 0"
)

_CORE_COLLECTIONS = [
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
]


@dataclass(frozen=True)
class KnowledgeBaseStatus:
    ready: bool
    backend: str
    embedded_path: str
    counts: dict[str, int]
    missing_required: list[str]
    failure_causes: list[str]
    shaw_coverage: dict[str, Any]
    rebuild_command: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "backend": self.backend,
            "embedded_path": self.embedded_path,
            "counts": self.counts,
            "missing_required": self.missing_required,
            "failure_causes": self.failure_causes,
            "shaw_coverage": self.shaw_coverage,
            "rebuild_command": self.rebuild_command,
        }


def required_core_collections() -> list[str]:
    return list(_CORE_COLLECTIONS)


def _missing_required_collections(counts: dict[str, int]) -> list[str]:
    missing = [
        collection
        for collection in _CORE_COLLECTIONS
        if int(counts.get(collection) or 0) <= 0
    ]
    case_count = int(counts.get(COLLECTION_CASE_LAW) or 0) + int(counts.get(COLLECTION_CASE_LAW_GLOBAL) or 0)
    case_count += sum(int(counts.get(collection) or 0) for collection in CASE_LAW_COLLECTIONS)
    if case_count <= 0:
        missing.append(f"{COLLECTION_CASE_LAW} or {COLLECTION_CASE_LAW_GLOBAL}")
    return missing


def _shaw_collection_coverage(store: Any, count: int) -> dict[str, Any]:
    if count <= 0:
        return {"points": 0, "page_start": None, "page_end": None, "pages_seen": 0, "has_page_metadata": False}
    try:
        # Sample only a few payloads — full scan is too expensive for a readiness check
        payloads = store.load_all_documents_metadata_only([COLLECTION_SHAW_PRIVATE])
        sample = payloads[:20] if len(payloads) > 20 else payloads
    except Exception as exc:
        return {
            "points": count,
            "page_start": None,
            "page_end": None,
            "pages_seen": 0,
            "has_page_metadata": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    pages: set[int] = set()
    starts: list[int] = []
    ends: list[int] = []
    with_hash = 0
    private = 0
    for payload in sample:
        if payload.get("private_public") == "private":
            private += 1
        if payload.get("content_hash") or payload.get("doc_hash"):
            with_hash += 1
        start = payload.get("page_start") or payload.get("page")
        end = payload.get("page_end") or start
        try:
            start_int = int(start)
            end_int = int(end)
        except (TypeError, ValueError):
            continue
        starts.append(start_int)
        ends.append(end_int)
        for page in range(start_int, end_int + 1):
            pages.add(page)
    return {
        "points": count,
        "page_start": min(starts) if starts else None,
        "page_end": max(ends) if ends else None,
        "pages_seen": len(pages),
        "has_page_metadata": bool(starts),
        "private_points": private,
        "hashed_points": with_hash,
    }


def knowledge_base_status() -> KnowledgeBaseStatus:
    backend = configured_vector_backend()
    embedded_path = str(OMNILEGAL_QDRANT_EMBEDDED_PATH)
    counts: dict[str, int] = {}
    failure_causes: list[str] = []
    shaw_coverage: dict[str, Any] = {}
    try:
        store = get_store()
        collections = store.available_collections()
        for collection in collections:
            counts[collection] = int(store.collection_point_count(collection) or 0)
        missing = _missing_required_collections(counts)
        shaw_coverage = _shaw_collection_coverage(store, counts.get(COLLECTION_SHAW_PRIVATE, 0))
        if missing:
            failure_causes.append("Required local collections are empty or missing: " + ", ".join(missing))
        # Page metadata is cosmetic (for PDF source citations).
        # Its absence should NOT block the entire app — retrieval works fine without it.
        if counts.get(COLLECTION_SHAW_PRIVATE, 0) > 0 and not shaw_coverage.get("has_page_metadata"):
            shaw_coverage["_page_metadata_note"] = (
                "SHAW_PRIVATE lacks page-aware metadata. "
                "This is non-blocking; retrieval works. Rebuild with --full-shaw for page citations."
            )
    except Exception as exc:
        missing = list(_CORE_COLLECTIONS) + [f"{COLLECTION_CASE_LAW} or {COLLECTION_CASE_LAW_GLOBAL}"]
        failure_causes.append(f"Vector backend unavailable: {type(exc).__name__}: {exc}")
        shaw_coverage = {"points": 0, "page_start": None, "page_end": None, "pages_seen": 0, "has_page_metadata": False}

    return KnowledgeBaseStatus(
        ready=not failure_causes and not missing,
        backend=backend,
        embedded_path=embedded_path,
        counts=counts,
        missing_required=missing,
        failure_causes=failure_causes,
        shaw_coverage=shaw_coverage,
        rebuild_command=REBUILD_COMMAND_TEMPLATE.format(backend=backend),
    )


def readiness_message(status: KnowledgeBaseStatus | dict[str, Any] | None = None) -> str:
    payload = status.as_dict() if isinstance(status, KnowledgeBaseStatus) else (status or knowledge_base_status().as_dict())
    reasons = payload.get("failure_causes") or payload.get("missing_required") or ["Knowledge base is not ready."]
    reason_lines = "\n".join(f"- {reason}" for reason in reasons)
    
    rebuild_cmd = payload.get('rebuild_command') or REBUILD_COMMAND_TEMPLATE.format(backend=configured_vector_backend())
    
    return (
        "## Knowledge base not ready\n\n"
        "OmniLegal is configured to fail closed instead of answering from empty fallback context.\n\n"
        f"{reason_lines}\n\n"
        "Run this rebuild command from the `omnilegal` directory:\n\n"
        f"```powershell\n{rebuild_cmd}\n```"
    )
