"""GPU-accelerated ingestion of *Law Text Files/* + intl_treaties/case_law JSONL using BGE-m3 on RTX 3050.

Sibling of ``ingest_law_text_files.py``. Differences:

* Forces ``OMNILEGAL_EMBED_PROVIDER=flagembedding`` and ``OMNILEGAL_EMBED_DEVICE=cuda:0``
  *before* importing the OmniLegal modules, so BGE-m3 (dense + sparse) loads on the GPU.
* Adds ``UK Law`` folder routing (missing from the original script).
* Ingests three additional JSONL corpora:
    - data/corpus/intl_treaties/un_treaties_full.jsonl   -> INTL_TREATIES
    - data/corpus/intl_treaties/icrc_ihl_corpus.jsonl    -> INTL_TREATIES
    - data/corpus/case_law_global/ihl_case_law.jsonl     -> CASE_LAW_GLOBAL
* Uses a smaller embed batch (``OMNILEGAL_EMBED_BATCH_SIZE=4``) - RTX 3050 has only 4 GB VRAM.
* Pins ``OMNILEGAL_EMBEDDING_DIM=1024`` to match BGE-m3 output.

Idempotent: chunk IDs are derived from a stable hash, so this *adds* to whatever
the prior CPU/FastEmbed run produced. Existing files re-upsert to the same
points; new files create new points.

Usage:

    python -m scripts.ingest_law_text_files_gpu                    # everything
    python -m scripts.ingest_law_text_files_gpu --only "UK Law"    # one folder
    python -m scripts.ingest_law_text_files_gpu --only "ihl_case_law.jsonl"
    python -m scripts.ingest_law_text_files_gpu --skip-jsonl       # folders only
    python -m scripts.ingest_law_text_files_gpu --skip-folders     # JSONL only
    python -m scripts.ingest_law_text_files_gpu --dry-run          # no embed
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.env import load_environment  # noqa: E402

# Load .env first, then force GPU + BGE-m3 before importing src.config.
load_environment()
os.environ["OMNILEGAL_EMBED_PROVIDER"] = "flagembedding"
os.environ["OMNILEGAL_EMBED_DEVICE"] = "cuda:0"
os.environ["OMNILEGAL_EMBED_BATCH_SIZE"] = "4"
os.environ["OMNILEGAL_EMBEDDING_DIM"] = "1024"
# Qdrant HTTP client read timeout. Default is 60s, which is too short for
# dense+sparse upserts of long-context BGE-m3 chunks. Read by vector_store.get_store().
os.environ.setdefault("QDRANT_TIMEOUT_SECONDS", "600")

from src.config import (  # noqa: E402
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
)
from src.rag.ingestion import _chunk_plain_text  # noqa: E402
from src.rag.vector_store import _stable_point_id, get_store, upsert_chunks  # noqa: E402

_LAW_TEXT_FILES_DIR = _PROJECT_ROOT / "Law Text Files"
_DATA_CORPUS_DIR = _PROJECT_ROOT / "data" / "corpus"

# (folder name, collection, jurisdiction label, doc_type)
FOLDER_ROUTING: list[tuple[str, str, str, str]] = [
    ("Indian Law", COLLECTION_STATUTES_IN, "india", "treatise"),
    ("International Law Texts", COLLECTION_COMMENTARY_GLOBAL, "international", "commentary"),
    ("Israel Law", COLLECTION_STATUTES_IL, "israel", "treatise"),
    ("Russian Law", COLLECTION_STATUTES_RU, "russia", "treatise"),
    ("UK Law", COLLECTION_STATUTES_UK, "uk", "treatise"),
    ("USA LAW", COLLECTION_STATUTES_US, "us", "treatise"),
]

# (relative jsonl path, collection, jurisdiction label, doc_type)
JSONL_ROUTING: list[tuple[str, str, str, str]] = [
    ("intl_treaties/un_treaties_full.jsonl", COLLECTION_INTL_TREATIES, "international", "treaty"),
    ("intl_treaties/icrc_ihl_corpus.jsonl", COLLECTION_INTL_TREATIES, "international", "treaty"),
    ("case_law_global/ihl_case_law.jsonl", COLLECTION_CASE_LAW_GLOBAL, "international", "case_law"),
]

# Keys consumed by the chunker directly - not duplicated into metadata_extra.
_CONSUMED_JSONL_KEYS = {
    "text",
    "content",
    "summary",
    "source_name",
    "title",
    "jurisdiction",
    "doc_type",
    "metadata",
}


def _readable_source_name(path: Path) -> str:
    name = path.stem
    for marker in (" (z-library", " (z-lib", " (1lib", " (Z-Library"):
        idx = name.find(marker)
        if idx != -1:
            name = name[:idx]
    return name.strip(" .-_") or path.stem


def _verify_gpu() -> None:
    try:
        import torch
    except ImportError:
        print("[fatal] PyTorch is not installed. `pip install torch --index-url https://download.pytorch.org/whl/cu121`")
        sys.exit(2)
    if not torch.cuda.is_available():
        print("[fatal] torch.cuda.is_available() is False. CUDA driver or torch build is wrong.")
        print("        Run `nvidia-smi` to confirm the driver, then reinstall torch with the cu121 wheel.")
        sys.exit(2)
    name = torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info(0)
    print(f"[gpu] {name} - {free / 1024**3:.2f} GB free / {total / 1024**3:.2f} GB total")


def _verify_collection_dim_compat(collections: set[str]) -> None:
    """Abort early if any existing target collection has a vector dim != 1024."""
    store = get_store()
    client = getattr(store, "client", None)
    if client is None:
        return  # SQLite fallback - dim is recorded per-row, no collection-level enforcement.

    bad: list[tuple[str, int]] = []
    for col in collections:
        try:
            info = client.get_collection(col)
        except Exception:
            continue  # Doesn't exist yet - will be created at 1024 by the upsert path.
        try:
            vectors_cfg = info.config.params.vectors
            if hasattr(vectors_cfg, "items"):
                dense_dim = vectors_cfg["dense"].size  # named-vector layout used by this codebase
            else:
                dense_dim = vectors_cfg.size
        except Exception:
            continue
        if dense_dim != 1024:
            bad.append((col, dense_dim))

    if bad:
        print("\n[fatal] Existing collections have a vector dim that doesn't match BGE-m3 (1024):")
        for col, dim in bad:
            print(f"  - {col}: {dim} dim")
        print("\nFix options:")
        print("  (a) Drop the mismatched collections in Qdrant and let this script recreate them at 1024.")
        print("  (b) Run this script against fresh suffixed collections (edit *_ROUTING tables).")
        print("  (c) Stay on FastEmbed (CPU) by running scripts/ingest_law_text_files.py instead.")
        sys.exit(3)


_UPSERT_BATCH = 8
_UPSERT_RETRIES = 3
_RESUME_PROBE_BATCH = 256


def _filter_already_ingested(collection: str, chunks: list[dict], *, label: str) -> list[dict]:
    """Drop chunks whose stable point ID is already stored in the target collection.

    This is what makes the script resumable: re-running after a crash skips
    every chunk that successfully reached Qdrant in a prior run, so we only
    pay the embedding cost for what's actually missing.
    """
    if not chunks:
        return chunks
    store = get_store()
    client = getattr(store, "client", None)
    if client is None:
        return chunks  # SQLite fallback — no cheap point-id existence probe.

    try:
        client.get_collection(collection)
    except Exception:
        return chunks  # collection doesn't exist yet, nothing to skip.

    ids = [_stable_point_id(collection, c) for c in chunks]
    existing: set[int] = set()
    for i in range(0, len(ids), _RESUME_PROBE_BATCH):
        batch_ids = ids[i : i + _RESUME_PROBE_BATCH]
        try:
            found = client.retrieve(
                collection_name=collection,
                ids=batch_ids,
                with_payload=False,
                with_vectors=False,
            )
            existing.update(int(p.id) for p in found)
        except Exception as exc:
            print(f"  [warn] {label}: resume probe failed ({exc}); falling back to full re-embed")
            return chunks

    remaining = [c for c, cid in zip(chunks, ids) if cid not in existing]
    if existing:
        print(f"  [resume] {label}: {len(existing)} already in {collection}, {len(remaining)} new to embed")
    return remaining


def _safe_upsert(collection: str, chunks: list[dict], *, label: str) -> int:
    """Upsert in tiny sub-batches with retries.

    Each sub-batch of ``_UPSERT_BATCH`` chunks is sent through ``upsert_chunks``.
    On Qdrant 408 / transient HTTP errors, we retry the same sub-batch up to
    ``_UPSERT_RETRIES`` times with linear backoff. If a sub-batch still fails,
    we halve it and try again (catches the rare "single chunk too large" case).
    """
    import time

    total = 0
    sub_batches: list[list[dict]] = [chunks[i : i + _UPSERT_BATCH] for i in range(0, len(chunks), _UPSERT_BATCH)]
    n_batches = len(sub_batches)
    for idx, sub in enumerate(sub_batches, start=1):
        attempt = 0
        current = sub
        while True:
            attempt += 1
            try:
                total += upsert_chunks(collection, current, batch_size=len(current) or 1)
                break
            except Exception as exc:
                msg = str(exc)
                transient = "408" in msg or "Timeout" in msg or "timed out" in msg or "Connection" in msg
                if not transient or attempt > _UPSERT_RETRIES:
                    # Final attempt: try halving the batch (one chunk may be huge).
                    if len(current) > 1:
                        mid = len(current) // 2
                        print(f"  [retry/split] {label} sub-batch {idx}/{n_batches}: splitting {len(current)} -> {mid}+{len(current) - mid}")
                        current_first, current = current[:mid], current[mid:]
                        try:
                            total += upsert_chunks(collection, current_first, batch_size=len(current_first) or 1)
                        except Exception as exc2:
                            print(f"  [error] {label} sub-batch {idx}/{n_batches} first-half still failing: {exc2}")
                        attempt = 0
                        continue
                    print(f"  [error] {label} sub-batch {idx}/{n_batches} (single chunk) gave up: {exc}")
                    break
                wait = 2 * attempt
                print(f"  [retry] {label} sub-batch {idx}/{n_batches} attempt {attempt} failed ({msg[:80]}); sleeping {wait}s")
                time.sleep(wait)
        if idx % 25 == 0 or idx == n_batches:
            print(f"  [progress] {label}: {idx}/{n_batches} sub-batches, {total} chunks upserted so far")
    return total


def ingest_folder(
    folder_name: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    *,
    dry_run: bool = False,
) -> int:
    folder = _LAW_TEXT_FILES_DIR / folder_name
    if not folder.exists():
        print(f"[skip] {folder_name}: folder not found at {folder}")
        return 0

    chunks: list[dict] = []
    for path in sorted(folder.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as exc:
            print(f"[warn] failed to read {path.name}: {exc}")
            continue
        if not text:
            continue
        source_name = _readable_source_name(path)
        file_chunks = _chunk_plain_text(
            text,
            collection=collection,
            source_name=source_name,
            jurisdiction=jurisdiction,
            doc_type=doc_type,
            metadata_extra={"original_filename": path.name},
        )
        if file_chunks:
            chunks.extend(file_chunks)
            print(f"  {source_name}: {len(file_chunks)} chunks")

    if not chunks:
        print(f"[skip] {folder_name}: no chunks produced")
        return 0
    if dry_run:
        print(f"[dry-run] {folder_name} -> {collection}: {len(chunks)} chunks (not upserted)")
        return len(chunks)

    chunks = _filter_already_ingested(collection, chunks, label=folder_name)
    if not chunks:
        print(f"[skip] {folder_name}: all chunks already in {collection} (resume)")
        return 0
    written = _safe_upsert(collection, chunks, label=folder_name)
    print(f"[ok] {folder_name} -> {collection}: {written} chunks upserted (GPU)")
    return written


def ingest_jsonl(
    rel_path: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    *,
    dry_run: bool = False,
) -> int:
    """Ingest a JSONL corpus file. Each line is one document.

    Mirrors the JSONL handling in ``src.rag.ingestion`` (line ~677): each row's
    ``text``/``content``/``summary`` field is chunked; remaining keys flow into
    ``metadata_extra`` for retrieval-time filters.
    """
    path = _DATA_CORPUS_DIR / rel_path
    if not path.exists():
        print(f"[skip] {rel_path}: file not found at {path}")
        return 0

    chunks: list[dict] = []
    skipped = 0
    bad = 0
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"  [warn] {rel_path}:{lineno} bad JSON: {exc}")
            bad += 1
            continue

        text = row.get("text") or row.get("content") or row.get("summary") or ""
        if not text:
            skipped += 1
            continue

        row_metadata = dict(row.get("metadata") or {})
        extra = {
            key: value
            for key, value in {**row, **row_metadata}.items()
            if key not in _CONSUMED_JSONL_KEYS
        }
        source_name = row.get("source_name") or row.get("title") or path.stem
        row_chunks = _chunk_plain_text(
            text,
            collection=collection,
            source_name=source_name,
            jurisdiction=row.get("jurisdiction") or jurisdiction,
            doc_type=row.get("doc_type") or doc_type,
            metadata_extra=extra,
        )
        if row_chunks:
            chunks.extend(row_chunks)

    print(f"  {path.name}: {len(chunks)} chunks (skipped {skipped} empty, {bad} bad lines)")
    if not chunks:
        return 0
    if dry_run:
        print(f"[dry-run] {rel_path} -> {collection}: {len(chunks)} chunks (not upserted)")
        return len(chunks)

    chunks = _filter_already_ingested(collection, chunks, label=path.name)
    if not chunks:
        print(f"[skip] {rel_path}: all chunks already in {collection} (resume)")
        return 0
    written = _safe_upsert(collection, chunks, label=path.name)
    print(f"[ok] {rel_path} -> {collection}: {written} chunks upserted (GPU)")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="GPU-accelerated Law Text Files + JSONL ingestion")
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        help=(
            "Restrict to one or more sources. Match folder name (e.g. 'UK Law') "
            "or JSONL basename (e.g. 'ihl_case_law.jsonl'). Repeatable."
        ),
    )
    parser.add_argument("--skip-folders", action="store_true", help="Skip the Law Text Files/* folders.")
    parser.add_argument("--skip-jsonl", action="store_true", help="Skip the JSONL corpora.")
    parser.add_argument("--dry-run", action="store_true", help="Chunk and report counts without embedding/upserting.")
    parser.add_argument("--skip-gpu-check", action="store_true", help="Skip the CUDA + collection-dim preflight checks.")
    args = parser.parse_args()

    print(f"Law Text Files root: {_LAW_TEXT_FILES_DIR}")
    print(f"Data corpus root:    {_DATA_CORPUS_DIR}")
    print(f"Embed provider: {os.environ.get('OMNILEGAL_EMBED_PROVIDER')} on {os.environ.get('OMNILEGAL_EMBED_DEVICE')}")

    folder_targets = [] if args.skip_folders else list(FOLDER_ROUTING)
    jsonl_targets = [] if args.skip_jsonl else list(JSONL_ROUTING)

    if args.only:
        wanted = {name.lower() for name in args.only}
        folder_targets = [t for t in folder_targets if t[0].lower() in wanted]
        jsonl_targets = [t for t in jsonl_targets if Path(t[0]).name.lower() in wanted or t[0].lower() in wanted]
        known = {t[0].lower() for t in FOLDER_ROUTING} | {Path(t[0]).name.lower() for t in JSONL_ROUTING}
        unknown = wanted - known
        if unknown:
            print(f"[warn] unknown sources ignored: {sorted(unknown)}")
        if not folder_targets and not jsonl_targets:
            print("[fatal] --only matched zero sources")
            return 1

    if not args.skip_gpu_check and not args.dry_run:
        _verify_gpu()
        target_cols = {t[1] for t in folder_targets} | {t[1] for t in jsonl_targets}
        _verify_collection_dim_compat(target_cols)

    summary: dict[str, int] = {}

    for folder_name, collection, jurisdiction, doc_type in folder_targets:
        print(f"\n>>> Ingesting Law Text Files/{folder_name} -> {collection}")
        n = ingest_folder(folder_name, collection, jurisdiction, doc_type, dry_run=args.dry_run)
        summary[collection] = summary.get(collection, 0) + n

    for rel_path, collection, jurisdiction, doc_type in jsonl_targets:
        print(f"\n>>> Ingesting data/corpus/{rel_path} -> {collection}")
        n = ingest_jsonl(rel_path, collection, jurisdiction, doc_type, dry_run=args.dry_run)
        summary[collection] = summary.get(collection, 0) + n

    print("\n=== GPU ingestion summary ===")
    grand = 0
    for col, count in summary.items():
        grand += count
        print(f"  {col}: {count} chunks")
    print(f"  Total: {grand} chunks across {len(summary)} collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
