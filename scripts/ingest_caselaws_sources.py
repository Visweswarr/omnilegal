"""Convert the curated legal-source catalog under ``caselaws/*.json`` into
COMMENTARY_GLOBAL chunks. Each external source (ICJ, UN Treaty Collection,
Indian Kanoon, etc.) becomes a small commentary passage that the retriever
can surface for "where can I find X" / "is dataset Y available" questions.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import (
    CASELAWS_DIR,
    COLLECTION_COMMENTARY_GLOBAL,
)
from src.rag.vector_store import upsert_chunks


def _format_recommended_for(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item)
    return str(value or "")


def _source_to_chunk(jurisdiction: str, source: dict[str, Any], idx: int) -> dict[str, Any]:
    name = str(source.get("name") or "Unknown source").strip()
    url = str(source.get("url") or "").strip()
    type_ = str(source.get("type") or "").strip()
    coverage = str(source.get("coverage") or "").strip()
    access = str(source.get("access") or "").strip()
    fmt = str(source.get("format") or "").strip()
    license_ = str(source.get("license") or "").strip()
    rec = _format_recommended_for(source.get("recommended_for"))

    body = (
        f"Source catalog entry: {name}\n"
        f"Jurisdiction scope: {jurisdiction}\n"
        f"Type: {type_}\n"
        f"URL: {url}\n"
        f"Coverage: {coverage}\n"
        f"Access: {access}\n"
        f"Format: {fmt}\n"
        f"License: {license_}\n"
        f"Recommended for: {rec}\n"
    )

    metadata: dict[str, Any] = {
        "source_name": name,
        "source_url": url,
        "collection": COLLECTION_COMMENTARY_GLOBAL,
        "jurisdiction": "international" if jurisdiction.lower() == "international bodies" else jurisdiction.lower(),
        "doc_type": "source_catalog",
        "source_role": "source_catalog",
        "license_note": license_ or "see source",
        "private_public": "public",
        "citation": name,
        "chunk_index": idx,
        "tags": [t.strip() for t in rec.split(",") if t.strip()],
    }

    return {
        "raw_text": body,
        "text": body,
        "index_text": (
            f"[CATALOG] {name} ({type_}) — {jurisdiction}\nURL: {url}\n"
            f"Coverage: {coverage}\nAccess: {access}\n"
        ),
        "metadata": metadata,
    }


def build_caselaws_chunks() -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    if not CASELAWS_DIR.exists():
        return chunks

    idx = 0
    for json_file in sorted(CASELAWS_DIR.glob("*.json")):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"[caselaws] failed to parse {json_file.name}: {exc}")
            continue

        if isinstance(data, list):
            jurisdiction = json_file.stem.replace("_", " ").title()
            sources = data
        elif isinstance(data, dict):
            jurisdiction = str(data.get("jurisdiction") or json_file.stem.replace("_", " ").title())
            sources = data.get("sources") or []
        else:
            continue

        for source in sources:
            if not isinstance(source, dict):
                continue
            chunk = _source_to_chunk(jurisdiction, source, idx)
            chunks.append(chunk)
            idx += 1

    return chunks


def main() -> None:
    chunks = build_caselaws_chunks()
    if not chunks:
        print("[caselaws] no chunks built — directory empty or unreadable")
        return
    written = upsert_chunks(COLLECTION_COMMENTARY_GLOBAL, chunks)
    print(f"[caselaws] indexed {written} catalog entries into {COLLECTION_COMMENTARY_GLOBAL}")


if __name__ == "__main__":
    main()
