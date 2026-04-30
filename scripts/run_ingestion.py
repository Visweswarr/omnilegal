#!/usr/bin/env python3
"""CLI runner for OmniLegal remote source ingestion pipeline.

Usage:
    python scripts/run_ingestion.py --audit-only
    python scripts/run_ingestion.py --status
    python scripts/run_ingestion.py --phase 1 --download --ingest
    python scripts/run_ingestion.py --all --download --ingest
    python scripts/run_ingestion.py --phase 1 --download  # download only, no Qdrant upsert
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Fix Windows console encoding
import io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Prevent src.services.__init__.py from eagerly loading heavy ML models
# (retrieval_qa → retriever → BGE-M3). We only need remote_sources here.
import types as _types
if "src.services" not in sys.modules:
    _stub = _types.ModuleType("src.services")
    _stub.__path__ = [str(_PROJECT_ROOT / "src" / "services")]
    _stub.__package__ = "src.services"
    sys.modules["src.services"] = _stub

from src.config import INGESTION_PHASES, SOURCE_ALIASES


def _print_section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}\n")


def cmd_audit(args: argparse.Namespace) -> None:
    """Run source audit and print summary."""
    _print_section("📋 Source Audit")
    from src.services.remote_sources import source_audit_summary
    result = source_audit_summary()
    summary = result["summary"]

    print(f"Total sources:        {summary['total_sources']}")
    print(f"Fetchable:            {summary['fetchable']}")
    print(f"Metadata only:        {summary['metadata_only']}")
    print(f"Permission required:  {summary['permission_required']}")
    print(f"Credential required:  {summary['credential_required']}")
    print(f"Tier-3 blocked:       {summary['tier3_blocked']}")

    if summary.get("missing_env"):
        print(f"\n⚠️  Missing env vars: {', '.join(summary['missing_env'])}")

    print("\n📦 Collections:")
    for coll, count in sorted(summary.get("collections", {}).items()):
        print(f"  {coll:30s} → {count} sources")

    # Show per-source details
    print("\n📝 Source details:")
    for row in result["sources"]:
        rec = row["record"]
        plan = row["plan"]
        status = "✅" if plan["allowed_to_fetch"] else "🔒" if plan["action"] == "permission_required" else "🔑" if plan["action"] == "credential_required" else "⛔"
        print(f"  {status} {rec['name']:40s} → {plan['collection']:25s} [{plan['adapter']}]")
        if plan["blocked_reason"]:
            print(f"       ↳ {plan['blocked_reason']}")


def cmd_status(args: argparse.Namespace) -> None:
    """Show current ingestion status."""
    _print_section("📊 Ingestion Status")
    from src.services.remote_sources import remote_status
    status = remote_status()

    print(f"Root:              {status['root']}")
    print(f"Checkpoint exists: {status['checkpoint_exists']}")
    print(f"Checkpoint entries:{status['checkpoint_entries']}")

    if status.get("has_manifest"):
        print(f"\nLatest manifest:   {status.get('latest_manifest')}")
        print(f"  Catalog chunks:  {status.get('last_catalog_chunks', 0)}")
        print(f"  Remote chunks:   {status.get('last_remote_chunks', 0)}")
        upserted = status.get("last_upserted_by_collection", {})
        if upserted:
            print(f"  Upserted:")
            for coll, count in sorted(upserted.items()):
                print(f"    {coll:30s} → {count} points")

    if status.get("audit_summary"):
        s = status["audit_summary"]
        print(f"\nAudit: {s.get('fetchable', 0)} fetchable / {s.get('total_sources', 0)} total sources")


def _resolve_source_aliases(values: list[str]) -> list[str]:
    """Translate friendly aliases (e.g. ``courtlistener``) to adapter labels."""
    resolved: list[str] = []
    for raw in values:
        cleaned = raw.strip().lower()
        if not cleaned:
            continue
        resolved.append(SOURCE_ALIASES.get(cleaned, cleaned))
    return resolved


def cmd_list_sources(args: argparse.Namespace) -> None:
    """Print the friendly source aliases plus all adapter labels by phase."""
    _print_section("📚 Available source filters")
    print("Friendly aliases (use with --source):")
    for alias, label in sorted(SOURCE_ALIASES.items()):
        print(f"  {alias:18s} → {label}")
    print("\nAdapter labels by ingestion phase (use with --phase):")
    for phase, labels in sorted(INGESTION_PHASES.items()):
        print(f"  Phase {phase}: {', '.join(labels)}")


def cmd_ingest(args: argparse.Namespace) -> None:
    """Run ingestion for specified phase, sources, or all phases."""
    phase = args.phase
    sources = _resolve_source_aliases(getattr(args, "source", []) or [])
    download = args.download
    ingest = args.ingest
    max_items = args.max_items

    if sources:
        _print_section(f"🚀 Source-targeted Ingestion ({', '.join(sources)})")
        print(f"Target adapters: {sources}")
    elif phase:
        adapters = INGESTION_PHASES.get(phase, [])
        if not adapters:
            print(f"❌ Unknown phase {phase}. Valid phases: {sorted(INGESTION_PHASES.keys())}")
            return
        _print_section(f"🚀 Phase {phase} Ingestion")
        print(f"Target adapters: {adapters}")
    else:
        _print_section("🚀 Full Ingestion (all phases)")

    print(f"Download: {download}")
    print(f"Ingest to Qdrant: {ingest}")
    print(f"Max items per source: {max_items}")
    print()

    start = time.time()
    from src.services.remote_sources import run_remote_ingestion

    # Build adapter filter: --source takes precedence over --phase
    adapter_filter: list[str] | None = None
    if sources:
        adapter_filter = sources
    elif phase:
        adapter_filter = INGESTION_PHASES.get(phase, [])

    result = run_remote_ingestion(
        catalog=getattr(args, "catalog", None),
        download=download,
        ingest=ingest,
        max_items_per_source=max_items,
        budget_gb=args.budget_gb,
        mode=getattr(args, "mode", "licensed"),
        resume=not args.fresh,
        reset_checkpoint=getattr(args, "reset_checkpoint", False),
        adapter_filter=adapter_filter,
    )
    elapsed = time.time() - start

    _print_section("📊 Results")
    print(f"Time elapsed:       {elapsed:.1f}s")
    print(f"Source count:        {result.get('source_count', 0)}")
    print(f"Catalog chunks:     {result.get('catalog_chunks', 0)}")
    print(f"Remote chunks:      {result.get('remote_chunks', 0)}")
    print(f"Budget used:         {result.get('budget_used_bytes', 0) / 1024 / 1024:.1f} MB")
    print(f"Checkpoint entries:  {result.get('checkpoint_entries_after', 0)}")
    print(f"Skipped (checkpoint):{result.get('skipped_from_checkpoint', 0)}")

    upserted = result.get("upserted_by_collection", {})
    if upserted:
        print(f"\n📦 Upserted to Qdrant:")
        for coll, count in sorted(upserted.items()):
            print(f"  {coll:30s} → {count} points")

    # Print event summary
    events = result.get("events", [])
    errors = [e for e in events if isinstance(e, dict) and e.get("status") in {"error", "adapter_error", "http_error"}]
    if errors:
        print(f"\n⚠️  {len(errors)} error(s):")
        for err in errors[:10]:
            print(f"  ❌ {err.get('source_name', err.get('adapter', 'unknown'))}: {err.get('reason', err.get('status'))}")

    print(f"\n📄 Manifest: {result.get('manifest_path', 'N/A')}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OmniLegal Remote Source Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_ingestion.py --audit-only
  python scripts/run_ingestion.py --status
  python scripts/run_ingestion.py --list-sources
  python scripts/run_ingestion.py --phase 1 --download --ingest
  python scripts/run_ingestion.py --source courtlistener --download --ingest
  python scripts/run_ingestion.py --source courtlistener --source govinfo --download --ingest
  python scripts/run_ingestion.py --phase 1 --download --ingest --max-items 5
  python scripts/run_ingestion.py --all --download --ingest --fresh
        """,
    )

    sub = parser.add_subparsers(dest="command")

    # Audit
    audit_p = sub.add_parser("audit", help="Run source audit")
    audit_p.set_defaults(func=cmd_audit)

    # Status
    status_p = sub.add_parser("status", help="Show ingestion status")
    status_p.set_defaults(func=cmd_status)

    # Ingest (default)
    parser.add_argument("--audit-only", action="store_true", help="Run source audit only")
    parser.add_argument("--status", action="store_true", help="Show ingestion status")
    parser.add_argument("--list-sources", action="store_true", help="List adapter labels and friendly aliases")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run specific phase (1-4)")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Run a single adapter. Accepts friendly aliases (courtlistener, govinfo, "
            "eurlex, uk-legislation, indian-kanoon) or raw adapter labels. Repeatable."
        ),
    )
    parser.add_argument("--all", action="store_true", help="Run all phases")
    parser.add_argument("--catalog", default=None, help="Catalog path (default: caselaws)")
    parser.add_argument("--mode", default="licensed", choices=["licensed", "metadata-only"], help="Permission mode")
    parser.add_argument("--download", action="store_true", help="Download remote content")
    parser.add_argument("--ingest", action="store_true", help="Ingest into Qdrant")
    parser.add_argument("--max-items", type=int, default=10, help="Max items per source (default: 10)")
    parser.add_argument("--budget-gb", type=float, default=50.0, help="Disk budget in GB (default: 50)")
    parser.add_argument("--fresh", action="store_true", help="Ignore checkpoint, start fresh")
    parser.add_argument("--reset-checkpoint", action="store_true", help="Delete checkpoint before running")

    args = parser.parse_args()

    if hasattr(args, "func"):
        args.func(args)
    elif args.audit_only:
        cmd_audit(args)
    elif args.status:
        cmd_status(args)
    elif args.list_sources:
        cmd_list_sources(args)
    elif args.download or args.ingest or args.phase or args.all or args.source:
        cmd_ingest(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
