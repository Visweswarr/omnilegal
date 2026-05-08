"""Minimal demo ingestion — small representative files only.

Instead of the full 14-file corpus, this script ingests just a few small,
representative texts so the demo can come up in ~8 minutes instead of
~45 minutes. The Indian Law collection is left alone if it already has
data (the previous full ingest was killed mid-run with ~2,176 chunks
already written).

Run from /app:
    /root/.venv/bin/python scripts/demo_quick_ingest.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.config import (  # noqa: E402
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_US,
)
from src.rag.ingestion import _chunk_plain_text  # noqa: E402
from src.rag.vector_store import get_store, upsert_chunks  # noqa: E402


def _ingest_text_file(
    path: Path,
    collection: str,
    *,
    jurisdiction: str,
    doc_type: str,
    source_name: str,
) -> int:
    print(f"  → {source_name} → {collection}", flush=True)
    t0 = time.time()
    text = path.read_text(encoding="utf-8", errors="ignore")
    chunks = _chunk_plain_text(
        text,
        collection=collection,
        source_name=source_name,
        jurisdiction=jurisdiction,
        doc_type=doc_type,
    )
    n = upsert_chunks(collection, chunks)
    print(f"    written {n} chunks in {time.time() - t0:.1f}s", flush=True)
    return n


def _ingest_pdf(path: Path, collection: str, *, jurisdiction: str, source_name: str) -> int:
    """Lightweight PDF ingest — extract text via pypdf and chunk."""
    try:
        from pypdf import PdfReader
    except ImportError:
        print(f"  ! pypdf not available, skipping {path.name}", flush=True)
        return 0
    print(f"  → {source_name} (pdf) → {collection}", flush=True)
    t0 = time.time()
    try:
        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages[:120]:  # cap at first 120 pages for speed
            try:
                text_parts.append(page.extract_text() or "")
            except Exception:
                continue
        text = "\n\n".join(text_parts)
    except Exception as exc:
        print(f"    failed: {type(exc).__name__}: {exc}", flush=True)
        return 0
    if not text.strip():
        return 0
    chunks = _chunk_plain_text(
        text,
        collection=collection,
        source_name=source_name,
        jurisdiction=jurisdiction,
        doc_type="treaty" if "Charter" in source_name or "Covenant" in source_name else "treatise",
    )
    n = upsert_chunks(collection, chunks)
    print(f"    written {n} chunks in {time.time() - t0:.1f}s", flush=True)
    return n


def main() -> None:
    started = time.time()
    base_txt = _ROOT / "Law Text Files"
    base_pdf = _ROOT / "data" / "pdfs"

    store = get_store()
    existing = set(store.available_collections())
    in_count = store.collection_point_count(COLLECTION_STATUTES_IN) if COLLECTION_STATUTES_IN in existing else 0
    print(f"existing STATUTES_IN points: {in_count}", flush=True)

    written_total = 0

    # Indian — only top up if very low (skip if already 2,000+).
    if in_count < 2000:
        path = base_txt / "Indian Law" / "Jurisprudence  Legal Theory Text book for Law students of India (Dr. V.D. Mahajan, Ph.D. etc.).txt"
        if path.exists():
            written_total += _ingest_text_file(
                path, COLLECTION_STATUTES_IN,
                jurisdiction="india", doc_type="treatise",
                source_name="Mahajan: Jurisprudence & Legal Theory (India)",
            )
    else:
        print("  → STATUTES_IN already populated, skipping", flush=True)

    # International commentary — small files
    print("\n>>> International commentary", flush=True)
    for fname, label in [
        ("introduction_to_roman_law_11934 (introduction_to_roman_law_11934) (z-library.sk, 1lib.sk, z-lib.sk) (1).txt",
         "Introduction to Roman Law"),
        ("Proportionality, Equality Laws, and Religion Conflicts in England, Canada, and the USA (Megan Pearson).txt",
         "Pearson: Proportionality, Equality Laws & Religion Conflicts"),
    ]:
        path = base_txt / "International Law Texts" / fname
        if path.exists():
            written_total += _ingest_text_file(
                path, COLLECTION_COMMENTARY_GLOBAL,
                jurisdiction="international", doc_type="commentary",
                source_name=label,
            )

    # Israel
    print("\n>>> Israel", flush=True)
    path = base_txt / "Israel Law" / "Prolonged Occupation and International Law Israel and Palestine (Nada Kiswanson (editor) etc.).txt"
    if path.exists():
        written_total += _ingest_text_file(
            path, COLLECTION_STATUTES_IL,
            jurisdiction="israel", doc_type="treatise",
            source_name="Kiswanson (ed.): Prolonged Occupation and International Law",
        )

    # Russia
    print("\n>>> Russia", flush=True)
    path = base_txt / "Russian Law" / "Russia, the Soviet Union, and Imperial Continuity in International Law (Lauri Mälksoo).txt"
    if path.exists():
        written_total += _ingest_text_file(
            path, COLLECTION_STATUTES_RU,
            jurisdiction="russia", doc_type="treatise",
            source_name="Mälksoo: Russia & Imperial Continuity in International Law",
        )

    # USA
    print("\n>>> USA", flush=True)
    path = base_txt / "USA LAW" / "Criminal Law and Procedure [USA] .txt"
    if path.exists():
        written_total += _ingest_text_file(
            path, COLLECTION_STATUTES_US,
            jurisdiction="us", doc_type="treatise",
            source_name="USA: Criminal Law and Procedure",
        )

    # Critical PDFs — UN Charter, ICCPR, ICESCR, Indian Constitution
    print("\n>>> Critical international PDFs", flush=True)
    pdf_jobs = [
        ("uncharter.pdf",                    COLLECTION_INTL_TREATIES,    "international", "UN Charter"),
        ("ccpr.pdf",                         COLLECTION_INTL_TREATIES,    "international", "ICCPR (1966)"),
        ("cescr.pdf",                        COLLECTION_INTL_TREATIES,    "international", "ICESCR (1966)"),
        ("Indian Constitutition.pdf",        COLLECTION_NATIONAL_IN,       "india",         "Constitution of India"),
        ("International Law (Malcolm N. Shaw).pdf", COLLECTION_SHAW_PRIVATE, "international",
         "Malcolm Shaw: International Law"),
    ]
    for fname, col, juris, label in pdf_jobs:
        path = base_pdf / fname
        if not path.exists():
            print(f"  ! missing {fname}", flush=True)
            continue
        written_total += _ingest_pdf(path, col, jurisdiction=juris, source_name=label)

    elapsed = time.time() - started
    print(f"\n=== DONE: wrote {written_total} chunks across all collections in {elapsed:.1f}s ===", flush=True)

    # Final inventory
    print("\nFinal inventory:")
    store2 = get_store()
    for col in [
        COLLECTION_STATUTES_IN, COLLECTION_STATUTES_US, COLLECTION_STATUTES_IL,
        COLLECTION_STATUTES_RU, COLLECTION_COMMENTARY_GLOBAL,
        COLLECTION_INTL_TREATIES, COLLECTION_NATIONAL_IN, COLLECTION_SHAW_PRIVATE,
    ]:
        try:
            n = store2.collection_point_count(col)
        except Exception:
            n = 0
        print(f"  {col}: {n}")


if __name__ == "__main__":
    main()
