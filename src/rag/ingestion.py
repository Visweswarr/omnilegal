"""
Structure-aware ingestion pipeline.

Treaty PDFs  -> per-Article chunks with metadata
Shaw textbook -> HierarchicalNodeParser (2048/512/128), footnotes as siblings
Indian const  -> section-based chunks
Case law JSONL -> 3-5 paragraph chunks preserving FACTS/HOLDING/REASONING labels
Contextual retrieval is opt-in and is applied to SHAW_PRIVATE/COMMENTARY by default.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    CASE_LAW_JSONL,
    CHUNK_OVERLAP,
    COLLECTION_CASE_LAW,
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_SHAW,
    CORPUS_DIR,
    CORPUS_FILES,
)

from src.rag.contextual_retrieval import generate_document_context

# ── Contextual retrieval backward compatibility/aliases ───────────────────

def _groq_context_prefix(doc_text: str, chunk_text: str) -> str:
    """Backward-compatible alias returning empty string locally because ingestion now runs natively at the document level."""
    return ""


def _base_metadata(
    *,
    source_name: str,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    chunk_index: int,
    year: int | None = None,
    article_number: str | None = None,
    page: int | None = None,
    citation: str | None = None,
    parent_id: str | None = None,
    footnote_ids: list[str] | None = None,
    context_prefix: str = "",
    private_public: str = "public",
    license_note: str = "public/legal source; verify upstream license before redistribution",
    **extra: Any,
) -> dict[str, Any]:
    metadata = {
        "source_name": source_name,
        "collection": collection,
        "jurisdiction": jurisdiction,
        "doc_type": doc_type,
        "year": year,
        "article_number": article_number,
        "page": page,
        "citation": citation or source_name,
        "parent_id": parent_id,
        "footnote_ids": footnote_ids or [],
        "chunk_index": chunk_index,
        "context_prefix": context_prefix,
        "license_note": license_note,
        "private_public": private_public,
    }
    metadata.update(extra)
    return metadata


def _index_text(raw_text: str, *, doc_context: str = "", metadata_lines: list[str] | None = None) -> str:
    """Build retrieval-only text while preserving raw text for display/citation."""
    raw_text = raw_text or ""
    metadata_lines = [line for line in (metadata_lines or []) if line]
    if not doc_context and not metadata_lines:
        return raw_text
    parts: list[str] = []
    if doc_context:
        parts.append(f"[DOC CONTEXT]\n{doc_context}")
    if metadata_lines:
        parts.append("[LOCAL METADATA]\n" + "\n".join(metadata_lines))
    parts.append(f"[CHUNK TEXT]\n{raw_text}")
    return "\n\n".join(parts)


def _chunk_record(raw_text: str, index_text: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "raw_text": raw_text,
        "text": raw_text,
        "index_text": index_text,
        "metadata": metadata,
    }


def _normalised_text_hash(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8", errors="ignore")).hexdigest()


# ── Docling PDF parsing ───────────────────────────────────────────────────

# Maximum pages Docling will attempt (prevents std::bad_alloc on large PDFs)
_DOCLING_MAX_PAGES = 20


def _parse_pdf_docling(pdf_path: Path) -> tuple[str, list[dict]]:
    """Parse a PDF. Uses pypdf (fast, no OCR) as primary; Docling as fallback."""
    # Try pypdf first: reliable for text-based legal PDFs, no RAM issues.
    try:
        import pypdf
        reader = pypdf.PdfReader(str(pdf_path))
        pages = [p.extract_text() or "" for p in reader.pages]
        full = "\n".join(pages)
        if full.strip():
            items = [{"text": full, "label": "TextItem", "level": 0, "is_footnote": False}]
            return full, items
        print(f"pypdf returned empty text for {pdf_path}, trying Docling...")
    except Exception as exc:
        print(f"pypdf failed for {pdf_path}: {exc}")

    # Fallback: Docling with OCR disabled and memory-safe settings
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import DocumentConverter, PdfFormatOption

        pipeline_opts = PdfPipelineOptions()
        pipeline_opts.do_ocr = False
        pipeline_opts.do_table_structure = False
        # Lower image resolution to reduce memory footprint
        if hasattr(pipeline_opts, "images_scale"):
            pipeline_opts.images_scale = 1.0  # default is 2.0

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)}
        )

        # Limit page count to prevent std::bad_alloc
        import pypdf as _pypdf_check
        total_pages = len(_pypdf_check.PdfReader(str(pdf_path)).pages)
        if total_pages > _DOCLING_MAX_PAGES:
            print(
                f"  WARNING: {pdf_path.name} has {total_pages} pages; "
                f"Docling will only process first {_DOCLING_MAX_PAGES} "
                f"(using pypdf for the rest)"
            )

        result = converter.convert(str(pdf_path))
        doc = result.document
        full_text_parts: list[str] = []
        items: list[dict] = []
        for item, _ in doc.iterate_items():
            label = type(item).__name__
            text = getattr(item, "text", "") or ""
            if not text.strip():
                continue
            full_text_parts.append(text)
            items.append({"text": text, "label": label,
                          "level": getattr(item, "level", 0),
                          "is_footnote": "Footnote" in label})
        return "\n".join(full_text_parts), items
    except MemoryError:
        print(f"Warning: Docling OOM for {pdf_path}; returning empty")
        return "", []
    except Exception as exc:
        print(f"Warning: all PDF parsers failed for {pdf_path}: {exc}")
        return "", []


# Keep alias for any legacy callers
_parse_pdf_fallback = _parse_pdf_docling


# ── Treaty chunking (per Article) ────────────────────────────────────────

_ARTICLE_RE = re.compile(r"^(Article\s+\d+[\w\-]*[^\n]*)", re.MULTILINE | re.IGNORECASE)


def _chunk_treaty(
    full_text: str,
    treaty_name: str,
    *,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    parts = _ARTICLE_RE.split(full_text)
    chunks: list[dict[str, Any]] = []

    doc_context = ""
    if add_context:
        doc_context = generate_document_context(
            source_name=treaty_name,
            doc_text=full_text,
            jurisdiction="international",
            doc_type="treaty"
        )

    preamble = parts[0].strip()
    if preamble:
        enriched_text = _index_text(preamble, doc_context=doc_context, metadata_lines=["Article: preamble"])

        chunks.append(_chunk_record(
            preamble,
            enriched_text,
            _base_metadata(
                source_name=treaty_name,
                collection=COLLECTION_INTL_TREATIES,
                jurisdiction="international",
                doc_type="treaty",
                article_number="preamble",
                chunk_index=0,
                context_prefix=doc_context,
                citation=f"{treaty_name}, preamble",
            ),
        ))

    article_idx = 1
    for i in range(1, len(parts) - 1, 2):
        article_header = parts[i].strip()
        article_body = parts[i + 1].strip()
        article_text = f"{article_header}\n{article_body}".strip()
        art_match = re.search(r"\d+[\w\-]*", article_header)
        art_id = art_match.group(0) if art_match else str(article_idx)
        
        enriched_text = _index_text(article_text, doc_context=doc_context, metadata_lines=[f"Article: {art_id}"])

        chunks.append(_chunk_record(
            article_text,
            enriched_text,
            _base_metadata(
                source_name=treaty_name,
                collection=COLLECTION_INTL_TREATIES,
                jurisdiction="international",
                doc_type="treaty",
                article_number=art_id,
                chunk_index=article_idx,
                context_prefix=doc_context,
                citation=f"{treaty_name}, art. {art_id}",
            ),
        ))
        article_idx += 1

    return chunks


# ── Shaw / textbook page-aware chunking ─────────────────────────────────

def _shaw_word_limit() -> int | None:
    """Return the explicit Shaw indexing cap, if configured.

    Empty/unset means full-PDF indexing. This intentionally replaces the old
    80k-word default cap.
    """
    raw = os.getenv("OMNILEGAL_SHAW_MAX_WORDS", "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _parse_pdf_pages_pypdf(pdf_path: Path) -> list[dict[str, Any]]:
    import pypdf

    reader = pypdf.PdfReader(str(pdf_path))
    return [
        {"page_number": idx + 1, "text": page.extract_text() or ""}
        for idx, page in enumerate(reader.pages)
    ]


def _normalise_page_records(page_texts: list[dict[str, Any]] | list[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, page in enumerate(page_texts):
        if isinstance(page, dict):
            page_number = int(page.get("page_number") or page.get("page") or idx + 1)
            text = str(page.get("text") or page.get("raw_text") or "")
        elif isinstance(page, (tuple, list)) and len(page) >= 2:
            page_number = int(page[0])
            text = str(page[1] or "")
        else:
            page_number = idx + 1
            text = str(page or "")
        if text.strip():
            records.append({"page_number": page_number, "text": text})
    return records


def _limit_page_records_by_words(page_texts: list[dict[str, Any]], max_words: int | None) -> list[dict[str, Any]]:
    if not max_words:
        return page_texts
    limited: list[dict[str, Any]] = []
    remaining = max_words
    for page in page_texts:
        words = str(page.get("text") or "").split()
        if not words:
            continue
        take = min(len(words), remaining)
        limited.append({"page_number": page["page_number"], "text": " ".join(words[:take])})
        remaining -= take
        if remaining <= 0:
            break
    return limited


def _infer_heading(text: str) -> str:
    for line in (text or "").splitlines():
        cleaned = re.sub(r"\s+", " ", line).strip(" .")
        if not cleaned or len(cleaned) > 120:
            continue
        if re.match(r"^(chapter|part|section|article)\b", cleaned, flags=re.IGNORECASE):
            return cleaned
        alpha = [ch for ch in cleaned if ch.isalpha()]
        if len(alpha) >= 6 and cleaned.upper() == cleaned:
            return cleaned.title()
    return ""


def _chunk_shaw_page_texts(
    page_texts: list[dict[str, Any]] | list[Any],
    *,
    add_context: bool = False,
    doc_context: str = "",
    chunk_size: int = 700,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    pages = _normalise_page_records(page_texts)
    if not pages:
        return []

    if add_context and not doc_context:
        doc_context = (
            "Private local Malcolm Shaw international-law commentary. "
            "Use this retrieval context only to improve matching against public international law "
            "concepts such as sources, treaties, custom, jurisdiction, state responsibility, "
            "use of force, immunities, human rights, and dispute settlement; display only short cited excerpts."
        )

    page_headings = {
        int(page["page_number"]): _infer_heading(str(page.get("text") or ""))
        for page in pages
    }
    tokens: list[tuple[str, int]] = []
    for page in pages:
        page_number = int(page["page_number"])
        for word in str(page.get("text") or "").split():
            tokens.append((word, page_number))
    if not tokens:
        return []

    step = max(chunk_size - overlap, 100)
    chunks: list[dict[str, Any]] = []
    for idx, start in enumerate(range(0, len(tokens), step)):
        token_slice = tokens[start : start + chunk_size]
        if not token_slice:
            continue
        raw_text = " ".join(word for word, _page in token_slice).strip()
        if not raw_text:
            continue
        page_start = min(page for _word, page in token_slice)
        page_end = max(page for _word, page in token_slice)
        heading = _infer_heading(raw_text) or page_headings.get(page_start) or f"Pages {page_start}-{page_end}"
        page_range = str(page_start) if page_start == page_end else f"{page_start}-{page_end}"
        content_hash = _normalised_text_hash(raw_text)
        parent_key = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")[:48] or f"pages-{page_range}"
        parent_id = f"shaw:{parent_key}"
        chunk_id = f"shaw:{page_start}:{page_end}:{idx}:{content_hash[:16]}"
        index_text = _index_text(
            raw_text,
            doc_context=doc_context,
            metadata_lines=[
                "Source: Malcolm Shaw - International Law",
                f"Page range: {page_range}",
                f"Heading: {heading}",
                "Corpus: private licensed commentary",
            ],
        )
        chunks.append(_chunk_record(
            raw_text,
            index_text,
            _base_metadata(
                source_name="Malcolm Shaw - International Law",
                collection=COLLECTION_SHAW,
                jurisdiction="international",
                doc_type="commentary",
                chunk_index=idx,
                page=page_start,
                page_start=page_start,
                page_end=page_end,
                heading=heading,
                parent_id=parent_id,
                chunk_id=chunk_id,
                content_hash=content_hash,
                context_prefix=doc_context,
                private_public="private",
                license_note="private/gated textbook corpus; output short cited excerpts only",
                citation=f"Malcolm N Shaw, International Law, pp. {page_range}",
            ),
        ))
    return chunks


def _chunk_shaw(
    pdf_path: Path,
    *,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    try:
        page_texts = _parse_pdf_pages_pypdf(pdf_path)
    except Exception as exc:
        print(f"Warning: page-aware Shaw parsing failed ({exc}), using fixed-size fallback")
        return _chunk_fixed_size(
            pdf_path,
            collection=COLLECTION_SHAW,
            source_name="Malcolm Shaw - International Law",
            jurisdiction="international",
            doc_type="commentary",
            add_context=add_context,
        )

    full_word_count = sum(len(str(page.get("text") or "").split()) for page in page_texts)
    max_words = _shaw_word_limit()
    if max_words and full_word_count > max_words:
        print(f"  Shaw full text has {full_word_count} words; indexing first {max_words} words because OMNILEGAL_SHAW_MAX_WORDS is set.")
        page_texts = _limit_page_records_by_words(page_texts, max_words)
    else:
        print(f"  Shaw full-PDF indexing enabled: {len(page_texts)} pages, {full_word_count} words.")

    return _chunk_shaw_page_texts(page_texts, add_context=add_context)


# ── Indian Constitution (section-based) ──────────────────────────────────

_ARTICLE_IN_RE = re.compile(
    r"^((?:Article|Section|Part)\s+\d+[A-Z]?\.?\s*[^\n]*)", re.MULTILINE | re.IGNORECASE
)


def _chunk_national_in(
    pdf_path: Path,
    *,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    full_text, _ = _parse_pdf_docling(pdf_path)
    parts = _ARTICLE_IN_RE.split(full_text)
    chunks: list[dict[str, Any]] = []

    doc_context = ""
    if add_context:
        doc_context = generate_document_context(
            source_name="Constitution of India",
            doc_text=full_text,
            jurisdiction="indian",
            doc_type="constitutional_text"
        )

    for idx, i in enumerate(range(1, len(parts) - 1, 2)):
        header = parts[i].strip()
        body = parts[i + 1].strip()
        text = f"{header}\n{body}".strip()
        art_match = re.search(r"\d+[A-Z]?", header)
        art_id = art_match.group(0) if art_match else str(idx)
        
        enriched_text = _index_text(text, doc_context=doc_context, metadata_lines=[f"Article: {art_id}"])

        chunks.append(_chunk_record(
            text,
            enriched_text,
            _base_metadata(
                source_name="Constitution of India",
                collection=COLLECTION_NATIONAL_IN,
                jurisdiction="indian",
                doc_type="constitutional_text",
                article_number=art_id,
                chunk_index=idx,
                context_prefix=doc_context,
                citation=f"Constitution of India, art. {art_id}",
                license_note="Indian public legal text; verify source copy before redistribution",
            ),
        ))

    if not chunks:
        return _chunk_fixed_size(
            pdf_path,
            collection=COLLECTION_NATIONAL_IN,
            source_name="Constitution of India",
            jurisdiction="indian",
            doc_type="constitutional_text",
            add_context=add_context,
        )
    return chunks


# ── Generic fixed-size chunker ────────────────────────────────────────────

def _chunk_fixed_size(
    pdf_path: Path,
    *,
    collection: str,
    source_name: str,
    jurisdiction: str = "international",
    doc_type: str = "unknown",
    chunk_size: int = 700,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    full_text, _ = _parse_pdf_docling(pdf_path)
    words = full_text.split()
    step = max(chunk_size - CHUNK_OVERLAP, 100)
    chunks: list[dict[str, Any]] = []

    doc_context = ""
    if add_context:
        doc_context = generate_document_context(
            source_name=source_name,
            doc_text=full_text,
            jurisdiction=jurisdiction,
            doc_type=doc_type
        )

    for idx, start in enumerate(range(0, len(words), step)):
        text = " ".join(words[start : start + chunk_size])
        
        enriched_text = _index_text(text, doc_context=doc_context, metadata_lines=[f"Chunk index: {idx}"])

        chunks.append(_chunk_record(
            text,
            enriched_text,
            _base_metadata(
                source_name=source_name,
                collection=collection,
                jurisdiction=jurisdiction,
                doc_type=doc_type,
                chunk_index=idx,
                context_prefix=doc_context,
                private_public="private" if collection == COLLECTION_SHAW else "public",
                license_note="private/gated textbook corpus; output short cited excerpts only" if collection == COLLECTION_SHAW else "public/legal source; verify upstream license before redistribution",
            ),
        ))
    return chunks


def _chunk_plain_text(
    text: str,
    *,
    collection: str,
    source_name: str,
    jurisdiction: str,
    doc_type: str,
    add_context: bool = False,
    private_public: str = "public",
    license_note: str = "public/legal source; verify upstream license before redistribution",
    metadata_extra: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    words = text.split()
    step = max(700 - CHUNK_OVERLAP, 100)
    chunks: list[dict[str, Any]] = []
    extra_metadata = dict(metadata_extra or {})
    citation = extra_metadata.pop("citation", None) or source_name
    year = extra_metadata.pop("year", None)
    article_number = extra_metadata.pop("article_number", None)
    page = extra_metadata.pop("page", None)
    parent_id = extra_metadata.pop("parent_id", None)
    footnote_ids = extra_metadata.pop("footnote_ids", None)
    
    doc_context = ""
    if add_context:
        doc_context = generate_document_context(
            source_name=source_name,
            doc_text=text,
            jurisdiction=jurisdiction,
            doc_type=doc_type
        )

    for idx, start in enumerate(range(0, len(words), step)):
        chunk_text = " ".join(words[start : start + 700])
        if not chunk_text.strip():
            continue
            
        enriched_text = _index_text(chunk_text, doc_context=doc_context, metadata_lines=[f"Chunk index: {idx}"])

        chunks.append(_chunk_record(
            chunk_text,
            enriched_text,
            _base_metadata(
                source_name=source_name,
                collection=collection,
                jurisdiction=jurisdiction,
                doc_type=doc_type,
                chunk_index=idx,
                year=year,
                article_number=article_number,
                page=page,
                citation=citation,
                parent_id=parent_id,
                footnote_ids=footnote_ids,
                context_prefix=doc_context,
                private_public=private_public,
                license_note=license_note,
                **extra_metadata,
            ),
        ))
    return chunks


def _ingest_directory_slot(
    directory: Path,
    *,
    collection: str,
    jurisdiction: str,
    doc_type: str,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    """Ingest local files for public-source expansion slots without scraping."""
    if not directory.exists():
        try:
            directory.mkdir(parents=True, exist_ok=True)
            readme = directory / "_PLACE_CORPUS_FILES_HERE.txt"
            readme.write_text(
                f"Directory auto-created for {collection} collection.\n"
                f"Expected jurisdiction: {jurisdiction}\n"
                f"Expected doc_type: {doc_type}\n\n"
                "Place PDFs, TXTs, or JSONL files in this folder to populate the collection locally. "
                "Any valid files placed here will be automatically converted into knowledge chunks during the next ingestion run."
            )
            print(f"[{collection}] Auto-created local source directory and README at: {directory}")
        except Exception as e:
            print(f"[{collection}] Cannot find or create local source directory {directory}: {e}")
        return []

    chunks: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        source_name = path.stem.replace("_", " ").strip()
        if suffix == ".pdf":
            chunks.extend(_chunk_fixed_size(
                path,
                collection=collection,
                source_name=source_name,
                jurisdiction=jurisdiction,
                doc_type=doc_type,
                add_context=add_context,
            ))
        elif suffix in {".txt", ".md"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            chunks.extend(_chunk_plain_text(
                text,
                collection=collection,
                source_name=source_name,
                jurisdiction=jurisdiction,
                doc_type=doc_type,
                add_context=add_context,
            ))
        elif suffix == ".jsonl":
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = row.get("text") or row.get("content") or row.get("summary") or ""
                if text:
                    row_metadata = dict(row.get("metadata") or {})
                    extra = {
                        key: value
                        for key, value in {**row, **row_metadata}.items()
                        if key not in {
                            "text",
                            "content",
                            "summary",
                            "source_name",
                            "title",
                            "jurisdiction",
                            "doc_type",
                            "metadata",
                        }
                    }
                    chunks.extend(_chunk_plain_text(
                        text,
                        collection=collection,
                        source_name=row.get("source_name") or row.get("title") or source_name,
                        jurisdiction=row.get("jurisdiction") or jurisdiction,
                        doc_type=row.get("doc_type") or doc_type,
                        add_context=add_context,
                        metadata_extra=extra,
                    ))
    print(f"{collection}: {len(chunks)} chunks from local slot {directory}")
    return chunks


# ── Case law JSONL ingestion ──────────────────────────────────────────────

_SECTION_RE = re.compile(
    r"\b(FACTS|HELD|HOLDING|REASONING|DISPOSITIF|JUDGMENT|ORDER)\b", re.IGNORECASE
)


def _flatten_case_field(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten_case_field(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            f"{key}: {_flatten_case_field(item)}"
            for key, item in value.items()
            if _flatten_case_field(item).strip()
        )
    return str(value)


def _extract_case_text(case: dict[str, Any]) -> str:
    parts = [
        case.get("text"),
        case.get("opinion_text"),
        case.get("justia_sections"),
        case.get("justia_summary"),
        case.get("oyez_summary"),
        case.get("wikipedia_summary"),
    ]
    text = "\n\n".join(_flatten_case_field(part) for part in parts if _flatten_case_field(part).strip())
    title = case.get("case_name") or case.get("title") or ""
    citation = case.get("citation") or ""
    header = " ".join(str(part) for part in [title, citation] if part)
    return f"{header}\n\n{text}".strip()


def _detect_case_jurisdiction(case: dict[str, Any]) -> str:
    court = str(case.get("court") or case.get("court_name") or case.get("jurisdiction") or "").lower()
    url = str(case.get("url") or case.get("source_url") or case.get("absolute_url") or "").lower()
    title = str(case.get("case_name") or case.get("title") or "").lower()
    source = " ".join([court, url, title])
    if any(term in source for term in ["oyez", "u.s.", "us supreme", "supreme court of the united states", "united states supreme", "scotus"]):
        return "us"
    if any(term in source for term in ["supreme court of india", "india", "indian"]):
        return "in"
    if any(term in source for term in ["echr", "ecthr", "european court", "court of justice", "cjeu", "curia"]):
        return "eu"
    if any(term in source for term in ["icj", "international court", "permanent court", "pca", "wto"]):
        return "international"
    return "international"


def _case_collection_for_jurisdiction(jurisdiction: str) -> str:
    return {
        "us": COLLECTION_CASE_LAW_US,
        "in": COLLECTION_CASE_LAW_IN,
        "eu": COLLECTION_CASE_LAW_EU,
        "international": COLLECTION_CASE_LAW_GLOBAL,
    }.get(jurisdiction, COLLECTION_CASE_LAW_GLOBAL)


def _chunk_case(case: dict[str, Any], *, add_context: bool = False) -> list[dict[str, Any]]:
    text = _extract_case_text(case)
    if not text.strip():
        return []
    source = case.get("case_name") or case.get("title") or str(case.get("id", "Unknown Case"))
    raw_date = case.get("date_filed") or case.get("decided_date") or ""
    year_match = re.search(r"\b(18|19|20)\d{2}\b", str(raw_date))
    year_str = year_match.group(0) if year_match else str(case.get("year", ""))
    jurisdiction = _detect_case_jurisdiction(case)
    collection = _case_collection_for_jurisdiction(jurisdiction)

    doc_context = ""
    if add_context:
        doc_context = generate_document_context(
            source_name=source,
            doc_text=text,
            jurisdiction=jurisdiction,
            doc_type="case_law"
        )

    sentences = re.split(r"(?<=[.!?])\s+", text)
    target_tokens = 700
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_len = 0
    chunk_idx = 0
    current_section = "GENERAL"

    for sent in sentences:
        sec_match = _SECTION_RE.search(sent)
        if sec_match:
            current_section = sec_match.group(0).upper()
        current.append(sent)
        current_len += len(sent.split())
        if current_len >= target_tokens:
            chunks.append(_make_case_chunk(
                current, source, current_section, year_str, chunk_idx, 
                full_text=text, doc_context=doc_context, jurisdiction=jurisdiction, collection=collection
            ))
            current = []
            current_len = 0
            chunk_idx += 1

    if current:
        chunks.append(_make_case_chunk(
            current, source, current_section, year_str, chunk_idx, 
            full_text=text, doc_context=doc_context, jurisdiction=jurisdiction, collection=collection
        ))
    return chunks


def _make_case_chunk(
    sentences: list[str],
    source: str,
    section: str,
    year_str: str,
    idx: int,
    *,
    full_text: str = "",
    doc_context: str = "",
    jurisdiction: str = "international",
    collection: str = COLLECTION_CASE_LAW_GLOBAL,
) -> dict[str, Any]:
    text = " ".join(sentences)

    enriched_text = _index_text(text, doc_context=doc_context, metadata_lines=[f"Section: {section}"])

    normalized = re.sub(r"\s+", " ", full_text or text).strip().lower()
    doc_hash = hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()
    source_fingerprint = hashlib.sha256("|".join([source.lower(), year_str, jurisdiction]).encode("utf-8", errors="ignore")).hexdigest()
    canonical_doc_id = f"local-case:{source_fingerprint[:24]}"
    return _chunk_record(
        text,
        enriched_text,
        _base_metadata(
            source_name=source,
            collection=collection,
            jurisdiction=jurisdiction,
            doc_type="case_law",
            legal_type="case_law",
            canonical_doc_id=canonical_doc_id,
            doc_hash=doc_hash,
            source_fingerprint=source_fingerprint,
            source_version=f"{year_str}-01-01" if year_str else "undated",
            version_date=f"{year_str}-01-01" if year_str else "undated",
            language="en",
            translation_status="original_only",
            importance_score=0.8 if jurisdiction in {"international", "us", "in", "eu"} and "supreme" in source.lower() else 0.3,
            importance_reason="local case-law import",
            importance_signals=["local_case_jsonl"],
            section=section,
            year=int(year_str) if year_str.isdigit() else None,
            chunk_index=idx,
            context_prefix=doc_context,
            citation=f"{source} ({year_str})" if year_str else source,
        ),
    )


def ingest_case_law_jsonl(
    path: Path | None = None,
    *,
    limit: int | None = None,
    add_context: bool = False,
    target_collection: str | None = None,
) -> list[dict[str, Any]]:
    p = Path(path) if path else (CASE_LAW_JSONL if CASE_LAW_JSONL else None)
    if not p or not p.exists():
        print(f"Case law JSONL not found at {p}; skipping. Local cases should be placed here if needed.")
        return []
    chunks: list[dict[str, Any]] = []
    count = 0
    effective_limit = limit if limit is not None else int(os.getenv("OMNILEGAL_CASE_LIMIT", "500"))
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            if effective_limit > 0 and count >= effective_limit:
                break
            try:
                case = json.loads(line)
                case_chunks = _chunk_case(case, add_context=add_context)
                if target_collection:
                    case_chunks = [c for c in case_chunks if c["metadata"]["collection"] == target_collection]
                if case_chunks:
                    chunks.extend(case_chunks)
                    count += 1
            except json.JSONDecodeError:
                continue
    print(f"Case law ({target_collection or 'all'}): {count} cases -> {len(chunks)} chunks")
    return chunks


# ── Public API ────────────────────────────────────────────────────────────

_TREATY_KEYS = {
    "un_charter": "UN Charter",
    "iccpr": "ICCPR",
    "icescr": "ICESCR",
}


def ingest_collection(
    collection_name: str,
    *,
    add_context: bool = False,
) -> list[dict[str, Any]]:
    """Produce chunks for the given collection from local corpus files."""
    chunks: list[dict[str, Any]] = []

    def add_source_catalog_entries() -> None:
        try:
            from src.services.remote_sources import source_catalog_chunks_for_collection
            catalog_chunks = source_catalog_chunks_for_collection(collection_name)
            if catalog_chunks:
                print(f"  Source catalog: {len(catalog_chunks)} chunks")
                chunks.extend(catalog_chunks)
        except Exception as exc:
            print(f"Warning: source catalog ingestion skipped for {collection_name}: {exc}")

    if collection_name == COLLECTION_INTL_TREATIES:
        for key, friendly_name in _TREATY_KEYS.items():
            path = CORPUS_FILES.get(key)
            if not path or not Path(path).exists():
                print(f"Skipping {friendly_name} - File not found. To populate this treaty, please place a PDF at: {path}")
                continue
            print(f"Chunking treaty: {friendly_name}")
            full_text, _ = _parse_pdf_docling(Path(path))
            treaty_chunks = _chunk_treaty(full_text, friendly_name, add_context=add_context)
            print(f"  {friendly_name}: {len(treaty_chunks)} chunks")
            chunks.extend(treaty_chunks)
        add_source_catalog_entries()

    elif collection_name == COLLECTION_SHAW:
        path = CORPUS_FILES.get("malcolm_shaw")
        if path and Path(path).exists():
            print("Chunking Shaw textbook (hierarchical)...")
            shaw_chunks = _chunk_shaw(Path(path), add_context=add_context)
            print(f"  Shaw: {len(shaw_chunks)} chunks")
            chunks.extend(shaw_chunks)
        else:
            print(f"Shaw PDF not found. To ingest the Shaw corpus, place the PDF at: {path}")
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_IN:
        path = CORPUS_FILES.get("indian_constitution")
        if path and Path(path).exists():
            print("Chunking Indian Constitution...")
            in_chunks = _chunk_national_in(Path(path), add_context=add_context)
            print(f"  Indian Constitution: {len(in_chunks)} chunks")
            chunks.extend(in_chunks)
        else:
            print(f"Indian Constitution PDF not found. To ingest it, place the PDF at: {path}")
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_in",
            collection=COLLECTION_NATIONAL_IN,
            jurisdiction="india",
            doc_type="domestic_law",
            add_context=add_context,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_CASE_LAW:
        chunks.extend(ingest_case_law_jsonl(add_context=add_context))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_COMMENTARY:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "commentary",
            collection=COLLECTION_COMMENTARY,
            jurisdiction="international",
            doc_type="commentary",
            add_context=add_context,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_US:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_us",
            collection=COLLECTION_NATIONAL_US,
            jurisdiction="us",
            doc_type="domestic_law",
            add_context=False,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_UK:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_uk",
            collection=COLLECTION_NATIONAL_UK,
            jurisdiction="uk",
            doc_type="domestic_law",
            add_context=False,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_EU:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_eu",
            collection=COLLECTION_NATIONAL_EU,
            jurisdiction="eu",
            doc_type="domestic_law",
            add_context=False,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_RU:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_ru",
            collection=COLLECTION_NATIONAL_RU,
            jurisdiction="russia",
            doc_type="domestic_law",
            add_context=False,
        ))
        add_source_catalog_entries()

    elif collection_name == COLLECTION_NATIONAL_IL:
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / "national_il",
            collection=COLLECTION_NATIONAL_IL,
            jurisdiction="israel",
            doc_type="domestic_law",
            add_context=False,
        ))
        add_source_catalog_entries()

    elif collection_name.startswith("CASE_LAW_"):
        jurisdiction_suffix = collection_name.replace("CASE_LAW_", "").lower()
        jurisdiction = "international" if jurisdiction_suffix == "global" else jurisdiction_suffix
        chunks.extend(ingest_case_law_jsonl(add_context=add_context, target_collection=collection_name))
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / f"case_law_{jurisdiction_suffix}",
            collection=collection_name,
            jurisdiction=jurisdiction,
            doc_type="case_law",
            add_context=add_context,
        ))
        add_source_catalog_entries()

    elif collection_name.startswith("STATUTES_"):
        jurisdiction_suffix = collection_name.replace("STATUTES_", "").lower()
        jurisdiction = "international" if jurisdiction_suffix == "global" else jurisdiction_suffix
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / f"statutes_{jurisdiction_suffix}",
            collection=collection_name,
            jurisdiction=jurisdiction,
            doc_type="domestic_law",
            add_context=add_context,
        ))
        add_source_catalog_entries()

    elif collection_name.startswith("COMMENTARY_"):
        jurisdiction_suffix = collection_name.replace("COMMENTARY_", "").lower()
        jurisdiction = "international" if jurisdiction_suffix == "global" else jurisdiction_suffix
        chunks.extend(_ingest_directory_slot(
            CORPUS_DIR / f"commentary_{jurisdiction_suffix}",
            collection=collection_name,
            jurisdiction=jurisdiction,
            doc_type="commentary",
            add_context=add_context,
        ))
        add_source_catalog_entries()

    else:
        print(f"No ingestion rule for collection {collection_name}; skipping.")

    print(f"\n[Ingestion Summary] Collection: {collection_name} | Total Processed Chunks: {len(chunks)}\n")
    return chunks


# ── Remote source ingestion ───────────────────────────────────────────────


def ingest_remote_sources(
    *,
    catalog: str | Path | None = None,
    phase: int | None = None,
    mode: str = "licensed",
    download: bool = True,
    ingest: bool = True,
    max_items_per_source: int = 10,
    budget_gb: float = 50,
    resume: bool = True,
    reset_checkpoint: bool = False,
    full_source: bool = False,
    target_collection_group: str = "all",
    quality_gate: str = "strict",
    update_mode: str = "overwrite_same_source_version",
    dedupe: str = "strict",
    importance_ranking: bool = True,
) -> dict[str, Any]:
    """Run the full remote-source pipeline: catalog → plan → download → chunk → Qdrant.

    Args:
        catalog: Optional catalog path. Defaults to ``caselaws``.
        phase:  If set, only run adapters in that phase (1-4). None = all.
        mode: Remote-source permission mode.
        download: Whether to actually fetch remote content.
        ingest: Whether to push chunks into Qdrant.
        max_items_per_source: Max documents/items per source.
        budget_gb: Disk-space budget cap.
        resume: Resume from checkpoint if available.
        reset_checkpoint: Delete the checkpoint before running.

    Returns:
        Manifest dict with statistics and events.
    """
    from src.services.remote_sources import run_remote_ingestion
    from src.config import INGESTION_PHASES

    adapter_filter = None
    if phase is not None:
        adapter_filter = INGESTION_PHASES.get(phase, [])

    result = run_remote_ingestion(
        catalog=catalog,
        mode=mode,
        download=download,
        ingest=ingest,
        max_items_per_source=max_items_per_source,
        budget_gb=budget_gb,
        resume=resume,
        reset_checkpoint=reset_checkpoint,
        adapter_filter=adapter_filter,
        full_source=full_source,
        target_collection_group=target_collection_group,
        quality_gate=quality_gate,
        update_mode=update_mode,
        dedupe=dedupe,
        importance_ranking=importance_ranking,
    )

    if phase is not None:
        phase_adapters = set(adapter_filter or [])
        if phase_adapters:
            print(f"\n[Phase {phase}] Target adapters: {sorted(phase_adapters)}")

    return result
