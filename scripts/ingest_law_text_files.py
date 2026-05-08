"""Ingest the *Law Text Files/* user-supplied corpus into the OmniLegal index.

Folder → collection routing (matches src.config GRANULAR_COLLECTIONS):

    Indian Law/                 → STATUTES_IN  (treatises on Indian law)
    International Law Texts/    → COMMENTARY_GLOBAL
    Israel Law/                 → STATUTES_IL
    Russian Law/                → STATUTES_RU
    USA LAW/                    → STATUTES_US

Each .txt file is treated as a single source document. Long files are
chunked with ``_chunk_plain_text`` (≈700-token windows, 100-token overlap).
Idempotent: a file's chunk IDs are derived from a stable hash so re-running
the script just upserts the same chunks.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (  # noqa: E402
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_US,
)
from src.rag.ingestion import _chunk_plain_text  # noqa: E402
from src.rag.vector_store import upsert_chunks  # noqa: E402

_LAW_TEXT_FILES_DIR = _PROJECT_ROOT / "Law Text Files"

# (folder name, collection, jurisdiction label, doc_type)
FOLDER_ROUTING: list[tuple[str, str, str, str]] = [
    ("Indian Law", COLLECTION_STATUTES_IN, "india", "treatise"),
    ("International Law Texts", COLLECTION_COMMENTARY_GLOBAL, "international", "commentary"),
    ("Israel Law", COLLECTION_STATUTES_IL, "israel", "treatise"),
    ("Russian Law", COLLECTION_STATUTES_RU, "russia", "treatise"),
    ("USA LAW", COLLECTION_STATUTES_US, "us", "treatise"),
]


def _readable_source_name(path: Path) -> str:
    """Strip noisy z-library / amazon suffixes from the filename."""
    name = path.stem
    # Remove (z-library.sk, 1lib.sk, z-lib.sk) and (… etc.) tails
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
        written = upsert_chunks(collection, chunks)
        print(f"[ok] {folder_name} → {collection}: {written} chunks indexed")
    else:
        print(f"[skip] {folder_name}: no .txt files produced any chunks")
    return written


def ingest_all_law_text_files(*, add_context: bool = False) -> dict[str, int]:
    """Ingest every routed folder under ``Law Text Files/``.

    Returns a mapping of ``collection → chunks_indexed``.
    """
    if not _LAW_TEXT_FILES_DIR.exists():
        print(f"[skip] Law Text Files directory missing at {_LAW_TEXT_FILES_DIR}")
        return {}

    summary: dict[str, int] = {}
    for folder_name, collection, jurisdiction, doc_type in FOLDER_ROUTING:
        print(f"\n>>> Ingesting Law Text Files/{folder_name} → {collection}")
        n = ingest_law_text_folder(
            folder_name,
            collection,
            jurisdiction,
            doc_type,
            add_context=add_context,
        )
        summary[collection] = summary.get(collection, 0) + n
    return summary


def main() -> int:
    print(f"Law Text Files root: {_LAW_TEXT_FILES_DIR}")
    summary = ingest_all_law_text_files()
    print("\n=== Law Text Files ingestion summary ===")
    grand = 0
    for col, count in summary.items():
        grand += count
        print(f"  {col}: {count} chunks")
    print(f"  Total: {grand} chunks across {len(summary)} collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
