"""Ingest the user-supplied local legal corpus into the OmniLegal index.

Folder -> collection routing (matches src.config GRANULAR_COLLECTIONS):

    Indian Law/                 -> STATUTES_IN  (treatises on Indian law)
    International Law Texts/    -> COMMENTARY_GLOBAL
    Israel Law/                 -> STATUTES_IL
    Russian Law/                -> STATUTES_RU
    UK Law/                     -> STATUTES_UK
    USA LAW/                    -> STATUTES_US

JSONL -> collection routing:

    data/corpus/intl_treaties/un_treaties_full.jsonl -> INTL_TREATIES
    data/corpus/intl_treaties/icrc_ihl_corpus.jsonl  -> INTL_TREATIES
    data/corpus/case_law_global/ihl_case_law.jsonl   -> CASE_LAW_GLOBAL

Each .txt file is treated as a single source document. Long files are
chunked with ``_chunk_plain_text`` (about 700-token windows, 100-token overlap).
Idempotent: a file's chunk IDs are derived from a stable hash so re-running
the script just upserts the same chunks.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

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
from src.rag.vector_store import upsert_chunks  # noqa: E402

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

# (relative jsonl path under data/corpus, collection, jurisdiction label, doc_type)
JSONL_ROUTING: list[tuple[str, str, str, str]] = [
    ("intl_treaties/un_treaties_full.jsonl", COLLECTION_INTL_TREATIES, "international", "treaty"),
    ("intl_treaties/icrc_ihl_corpus.jsonl", COLLECTION_INTL_TREATIES, "international", "treaty"),
    ("case_law_global/ihl_case_law.jsonl", COLLECTION_CASE_LAW_GLOBAL, "international", "case_law"),
]

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
    """Strip noisy z-library / amazon suffixes from the filename."""
    name = path.stem
    # Remove z-library / 1lib tails.
    for marker in (" (z-library", " (z-lib", " (1lib", " (Z-Library"):
        idx = name.find(marker)
        if idx != -1:
            name = name[:idx]
    return name.strip(" .-_") or path.stem


def ingest_law_text_folder(
    folder_name: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    *,
    add_context: bool = False,
    dry_run: bool = False,
) -> int:
    """Ingest every .txt file in *Law Text Files/<folder_name>/* into <collection>.

    Returns the number of chunks upserted.
    """
    folder = _LAW_TEXT_FILES_DIR / folder_name
    if not folder.exists():
        print(f"[skip] {folder_name}: folder not found at {folder}")
        return 0

    written = 0
    chunks: list[dict] = []
    for path in sorted(folder.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            print(f"[warn] failed to read {path.name}: {exc}")
            continue
        text = text.strip()
        if not text:
            continue
        source_name = _readable_source_name(path)
        file_chunks = _chunk_plain_text(
            text,
            collection=collection,
            source_name=source_name,
            jurisdiction=jurisdiction,
            doc_type=doc_type,
            add_context=add_context,
            metadata_extra={"original_filename": path.name},
        )
        if file_chunks:
            chunks.extend(file_chunks)
            print(f"  {source_name}: {len(file_chunks)} chunks")

    if chunks:
        if dry_run:
            print(f"[dry-run] {folder_name} -> {collection}: {len(chunks)} chunks (not upserted)")
            return len(chunks)
        written = upsert_chunks(collection, chunks)
        print(f"[ok] {folder_name} -> {collection}: {written} chunks indexed")
    else:
        print(f"[skip] {folder_name}: no .txt files produced any chunks")
    return written


def ingest_jsonl_corpus(
    rel_path: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    *,
    add_context: bool = False,
    dry_run: bool = False,
) -> int:
    """Ingest one routed JSONL file under ``data/corpus`` into <collection>."""
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
            add_context=add_context,
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

    written = upsert_chunks(collection, chunks)
    print(f"[ok] {rel_path} -> {collection}: {written} chunks indexed")
    return written


def ingest_all_law_text_files(
    *,
    add_context: bool = False,
    include_folders: bool = True,
    include_jsonl: bool = True,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest every routed local folder and JSONL corpus.

    Returns a mapping of ``collection -> chunks_indexed``.
    """
    if include_folders and not _LAW_TEXT_FILES_DIR.exists():
        print(f"[skip] Law Text Files directory missing at {_LAW_TEXT_FILES_DIR}")

    summary: dict[str, int] = {}
    if include_folders:
        for folder_name, collection, jurisdiction, doc_type in FOLDER_ROUTING:
            print(f"\n>>> Ingesting Law Text Files/{folder_name} -> {collection}")
            n = ingest_law_text_folder(
                folder_name,
                collection,
                jurisdiction,
                doc_type,
                add_context=add_context,
                dry_run=dry_run,
            )
            summary[collection] = summary.get(collection, 0) + n

    if include_jsonl:
        for rel_path, collection, jurisdiction, doc_type in JSONL_ROUTING:
            print(f"\n>>> Ingesting data/corpus/{rel_path} -> {collection}")
            n = ingest_jsonl_corpus(
                rel_path,
                collection,
                jurisdiction,
                doc_type,
                add_context=add_context,
                dry_run=dry_run,
            )
            summary[collection] = summary.get(collection, 0) + n
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Law Text Files plus selected JSONL corpora")
    parser.add_argument("--skip-folders", action="store_true", help="Skip the Law Text Files/* folders.")
    parser.add_argument("--skip-jsonl", action="store_true", help="Skip the routed JSONL corpora.")
    parser.add_argument("--dry-run", action="store_true", help="Chunk and report counts without embedding/upserting.")
    args = parser.parse_args()

    print(f"Law Text Files root: {_LAW_TEXT_FILES_DIR}")
    print(f"Data corpus root:    {_DATA_CORPUS_DIR}")
    summary = ingest_all_law_text_files(
        include_folders=not args.skip_folders,
        include_jsonl=not args.skip_jsonl,
        dry_run=args.dry_run,
    )
    print("\n=== Local corpus ingestion summary ===")
    grand = 0
    for col, count in summary.items():
        grand += count
        print(f"  {col}: {count} chunks")
    print(f"  Total: {grand} chunks across {len(summary)} collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
