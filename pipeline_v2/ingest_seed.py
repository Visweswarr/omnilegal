"""Seed the embedded Qdrant corpus from curated docs + caselaws/*.json.

Run:
    python -m pipeline_v2.ingest_seed            # seed with curated + source maps
    python -m pipeline_v2.ingest_seed --reset    # wipe the collection first
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pipeline_v2.seed_corpus import get_seed_docs
from pipeline_v2.settings import ROOT
from pipeline_v2.vector_store import (
    clear_collection,
    collection_count,
    ensure_collection,
    upsert_documents,
)

log = logging.getLogger("pipeline_v2.ingest_seed")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# Map the PDF source-map jurisdiction names to ISO codes used by the classifier
_JUR_MAP = {
    "United States": "US",
    "NATIONAL_US": "US",
    "United Kingdom": "UK",
    "NATIONAL_UK": "UK",
    "European Union": "EU",
    "NATIONAL_EU": "EU",
    "India": "IN",
    "NATIONAL_IN": "IN",
    "Russia": "RU",
    "Russian Federation": "RU",
    "NATIONAL_RU": "RU",
    "Israel": "IL",
    "NATIONAL_IL": "IL",
    "International bodies": "INTL",
    "International": "INTL",
    "INTERNATIONAL": "INTL",
}


def _from_caselaws() -> list[dict]:
    """Ingest the `/app/caselaws/*.json` files as commentary entries describing
    what primary sources exist per jurisdiction."""
    files = sorted((ROOT / "caselaws").glob("*.json"))
    docs: list[dict] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            log.warning("Could not read %s: %s", path, e)
            continue
        # mix.json is a list of source entries (heterogeneous)
        if isinstance(raw, list):
            raw = {"jurisdiction": "Mixed", "sources": raw}
        if not isinstance(raw, dict):
            continue
        jur_name = raw.get("jurisdiction") or path.stem
        jur_iso = _JUR_MAP.get(jur_name, (jur_name[:2].upper() if jur_name else "INTL") or "INTL")
        for src in raw.get("sources", []) or []:
            if not isinstance(src, dict):
                continue
            name = src.get("name") or "Unknown"
            stype = src.get("type") or "source"
            coverage = src.get("coverage") or ""
            access = src.get("access") or ""
            licence = src.get("license") or src.get("licence") or ""
            url = ""
            if isinstance(src.get("access"), str) and "http" in str(src.get("access", "")):
                # Sometimes access has URL strings
                for token in str(src.get("access", "")).split():
                    if token.startswith("http"):
                        url = token.rstrip(";")
                        break

            recommended = src.get("recommended_for") or src.get("recommended_for_collections") or []
            if isinstance(recommended, list):
                recommended_str = ", ".join(recommended)
            else:
                recommended_str = str(recommended)

            text = (
                f"Source map entry — {jur_name}: {name} ({stype}). "
                f"Coverage: {coverage}. Access: {access}. Licence: {licence}. "
                f"Recommended for: {recommended_str}. "
                "This entry describes where primary legal texts can be obtained for "
                f"the {jur_name} jurisdiction; it is metadata, not a legal rule."
            ).strip()
            if len(text) < 40:
                continue

            docs.append({
                "source_id": f"srcmap::{path.stem}::{name}",
                "citation": f"Source map: {name} ({jur_name})",
                "jurisdiction": jur_iso,
                "doc_type": "commentary",
                "url": url,
                "text": text,
            })
    return docs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="clear the collection first")
    p.add_argument("--only-seed", action="store_true", help="skip caselaws source map")
    args = p.parse_args(argv)

    if args.reset:
        log.info("Clearing Qdrant collection…")
        clear_collection()
    else:
        ensure_collection()

    docs = get_seed_docs()
    if not args.only_seed:
        docs.extend(_from_caselaws())

    log.info("Upserting %d documents…", len(docs))
    # Chunk to keep memory low and show progress
    total = 0
    batch_size = 32
    for i in range(0, len(docs), batch_size):
        batch = docs[i : i + batch_size]
        total += upsert_documents(batch)
        log.info("  upserted %d / %d", total, len(docs))

    count = collection_count()
    log.info("Collection now has %d points.", count)
    return 0 if count > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
