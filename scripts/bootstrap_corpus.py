"""Bootstrap the OmniLegal corpus: ingests bundled PDFs + caselaws catalog.

Run once after cloning / on first launch:

    python scripts/bootstrap_corpus.py

Pipeline (all idempotent, safe to re-run):
    1. Treaties: UN Charter, ICCPR, ICESCR  →  INTL_TREATIES
    2. Indian Constitution                  →  NATIONAL_IN
    3. Malcolm Shaw, International Law      →  SHAW_PRIVATE
    4. caselaws/*.json source catalog       →  COMMENTARY_GLOBAL
    5. data/corpus/**/*.jsonl seed corpora  →  matched per directory
    6. Local case-law JSONL (if present)    →  CASE_LAW_*

Heavy ingestion (Docling parse, BGE-m3 embedding) is skipped automatically
when those dependencies aren't installed; FastEmbed kicks in and gives a
working dense index in seconds.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (  # noqa: E402
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
    CORPUS_FILES,
)
from src.rag.ingestion import ingest_collection  # noqa: E402
from src.rag.vector_store import upsert_chunks  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s | %(message)s")
log = logging.getLogger("omnilegal.bootstrap")


def _ingest(name: str, collection: str) -> int:
    print(f"\n>>> Ingesting {name} ({collection})")
    try:
        chunks = ingest_collection(collection)
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] {name}: {exc}")
        return 0
    if not chunks:
        print(f"[skip] {name}: no chunks produced")
        return 0
    written = upsert_chunks(collection, chunks)
    print(f"[ok]   {name}: {written} chunks indexed")
    return written


def _ingest_caselaws() -> int:
    print("\n>>> Ingesting caselaws/*.json catalog (COMMENTARY_GLOBAL)")
    try:
        from scripts.ingest_caselaws_sources import build_caselaws_chunks
    except Exception as exc:  # noqa: BLE001
        print(f"[ERROR] caselaws: {exc}")
        return 0
    chunks = build_caselaws_chunks()
    if not chunks:
        print("[skip] caselaws: no chunks built")
        return 0
    written = upsert_chunks(COLLECTION_COMMENTARY_GLOBAL, chunks)
    print(f"[ok]   caselaws: {written} catalog entries indexed")
    return written


def _ingest_data_corpus_seeds() -> int:
    """Ingest pre-baked seed JSONLs under data/corpus/* so retrieval has a baseline."""
    from src.rag.ingestion import _chunk_plain_text  # noqa: WPS437

    from src.config import (
        CORPUS_DIR,
        COLLECTION_CASE_LAW_EU,
        COLLECTION_CASE_LAW_GLOBAL,
        COLLECTION_CASE_LAW_IL,
        COLLECTION_CASE_LAW_IN,
        COLLECTION_CASE_LAW_RU,
        COLLECTION_CASE_LAW_UK,
        COLLECTION_CASE_LAW_US,
        COLLECTION_NATIONAL_EU,
        COLLECTION_NATIONAL_IL,
        COLLECTION_NATIONAL_IN,
        COLLECTION_NATIONAL_RU,
        COLLECTION_NATIONAL_UK,
        COLLECTION_NATIONAL_US,
        COLLECTION_STATUTES_EU,
        COLLECTION_STATUTES_IL,
        COLLECTION_STATUTES_IN,
        COLLECTION_STATUTES_RU,
        COLLECTION_STATUTES_UK,
        COLLECTION_STATUTES_US,
        COLLECTION_INTL_TREATIES,
        COLLECTION_COMMENTARY_GLOBAL,
    )

    dir_to_collection: dict[str, str] = {
        "intl_treaties": COLLECTION_INTL_TREATIES,
        "national_in": COLLECTION_NATIONAL_IN,
        "national_us": COLLECTION_NATIONAL_US,
        "national_uk": COLLECTION_NATIONAL_UK,
        "national_eu": COLLECTION_NATIONAL_EU,
        "national_ru": COLLECTION_NATIONAL_RU,
        "national_il": COLLECTION_NATIONAL_IL,
        "statutes_us": COLLECTION_STATUTES_US,
        "statutes_in": COLLECTION_STATUTES_IN,
        "statutes_uk": COLLECTION_STATUTES_UK,
        "statutes_eu": COLLECTION_STATUTES_EU,
        "statutes_ru": COLLECTION_STATUTES_RU,
        "statutes_il": COLLECTION_STATUTES_IL,
        "case_law_global": COLLECTION_CASE_LAW_GLOBAL,
        "case_law_us": COLLECTION_CASE_LAW_US,
        "case_law_in": COLLECTION_CASE_LAW_IN,
        "case_law_eu": COLLECTION_CASE_LAW_EU,
        "case_law_uk": COLLECTION_CASE_LAW_UK,
        "case_law_ru": COLLECTION_CASE_LAW_RU,
        "case_law_il": COLLECTION_CASE_LAW_IL,
        "commentary_global": COLLECTION_COMMENTARY_GLOBAL,
    }

    import json as _json

    total_written = 0
    for sub in sorted(CORPUS_DIR.iterdir()):
        if not sub.is_dir():
            continue
        collection = dir_to_collection.get(sub.name)
        if not collection:
            continue
        chunks: list[dict] = []
        for jsonl in sorted(sub.glob("*.jsonl")):
            for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = _json.loads(line)
                except _json.JSONDecodeError:
                    continue
                text = row.get("text") or row.get("content") or row.get("summary") or ""
                if not text:
                    continue
                meta = dict(row.get("metadata") or {})
                source_name = (
                    row.get("source_name")
                    or row.get("title")
                    or meta.get("source_name")
                    or jsonl.stem.replace("_", " ").title()
                )
                jurisdiction = row.get("jurisdiction") or meta.get("jurisdiction") or "international"
                doc_type = row.get("doc_type") or meta.get("doc_type") or "commentary"
                chunks.extend(
                    _chunk_plain_text(
                        text,
                        collection=collection,
                        source_name=str(source_name),
                        jurisdiction=str(jurisdiction),
                        doc_type=str(doc_type),
                        add_context=False,
                    )
                )
        if chunks:
            written = upsert_chunks(collection, chunks)
            total_written += written
            print(f"[ok]   data/corpus/{sub.name}: {written} chunks → {collection}")
    return total_written


def main() -> int:
    print("Available source PDFs:")
    for key, path in CORPUS_FILES.items():
        print(f"  {key:22s}  {'OK' if path.exists() else 'MISSING'}  {path}")

    grand_total = 0
    grand_total += _ingest("Treaties (UN Charter, ICCPR, ICESCR)", COLLECTION_INTL_TREATIES)
    grand_total += _ingest("Constitution of India", COLLECTION_NATIONAL_IN)
    grand_total += _ingest("Malcolm Shaw — International Law", COLLECTION_SHAW_PRIVATE)
    grand_total += _ingest_caselaws()
    try:
        grand_total += _ingest_data_corpus_seeds()
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] data/corpus seed ingestion skipped: {exc}")
    print(f"\nTotal new/updated chunks: {grand_total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
