"""Remote-source ingestion for pipeline_v2 — bulk corpus growth.

Wires the working CourtListener / GovInfo / EUR-Lex / legislation.gov.uk /
Indian Kanoon adapters in `src/services/adapters/` directly into the embedded
v2 Qdrant store, so the corpus can grow from ~133 seed passages to 100k+.

Run examples:
    python -m pipeline_v2.ingest_remote --source courtlistener --max-items 50
    python -m pipeline_v2.ingest_remote --all --max-items 25
    python -m pipeline_v2.ingest_remote --source eurlex --max-items 25 --reset

Env vars required for paid sources:
    COURTLISTENER_TOKEN    courtlistener
    GOVINFO_API_KEY        govinfo
    INDIAN_KANOON_API_TOKEN indian_kanoon
EUR-Lex (CELLAR SPARQL) and legislation.gov.uk are open / no-auth.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Callable

# Ensure project root is on sys.path so `src.*` and `pipeline_v2.*` resolve
_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.services.remote_sources import BudgetManager, SourceRecord, SourcePlan  # noqa: E402

from pipeline_v2.settings import (  # noqa: E402
    CORPUS_DIR,
)
from pipeline_v2.vector_store import (  # noqa: E402
    clear_collection,
    collection_count,
    ensure_collection,
    upsert_documents,
)

log = logging.getLogger("pipeline_v2.ingest_remote")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


# ──────────────────────────────────────────────────────────────────────────
# Source registry — minimal SourceRecord + SourcePlan per adapter target.
# Each entry produces real legal text via the registered adapter.
# ──────────────────────────────────────────────────────────────────────────
_SOURCE_REGISTRY: dict[str, dict[str, Any]] = {
    "courtlistener": {
        "name": "CourtListener (Free Law Project)",
        "adapter": "courtlistener_api",
        "jurisdiction": "United States",
        "v2_jurisdiction": "US",
        "default_doc_type": "case_law",
        "collection": "CASE_LAW_US",
        "url": "https://www.courtlistener.com",
        "license_note": "Public domain (US government work)",
        "source_type": "aggregator (non-profit)",
        "coverage": "~200 federal + state courts; SCOTUS 1754–present",
        "access": "REST API v4",
        "source_format": "JSON, plain text",
        "catalog_file": "national_us.json",
    },
    "govinfo": {
        "name": "GovInfo API (US Federal)",
        "adapter": "govinfo_api",
        "jurisdiction": "United States",
        "v2_jurisdiction": "US",
        "default_doc_type": "statute",
        "collection": "STATUTES_US",
        "url": "https://api.govinfo.gov",
        "license_note": "Public domain (US government work)",
        "source_type": "official",
        "coverage": "USCOURTS, PLAW, USCODE, BILLS",
        "access": "REST API (api_key)",
        "source_format": "PDF, plain text, XML",
        "catalog_file": "national_us.json",
    },
    "eurlex": {
        "name": "EUR-Lex / CELLAR (EU Publications Office)",
        "adapter": "eurlex_cellar",
        "jurisdiction": "European Union",
        "v2_jurisdiction": "EU",
        "default_doc_type": "statute",
        "collection": "STATUTES_EU",
        "url": "https://publications.europa.eu",
        "license_note": "Open (re-use authorised under Decision 2011/833/EU)",
        "source_type": "official",
        "coverage": "EU regulations, directives, CJEU case law",
        "access": "SPARQL endpoint (no auth)",
        "source_format": "RDF, HTML, PDF",
        "catalog_file": "national_eu.json",
    },
    "uk_legislation": {
        "name": "legislation.gov.uk",
        "adapter": "uk_legislation_api",
        "jurisdiction": "United Kingdom",
        "v2_jurisdiction": "UK",
        "default_doc_type": "statute",
        "collection": "STATUTES_UK",
        "url": "https://www.legislation.gov.uk",
        "license_note": "Open Government Licence v3.0",
        "source_type": "official",
        "coverage": "UK Public General Acts and statutory instruments",
        "access": "REST/Atom (no auth)",
        "source_format": "XML, HTML, JSON",
        "catalog_file": "national_uk.json",
    },
    "indian_kanoon": {
        "name": "Indian Kanoon API",
        "adapter": "indian_kanoon_api",
        "jurisdiction": "India",
        "v2_jurisdiction": "IN",
        "default_doc_type": "case_law",
        "collection": "CASE_LAW_IN",
        "url": "https://api.indiankanoon.org",
        "license_note": "Indian Kanoon ToS (per-document)",
        "source_type": "aggregator",
        "coverage": "Supreme Court, High Courts, tribunals, central acts",
        "access": "REST API (token)",
        "source_format": "HTML, JSON",
        "catalog_file": "national_in.json",
    },
}

# Public alias so callers can list available targets without importing the dict
AVAILABLE_SOURCES = sorted(_SOURCE_REGISTRY.keys())


def _build_record(source_key: str) -> SourceRecord:
    cfg = _SOURCE_REGISTRY[source_key]
    return SourceRecord(
        source_id=f"v2::{source_key}",
        catalog_file=cfg["catalog_file"],
        group_index=0,
        source_index=0,
        jurisdiction=cfg["jurisdiction"],
        name=cfg["name"],
        url=cfg["url"],
        source_type=cfg["source_type"],
        coverage=cfg["coverage"],
        access=cfg["access"],
        source_format=cfg["source_format"],
        license_note=cfg["license_note"],
        recommended_for=[cfg["collection"]],
        raw={},
    )


def _build_plan(source_key: str) -> SourcePlan:
    cfg = _SOURCE_REGISTRY[source_key]
    return SourcePlan(
        source_id=f"v2::{source_key}",
        collection=cfg["collection"],
        tier=1,
        adapter=cfg["adapter"],
        action="fetch",
        metadata_only=False,
        allowed_to_fetch=True,
        blocked_reason="",
        required_env=[],
        urls=[cfg["url"]],
    )


def _v2_doc_type(adapter_chunk_meta: dict[str, Any], default: str) -> str:
    """Map adapter chunk metadata to the v2 doc_type vocabulary."""
    legal_type = str(adapter_chunk_meta.get("legal_type") or "").lower()
    doc_type = str(adapter_chunk_meta.get("doc_type") or "").lower()
    candidate = legal_type or doc_type or default
    if candidate in {"case_law", "case", "judgment", "judgement", "opinion"}:
        return "case_law"
    if candidate in {"statute", "legislation", "act", "regulation", "directive"}:
        return "statute"
    if candidate in {"treaty", "convention", "covenant", "protocol"}:
        return "treaty"
    if candidate in {"commentary", "academic", "secondary", "remote_source_content"}:
        return default if default in {"case_law", "statute", "treaty"} else "commentary"
    return default


def _adapter_chunk_to_v2_doc(
    chunk: dict[str, Any],
    *,
    source_key: str,
    chunk_index: int,
) -> dict[str, Any] | None:
    """Convert a `(text, metadata)` adapter chunk into a v2 Qdrant doc."""
    text = (chunk.get("text") or "").strip()
    if len(text) < 80:
        return None
    meta = dict(chunk.get("metadata") or {})
    cfg = _SOURCE_REGISTRY[source_key]

    chunk_id = (
        meta.get("chunk_id")
        or meta.get("canonical_doc_id")
        or f"{source_key}:{chunk_index}"
    )
    citation = (
        meta.get("citation")
        or meta.get("source_name")
        or meta.get("case_name")
        or cfg["name"]
    )
    url = (
        meta.get("source_url")
        or meta.get("original_source_url")
        or cfg["url"]
    )

    return {
        "source_id": f"{source_key}::{chunk_id}",
        "citation": str(citation),
        "jurisdiction": cfg["v2_jurisdiction"],
        "doc_type": _v2_doc_type(meta, cfg["default_doc_type"]),
        "url": str(url),
        "text": text,
        # Light extras kept on the payload — Qdrant stores them as filterable fields.
        "court": meta.get("court", "") or meta.get("court_or_body", ""),
        "year": meta.get("year"),
        "license_note": meta.get("license_note", "") or cfg["license_note"],
        "remote_adapter": cfg["adapter"],
        "collection": cfg["collection"],
        "chunk_index": chunk_index,
    }


def _invoke_adapter(
    source_key: str,
    *,
    max_items: int,
    max_bytes: int,
    budget_gb: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Build minimal record/plan/budget and call the adapter."""
    from src.services.adapters import get_adapter_registry, has_adapter

    cfg = _SOURCE_REGISTRY[source_key]
    if not has_adapter(cfg["adapter"]):
        raise RuntimeError(f"Adapter {cfg['adapter']} is not registered")

    record = _build_record(source_key)
    plan = _build_plan(source_key)

    download_root = CORPUS_DIR / "remote" / source_key
    download_root.mkdir(parents=True, exist_ok=True)

    budget = BudgetManager(
        root=download_root,
        budget_bytes=int(budget_gb * 1024 * 1024 * 1024),
        min_free_bytes=int(2 * 1024 * 1024 * 1024),  # always keep 2 GB free
    )

    adapter_fn: Callable = get_adapter_registry()[cfg["adapter"]]
    return adapter_fn(
        record,
        plan,
        root=download_root,
        budget=budget,
        max_items=max_items,
        max_bytes=max_bytes,
        mode="licensed",
        checkpoint={},
        resume=False,
        ingest=False,
    )


def ingest_source(
    source_key: str,
    *,
    max_items: int = 25,
    max_bytes_per_item: int = 10 * 1024 * 1024,
    budget_gb: float = 5.0,
    batch_size: int = 32,
) -> dict[str, Any]:
    """Run one source's adapter and upsert resulting chunks into v2 Qdrant."""
    if source_key not in _SOURCE_REGISTRY:
        raise ValueError(f"Unknown source {source_key!r}; valid: {AVAILABLE_SOURCES}")

    log.info("→ Ingesting source: %s (max_items=%d)", source_key, max_items)
    ensure_collection()

    chunks, events = _invoke_adapter(
        source_key,
        max_items=max_items,
        max_bytes=max_bytes_per_item,
        budget_gb=budget_gb,
    )

    error_events = [e for e in events if isinstance(e, dict) and e.get("status") in {"error", "adapter_error", "http_error"}]
    if error_events:
        for err in error_events[:5]:
            log.warning("  adapter event: %s", err)

    if not chunks:
        log.warning("  no chunks returned for %s (events=%d)", source_key, len(events))
        return {
            "source": source_key,
            "fetched_chunks": 0,
            "upserted": 0,
            "errors": len(error_events),
        }

    docs: list[dict[str, Any]] = []
    skipped = 0
    for i, chunk in enumerate(chunks):
        doc = _adapter_chunk_to_v2_doc(chunk, source_key=source_key, chunk_index=i)
        if doc is None:
            skipped += 1
            continue
        docs.append(doc)

    log.info("  fetched %d chunks → %d v2 docs (skipped %d short)", len(chunks), len(docs), skipped)

    upserted_total = 0
    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        upserted_total += upsert_documents(batch)
        log.info("  upserted %d / %d", upserted_total, len(docs))

    return {
        "source": source_key,
        "fetched_chunks": len(chunks),
        "v2_docs": len(docs),
        "upserted": upserted_total,
        "errors": len(error_events),
    }


def ingest_all(
    *,
    max_items: int = 25,
    max_bytes_per_item: int = 10 * 1024 * 1024,
    budget_gb: float = 5.0,
    batch_size: int = 32,
    sources: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Run every source listed (default: all). Failures are logged, not fatal."""
    selected = sources or AVAILABLE_SOURCES
    results: list[dict[str, Any]] = []
    for key in selected:
        try:
            res = ingest_source(
                key,
                max_items=max_items,
                max_bytes_per_item=max_bytes_per_item,
                budget_gb=budget_gb,
                batch_size=batch_size,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("Source %s failed: %s", key, exc)
            res = {"source": key, "error": f"{type(exc).__name__}: {exc}"}
        results.append(res)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Bulk-ingest remote legal sources into pipeline_v2 Qdrant")
    # Source selection is required UNLESS --list is given. Validate manually
    # so --list works standalone (argparse mutex groups can't depend on flags).
    p.add_argument("--source", choices=AVAILABLE_SOURCES, help="Single source to ingest")
    p.add_argument("--all", action="store_true", help="Ingest every registered source")

    p.add_argument("--max-items", type=int, default=25, help="Max items per source (default: 25)")
    p.add_argument("--budget-gb", type=float, default=5.0, help="Adapter download budget (GB, default: 5)")
    p.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024, help="Max bytes per item")
    p.add_argument("--reset", action="store_true", help="Wipe v2 Qdrant collection first")
    p.add_argument("--list", action="store_true", help="Print supported sources and exit")
    args = p.parse_args(argv)

    if args.list:
        for key in AVAILABLE_SOURCES:
            cfg = _SOURCE_REGISTRY[key]
            print(f"  {key:18s} -> {cfg['adapter']:25s} ({cfg['v2_jurisdiction']}, {cfg['default_doc_type']})")
        return 0

    if not (args.source or args.all):
        p.error("one of --source, --all, or --list is required")
    if args.source and args.all:
        p.error("--source and --all are mutually exclusive")

    if args.reset:
        log.info("Clearing v2 Qdrant collection…")
        clear_collection()
    ensure_collection()

    if args.all:
        results = ingest_all(
            max_items=args.max_items,
            max_bytes_per_item=args.max_bytes,
            budget_gb=args.budget_gb,
        )
    else:
        results = [ingest_source(
            args.source,
            max_items=args.max_items,
            max_bytes_per_item=args.max_bytes,
            budget_gb=args.budget_gb,
        )]

    total_upserted = sum(int(r.get("upserted", 0) or 0) for r in results)
    log.info("=" * 60)
    log.info("Ingestion complete. Upserted %d docs across %d sources.", total_upserted, len(results))
    for r in results:
        log.info("  %-18s upserted=%-6s fetched=%-6s errors=%s",
                 r.get("source", "?"),
                 r.get("upserted", "—"),
                 r.get("fetched_chunks", "—"),
                 r.get("errors", r.get("error", "0")))
    log.info("v2 collection now contains %d points.", collection_count())
    return 0 if total_upserted > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
