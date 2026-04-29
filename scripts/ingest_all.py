"""
Unified multi-jurisdiction legal data ingestion.

Usage:
    python scripts/ingest_all.py                    # Full ingestion (all phases)
    python scripts/ingest_all.py --phase 0          # Reset garbage only
    python scripts/ingest_all.py --phase 2          # US cases only
    python scripts/ingest_all.py --phase 3          # EU ECHR only
    python scripts/ingest_all.py --phase 4          # Russia only
    python scripts/ingest_all.py --verify           # Verify current state
    python scripts/ingest_all.py --limit 100        # Limit docs per source
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent))
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

from src.config import (
    CASE_LAW_JSONL,
    COLLECTION_CASE_LAW,
    COLLECTION_COMMENTARY,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_SHAW_PRIVATE,
    QDRANT_URL,
)

# ── Garbage collections to purge ──────────────────────────────────────────
GARBAGE_COLLECTIONS = {
    COLLECTION_COMMENTARY,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_US,
}

# Collections that contain real data — never touch
PROTECTED_COLLECTIONS = {
    COLLECTION_NATIONAL_IN,     # 589 pts — real Constitution of India
    COLLECTION_SHAW_PRIVATE,    # 1184 pts — real Shaw textbook
    COLLECTION_INTL_TREATIES,   # 274 pts — real UN Charter + ICCPR
}


# ══════════════════════════════════════════════════════════════════════════
# TEXT CHUNKING
# ══════════════════════════════════════════════════════════════════════════

_SECTION_RE = re.compile(
    r"\b(FACTS|HELD|HOLDING|REASONING|DISPOSITIF|JUDGMENT|ORDER|"
    r"THE CIRCUMSTANCES OF THE CASE|THE LAW|PROCEDURE|AS TO THE MERITS|"
    r"OPERATIVE PROVISIONS|DISSENTING OPINION)\b",
    re.IGNORECASE,
)


def _chunk_legal_text(
    text: str,
    *,
    target_words: int = 600,
    overlap_words: int = 80,
) -> list[str]:
    """Smart legal text chunker.

    Tries to split at section/paragraph boundaries. Falls back to
    word-count-based splitting with overlap.
    """
    if not text or not text.strip():
        return []

    # Try section-based splitting first
    sections = _SECTION_RE.split(text)
    if len(sections) > 2:
        chunks = []
        current_section = ""
        current_text = ""
        for i, part in enumerate(sections):
            if _SECTION_RE.match(part):
                if current_text.strip() and len(current_text.split()) > 30:
                    chunks.append(f"{current_section}\n{current_text}".strip())
                current_section = part
                current_text = ""
            else:
                current_text += part
        if current_text.strip():
            chunks.append(f"{current_section}\n{current_text}".strip())

        # Re-chunk any oversized sections
        final = []
        for chunk in chunks:
            if len(chunk.split()) > target_words * 2:
                final.extend(_fixed_chunk(chunk, target_words, overlap_words))
            elif len(chunk.split()) > 30:
                final.append(chunk)
        if final:
            return final

    # Paragraph-based splitting
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) > 3:
        chunks = []
        current = []
        current_len = 0
        for para in paragraphs:
            words = len(para.split())
            if current_len + words > target_words and current:
                chunks.append("\n\n".join(current))
                # Keep last paragraph for overlap
                current = [current[-1]] if current else []
                current_len = len(current[0].split()) if current else 0
            current.append(para)
            current_len += words
        if current:
            chunks.append("\n\n".join(current))
        if len(chunks) > 1:
            return [c for c in chunks if len(c.split()) > 30]

    # Fixed-size fallback
    return _fixed_chunk(text, target_words, overlap_words)


def _fixed_chunk(text: str, target_words: int, overlap_words: int) -> list[str]:
    words = text.split()
    if len(words) <= target_words:
        return [text] if len(words) > 30 else []
    step = max(target_words - overlap_words, 100)
    chunks = []
    for start in range(0, len(words), step):
        chunk = " ".join(words[start:start + target_words])
        if len(chunk.split()) > 30:
            chunks.append(chunk)
    return chunks


# ══════════════════════════════════════════════════════════════════════════
# METADATA BUILDER
# ══════════════════════════════════════════════════════════════════════════

def _make_metadata(
    *,
    source_name: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    chunk_index: int,
    year: int | None = None,
    citation: str | None = None,
    section: str | None = None,
) -> dict[str, Any]:
    return {
        "source_name": source_name,
        "collection": collection,
        "jurisdiction": jurisdiction,
        "doc_type": doc_type,
        "year": year,
        "citation": citation or source_name,
        "chunk_index": chunk_index,
        "section": section,
        "license_note": "public/legal source",
    }


# ══════════════════════════════════════════════════════════════════════════
# PHASE 0: RESET GARBAGE
# ══════════════════════════════════════════════════════════════════════════

def phase_0_reset():
    """Delete garbage collections, keep protected ones."""
    import urllib.request

    print("=" * 60)
    print("PHASE 0: PURGING GARBAGE COLLECTIONS")
    print("=" * 60)

    for col in GARBAGE_COLLECTIONS:
        try:
            req = urllib.request.Request(
                f"{QDRANT_URL.rstrip('/')}/collections/{col}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=10)
            print(f"  DELETED: {col}")
        except Exception as e:
            print(f"  SKIP: {col} (may not exist: {e})")

    # Also purge CASE_LAW of US-mislabeled entries
    print("\n  Checking CASE_LAW for mislabeled US cases...")
    try:
        payload = json.dumps({
            "limit": 10, "with_payload": True, "with_vector": False,
        }).encode()
        req = urllib.request.Request(
            f"{QDRANT_URL.rstrip('/')}/collections/{COLLECTION_CASE_LAW}/points/scroll",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        points = data.get("result", {}).get("points", [])
        us_count = sum(
            1 for p in points
            if "oyez" in str(p.get("payload", {}).get("url", "")).lower()
            or "united states" in str(p.get("payload", {}).get("citation", "")).lower()
            or "v. United States" in str(p.get("payload", {}).get("source_name", ""))
        )
        if us_count > len(points) * 0.5:
            print(f"  WARNING: {us_count}/{len(points)} sampled CASE_LAW entries are US cases.")
            print("  DELETING entire CASE_LAW to rebuild with correct jurisdiction tags...")
            req = urllib.request.Request(
                f"{QDRANT_URL.rstrip('/')}/collections/{COLLECTION_CASE_LAW}",
                method="DELETE",
            )
            urllib.request.urlopen(req, timeout=10)
            print("  DELETED: CASE_LAW (will rebuild)")
        else:
            print(f"  CASE_LAW looks OK ({us_count}/{len(points)} US). Keeping.")
    except Exception as e:
        print(f"  Could not check CASE_LAW: {e}")

    print("\n  Protected (untouched):")
    for col in PROTECTED_COLLECTIONS:
        print(f"    {col}")

    print("\nPhase 0 complete.\n")


# ══════════════════════════════════════════════════════════════════════════
# PHASE 2: US CASES (existing 982MB JSONL)
# ══════════════════════════════════════════════════════════════════════════

def _detect_jurisdiction_from_case(case: dict) -> str:
    """Auto-detect jurisdiction from case metadata."""
    court = str(case.get("court", "")).lower()
    url = str(case.get("url", "")).lower()
    title = str(case.get("title", "")).lower()
    citation = str(case.get("citation", "")).lower()

    # US courts
    if any(kw in court for kw in ["warren", "burger", "rehnquist", "roberts", "supreme"]):
        return "us"
    if "oyez.org" in url or "justia.com" in url:
        return "us"
    if "u.s." in citation or "s.ct." in citation or "s. ct." in citation:
        return "us"

    # ICJ / International
    if any(kw in court for kw in ["icj", "international court", "pcij"]):
        return "international"
    if "icj" in url:
        return "international"

    # India
    if "india" in court or "india" in url:
        return "in"

    # EU
    if any(kw in court for kw in ["echr", "european", "cjeu"]):
        return "eu"

    return "us"  # Default for this JSONL which is Oyez/CourtListener


def _extract_case_text_full(case: dict) -> str:
    """Extract all text from a case record."""
    parts = []

    # Title/header
    title = case.get("title", "")
    citation = case.get("citation", "")
    if title:
        parts.append(title)
    if citation:
        parts.append(citation)

    # Justia sections (richest text source)
    justia = case.get("justia_sections", {})
    if isinstance(justia, dict):
        for section_name in ["Syllabus", "Opinion", "Dissent", "Concurrence"]:
            text = justia.get(section_name, "")
            if isinstance(text, str) and text.strip():
                parts.append(f"{section_name}:\n{text}")
            elif isinstance(text, list):
                parts.append(f"{section_name}:\n" + "\n".join(str(t) for t in text))

    # Summaries
    for key in ["justia_summary", "oyez_summary", "wikipedia_summary"]:
        val = case.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val)
        elif isinstance(val, dict):
            for sub_key, sub_val in val.items():
                if isinstance(sub_val, str) and sub_val.strip():
                    parts.append(f"{sub_key}: {sub_val}")
                elif isinstance(sub_val, list):
                    joined = " ".join(str(s) for s in sub_val if s)
                    if joined.strip():
                        parts.append(f"{sub_key}: {joined}")

    return "\n\n".join(parts)


def phase_2_us_cases(limit: int | None = None):
    """Ingest US Supreme Court cases from local JSONL."""
    from src.rag.vector_store import upsert_chunks, create_collection

    print("=" * 60)
    print("PHASE 2: US SUPREME COURT CASES")
    print("=" * 60)

    jsonl_path = CASE_LAW_JSONL
    if not jsonl_path or not Path(jsonl_path).exists():
        print(f"  JSONL not found at {jsonl_path}. Skipping.")
        return

    effective_limit = limit or 6733  # All cases
    print(f"  Source: {jsonl_path}")
    print(f"  Limit: {effective_limit}")

    # Create collections
    create_collection(COLLECTION_NATIONAL_US)
    create_collection(COLLECTION_CASE_LAW)

    all_us_chunks = []
    all_caslaw_chunks = []
    count = 0

    with open(jsonl_path, encoding="utf-8") as fh:
        for line in fh:
            if count >= effective_limit:
                break
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue

            text = _extract_case_text_full(case)
            if not text.strip() or len(text.split()) < 50:
                continue

            jurisdiction = _detect_jurisdiction_from_case(case)
            title = case.get("title", str(case.get("id", "Unknown")))
            year_str = str(case.get("year", ""))
            citation = case.get("citation", title)

            chunks = _chunk_legal_text(text)

            for idx, chunk_text in enumerate(chunks):
                # US chunks go to NATIONAL_US
                us_chunk = {
                    "text": chunk_text,
                    "metadata": _make_metadata(
                        source_name=title,
                        collection=COLLECTION_NATIONAL_US,
                        jurisdiction=jurisdiction,
                        doc_type="case_law",
                        chunk_index=idx,
                        year=int(year_str) if year_str.isdigit() else None,
                        citation=f"{citation} ({year_str})" if year_str else citation,
                    ),
                }
                all_us_chunks.append(us_chunk)

                # Also go to CASE_LAW (global)
                cl_chunk = {
                    "text": chunk_text,
                    "metadata": _make_metadata(
                        source_name=title,
                        collection=COLLECTION_CASE_LAW,
                        jurisdiction=jurisdiction,
                        doc_type="case_law",
                        chunk_index=idx,
                        year=int(year_str) if year_str.isdigit() else None,
                        citation=f"{citation} ({year_str})" if year_str else citation,
                    ),
                }
                all_caslaw_chunks.append(cl_chunk)

            count += 1
            if count % 500 == 0:
                print(f"  Processed {count} cases ({len(all_us_chunks)} chunks)...")

            # Batch upsert every 2000 chunks to manage memory
            if len(all_us_chunks) >= 2000:
                print(f"  Upserting batch: {len(all_us_chunks)} US + {len(all_caslaw_chunks)} CASE_LAW chunks...")
                upsert_chunks(COLLECTION_NATIONAL_US, all_us_chunks)
                upsert_chunks(COLLECTION_CASE_LAW, all_caslaw_chunks)
                all_us_chunks = []
                all_caslaw_chunks = []

    # Final batch
    if all_us_chunks:
        print(f"  Upserting final batch: {len(all_us_chunks)} US + {len(all_caslaw_chunks)} CASE_LAW chunks...")
        upsert_chunks(COLLECTION_NATIONAL_US, all_us_chunks)
        upsert_chunks(COLLECTION_CASE_LAW, all_caslaw_chunks)

    print(f"\n  Phase 2 complete: {count} cases ingested.\n")


# ══════════════════════════════════════════════════════════════════════════
# PHASE 3: EU (ECHR from HuggingFace)
# ══════════════════════════════════════════════════════════════════════════

def phase_3_eu_echr(limit: int | None = None):
    """Ingest European Court of Human Rights cases from lex_glue/ecthr_a."""
    from datasets import load_dataset
    from src.rag.vector_store import upsert_chunks, create_collection

    print("=" * 60)
    print("PHASE 3: EU — ECHR CASES")
    print("=" * 60)

    effective_limit = limit or 9000
    split_spec = f"train[:{effective_limit}]" if effective_limit < 9000 else "train"

    print(f"  Loading lex_glue/ecthr_a ({split_spec})...")
    ds = load_dataset("lex_glue", "ecthr_a", split=split_spec)
    print(f"  Loaded {len(ds)} cases.")

    create_collection(COLLECTION_NATIONAL_EU)

    # ECHR article labels
    echr_articles = ["2", "3", "5", "6", "8", "9", "10", "11", "14", "P1-1"]

    all_chunks = []
    case_law_chunks = []
    count = 0

    for row in ds:
        text_parts = row.get("text", [])
        if not text_parts:
            continue

        # Join all text paragraphs
        full_text = "\n\n".join(text_parts)
        if len(full_text.split()) < 50:
            continue

        # Determine which ECHR articles were violated
        labels = row.get("labels", [])
        violated = [echr_articles[l] for l in labels if l < len(echr_articles)]
        violated_str = ", ".join(violated) if violated else "none"

        # Use first paragraph as title approximation
        title_approx = text_parts[0][:100].strip() if text_parts else "ECHR Case"
        source_name = f"ECHR Case: {title_approx}"

        chunks = _chunk_legal_text(full_text)

        for idx, chunk_text in enumerate(chunks):
            chunk = {
                "text": chunk_text,
                "metadata": _make_metadata(
                    source_name=source_name,
                    collection=COLLECTION_NATIONAL_EU,
                    jurisdiction="eu",
                    doc_type="case_law",
                    chunk_index=idx,
                    citation=f"ECHR (Articles violated: {violated_str})",
                    section=f"echr_articles_{violated_str}",
                ),
            }
            all_chunks.append(chunk)

            # Also to CASE_LAW global
            cl_chunk = dict(chunk)
            cl_chunk["metadata"] = dict(chunk["metadata"])
            cl_chunk["metadata"]["collection"] = COLLECTION_CASE_LAW
            case_law_chunks.append(cl_chunk)

        count += 1
        if count % 1000 == 0:
            print(f"  Processed {count} ECHR cases ({len(all_chunks)} chunks)...")

        if len(all_chunks) >= 2000:
            print(f"  Upserting batch: {len(all_chunks)} EU + {len(case_law_chunks)} CASE_LAW...")
            upsert_chunks(COLLECTION_NATIONAL_EU, all_chunks)
            upsert_chunks(COLLECTION_CASE_LAW, case_law_chunks)
            all_chunks = []
            case_law_chunks = []

    if all_chunks:
        print(f"  Upserting final batch: {len(all_chunks)} EU + {len(case_law_chunks)} CASE_LAW...")
        upsert_chunks(COLLECTION_NATIONAL_EU, all_chunks)
        upsert_chunks(COLLECTION_CASE_LAW, case_law_chunks)

    print(f"\n  Phase 3 complete: {count} ECHR cases ingested.\n")


# ══════════════════════════════════════════════════════════════════════════
# PHASE 4: RUSSIA (RusLawOD from HuggingFace)
# ══════════════════════════════════════════════════════════════════════════

def phase_4_russia(limit: int | None = None):
    """Ingest Russian legal texts from irlspbru/RusLawOD."""
    from datasets import load_dataset
    from src.rag.vector_store import upsert_chunks, create_collection

    print("=" * 60)
    print("PHASE 4: RUSSIA — RusLawOD")
    print("=" * 60)

    effective_limit = limit or 5000
    # RusLawOD is 5.9GB — load streaming to avoid OOM
    print(f"  Loading irlspbru/RusLawOD (streaming, limit={effective_limit})...")

    try:
        ds = load_dataset("irlspbru/RusLawOD", split="train", streaming=True)
    except Exception as e:
        print(f"  Failed to load RusLawOD: {e}")
        print("  Skipping Phase 4.")
        return

    create_collection(COLLECTION_NATIONAL_RU)

    all_chunks = []
    count = 0

    for row in ds:
        if count >= effective_limit:
            break

        # RusLawOD fields vary — try common patterns
        text = ""
        for field in ["text", "content", "body", "document_text"]:
            if field in row and row[field]:
                text = str(row[field])
                break

        if not text.strip() or len(text.split()) < 30:
            continue

        title = str(row.get("title", row.get("name", f"Russian Legal Doc {count}")))
        doc_type = str(row.get("type", row.get("doc_type", "statute")))
        year = None
        date_str = str(row.get("date", row.get("year", "")))
        year_match = re.search(r"\b(19|20)\d{2}\b", date_str)
        if year_match:
            year = int(year_match.group(0))

        chunks = _chunk_legal_text(text)

        for idx, chunk_text in enumerate(chunks):
            chunk = {
                "text": chunk_text,
                "metadata": _make_metadata(
                    source_name=title,
                    collection=COLLECTION_NATIONAL_RU,
                    jurisdiction="ru",
                    doc_type=doc_type,
                    chunk_index=idx,
                    year=year,
                    citation=title,
                ),
            }
            all_chunks.append(chunk)

        count += 1
        if count % 500 == 0:
            print(f"  Processed {count} Russian docs ({len(all_chunks)} chunks)...")

        if len(all_chunks) >= 2000:
            print(f"  Upserting batch: {len(all_chunks)} RU chunks...")
            upsert_chunks(COLLECTION_NATIONAL_RU, all_chunks)
            all_chunks = []

    if all_chunks:
        print(f"  Upserting final batch: {len(all_chunks)} RU chunks...")
        upsert_chunks(COLLECTION_NATIONAL_RU, all_chunks)

    print(f"\n  Phase 4 complete: {count} Russian docs ingested.\n")


# ══════════════════════════════════════════════════════════════════════════
# PHASE 5: COMMENTARY REBUILD
# ══════════════════════════════════════════════════════════════════════════

def phase_5_commentary(limit: int | None = None):
    """Rebuild COMMENTARY with actual legal commentary from case holdings."""
    from datasets import load_dataset
    from src.rag.vector_store import upsert_chunks, create_collection

    print("=" * 60)
    print("PHASE 5: COMMENTARY REBUILD (case_hold)")
    print("=" * 60)

    effective_limit = limit or 45000
    split_spec = f"train[:{effective_limit}]" if effective_limit < 45000 else "train"

    print(f"  Loading lex_glue/case_hold ({split_spec})...")
    try:
        ds = load_dataset("lex_glue", "case_hold", split=split_spec)
    except Exception as e:
        print(f"  Failed to load case_hold: {e}")
        return

    print(f"  Loaded {len(ds)} case holdings.")

    create_collection(COLLECTION_COMMENTARY)

    all_chunks = []
    count = 0

    for row in ds:
        context = str(row.get("context", ""))
        holdings = row.get("endings", [])
        label = row.get("label", 0)

        if not context.strip() or len(context.split()) < 30:
            continue

        # The correct holding
        if isinstance(holdings, list) and label < len(holdings):
            correct_holding = holdings[label]
        else:
            correct_holding = ""

        # Combine context + correct holding for a rich commentary chunk
        full_text = context
        if correct_holding:
            full_text += f"\n\nHolding: {correct_holding}"

        source_name = "Legal Commentary (CaseHold)"
        citation_match = re.search(r"\d+ [A-Z]\.\w+\.?\s*\d+", context)
        citation = citation_match.group(0) if citation_match else source_name

        chunk = {
            "text": full_text,
            "metadata": _make_metadata(
                source_name=source_name,
                collection=COLLECTION_COMMENTARY,
                jurisdiction="international",  # Legal commentary is universal
                doc_type="commentary",
                chunk_index=count,
                citation=citation,
            ),
        }
        all_chunks.append(chunk)
        count += 1

        if count % 5000 == 0:
            print(f"  Processed {count} commentary entries...")

        if len(all_chunks) >= 3000:
            print(f"  Upserting batch: {len(all_chunks)} COMMENTARY chunks...")
            upsert_chunks(COLLECTION_COMMENTARY, all_chunks)
            all_chunks = []

    if all_chunks:
        print(f"  Upserting final batch: {len(all_chunks)} COMMENTARY chunks...")
        upsert_chunks(COLLECTION_COMMENTARY, all_chunks)

    print(f"\n  Phase 5 complete: {count} commentary entries ingested.\n")


# ══════════════════════════════════════════════════════════════════════════
# VERIFICATION
# ══════════════════════════════════════════════════════════════════════════

def verify():
    """Check all collections: count, sample, jurisdiction labels."""
    import urllib.request

    print("=" * 60)
    print("VERIFICATION: Collection Audit")
    print("=" * 60)

    all_collections = [
        COLLECTION_CASE_LAW,
        COLLECTION_COMMENTARY,
        COLLECTION_INTL_TREATIES,
        COLLECTION_NATIONAL_IN,
        COLLECTION_NATIONAL_US,
        COLLECTION_NATIONAL_UK,
        COLLECTION_NATIONAL_EU,
        COLLECTION_NATIONAL_RU,
        COLLECTION_NATIONAL_IL,
        COLLECTION_SHAW_PRIVATE,
    ]

    total_points = 0

    for col in all_collections:
        try:
            with urllib.request.urlopen(
                f"{QDRANT_URL.rstrip('/')}/collections/{col}", timeout=5
            ) as r:
                data = json.loads(r.read())
            count = data.get("result", {}).get("points_count", 0)
            total_points += count

            # Sample a few entries
            payload = json.dumps({
                "limit": 3, "with_payload": True, "with_vector": False
            }).encode()
            req = urllib.request.Request(
                f"{QDRANT_URL.rstrip('/')}/collections/{col}/points/scroll",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                scroll_data = json.loads(r.read())
            points = scroll_data.get("result", {}).get("points", [])

            jurisdictions = set()
            doc_types = set()
            sources = set()
            for p in points:
                pl = p.get("payload", {})
                jurisdictions.add(pl.get("jurisdiction", "?"))
                doc_types.add(pl.get("doc_type", "?"))
                sources.add(pl.get("source_name", "?")[:50])

            status = "[OK]" if count > 0 else "[EMPTY]"
            print(f"\n  {status} {col}: {count:,} points")
            print(f"     Jurisdictions: {jurisdictions}")
            print(f"     Doc types: {doc_types}")
            print(f"     Sources (sample): {list(sources)[:3]}")

        except Exception:
            print(f"\n  [MISSING] {col}: NOT FOUND")

    print(f"\n  TOTAL: {total_points:,} points across all collections")
    print()


# ══════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Multi-jurisdiction legal data ingestion")
    parser.add_argument("--phase", type=int, help="Run specific phase (0-5)")
    parser.add_argument("--limit", type=int, help="Limit documents per source")
    parser.add_argument("--verify", action="store_true", help="Verify current state only")
    args = parser.parse_args()

    if args.verify:
        verify()
        return

    phases = {
        0: ("Reset garbage", phase_0_reset),
        2: ("US cases", lambda: phase_2_us_cases(args.limit)),
        3: ("EU ECHR cases", lambda: phase_3_eu_echr(args.limit)),
        4: ("Russia RusLawOD", lambda: phase_4_russia(args.limit)),
        5: ("Commentary rebuild", lambda: phase_5_commentary(args.limit)),
    }

    if args.phase is not None:
        if args.phase in phases:
            name, func = phases[args.phase]
            print(f"\nRunning Phase {args.phase}: {name}")
            func()
        else:
            print(f"Unknown phase {args.phase}. Available: {list(phases.keys())}")
            return
    else:
        print("\n" + "=" * 60)
        print("FULL MULTI-JURISDICTION INGESTION")
        print("=" * 60)
        start = time.time()
        for phase_num in sorted(phases.keys()):
            name, func = phases[phase_num]
            print(f"\n{'='*60}")
            print(f"Starting Phase {phase_num}: {name}")
            print(f"{'='*60}")
            try:
                func()
            except Exception as e:
                print(f"\n  ERROR in Phase {phase_num}: {e}")
                print("  Continuing to next phase...\n")
        elapsed = time.time() - start
        print(f"\n{'='*60}")
        print(f"ALL PHASES COMPLETE in {elapsed / 60:.1f} minutes")
        print(f"{'='*60}\n")

    verify()


if __name__ == "__main__":
    main()
