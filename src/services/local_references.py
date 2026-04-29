"""Ingest local project reference PDFs as non-authority commentary metadata."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY, LOCAL_REFERENCES_DIR
from src.services.legal_chunking import structured_legal_chunks


REFERENCE_TYPES = {
    "nlp project": "project_reference",
    "high": "source_map",
}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reference_doc_type(path: Path) -> str:
    lowered = path.stem.lower()
    for marker, doc_type in REFERENCE_TYPES.items():
        if marker in lowered:
            return doc_type
    return "project_reference"


def _extract_with_pypdf(path: Path) -> tuple[str, int, str]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = [(page.extract_text() or "") for page in reader.pages]
        return "\n\n".join(part for part in parts if part.strip()), len(reader.pages), "pypdf"
    except Exception as exc:
        return "", 0, f"pypdf_failed:{type(exc).__name__}"


def _extract_with_docling(path: Path) -> tuple[str, str]:
    try:
        from docling.document_converter import DocumentConverter

        result = DocumentConverter().convert(str(path))
        document = getattr(result, "document", None)
        if document is None:
            return "", "docling_empty"
        if hasattr(document, "export_to_markdown"):
            text = document.export_to_markdown()
        elif hasattr(document, "export_to_text"):
            text = document.export_to_text()
        else:
            text = str(document)
        return text.strip(), "docling"
    except Exception as exc:
        return "", f"docling_failed:{type(exc).__name__}"


def _extract_with_ocr(path: Path, *, max_pages: int = 3) -> tuple[str, str]:
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except Exception:
        return "", "ocr_unavailable"
    try:
        pdf = pdfium.PdfDocument(str(path))
        parts: list[str] = []
        for index in range(min(len(pdf), max_pages)):
            page = pdf[index]
            bitmap = page.render(scale=2).to_pil()
            parts.append(pytesseract.image_to_string(bitmap))
        text = "\n\n".join(part for part in parts if part.strip())
        return text.strip(), "ocr_tesseract"
    except Exception as exc:
        return "", f"ocr_failed:{type(exc).__name__}"


def extract_reference_text(path: str | Path, *, enable_ocr: bool = True) -> dict[str, Any]:
    pdf_path = Path(path)
    text, page_count, method = _extract_with_pypdf(pdf_path)
    ocr_status = "not_needed" if text.strip() else "not_run"
    if not text.strip():
        text, docling_status = _extract_with_docling(pdf_path)
        method = docling_status
        ocr_status = "not_needed" if text.strip() else "not_run"
    if enable_ocr and not text.strip():
        text, ocr_status = _extract_with_ocr(pdf_path)
        method = ocr_status
    return {
        "text": text.strip(),
        "page_count": page_count,
        "extraction_method": method,
        "ocr_status": ocr_status,
    }


def reference_chunks_for_file(path: str | Path, *, enable_ocr: bool = True) -> list[dict[str, Any]]:
    pdf_path = Path(path)
    checksum = _sha256_file(pdf_path)
    extracted = extract_reference_text(pdf_path, enable_ocr=enable_ocr)
    doc_type = _reference_doc_type(pdf_path)
    text = extracted["text"]
    if not text:
        text = (
            f"Project reference file: {pdf_path.name}. "
            f"Text extraction status: {extracted['extraction_method']}; OCR status: {extracted['ocr_status']}. "
            "This record is indexed for source discovery, project planning, and ingestion auditing only. "
            "It is not legal authority and must not support legal-merits claims."
        )
    base_metadata = {
        "source_name": pdf_path.name,
        "collection": COLLECTION_COMMENTARY,
        "jurisdiction": "project",
        "language": "en",
        "translation_status": "original",
        "doc_type": doc_type,
        "year": None,
        "article_number": None,
        "page": None,
        "citation": pdf_path.name,
        "parent_id": f"local_reference:{checksum[:16]}",
        "footnote_ids": [],
        "context_prefix": "",
        "license_note": "user-provided local project reference",
        "private_public": "project_reference",
        "source_id": f"local_reference:{checksum[:16]}",
        "source_url": str(pdf_path),
        "original_source_url": str(pdf_path),
        "source_format": "PDF",
        "not_legal_authority": True,
        "extraction_method": extracted["extraction_method"],
        "ocr_status": extracted["ocr_status"],
        "content_sha256": checksum,
    }
    chunks = structured_legal_chunks(
        text,
        base_metadata=base_metadata,
        doc_type=doc_type,
        source_type="project reference source map",
        max_words=700,
    )
    if not chunks:
        chunks = [{"text": text, "metadata": dict(base_metadata, chunk_index=0, structure="metadata_only")}]
    output: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks):
        metadata = dict(base_metadata)
        metadata.update(chunk.get("metadata") or {})
        metadata["chunk_index"] = idx
        seed = f"{checksum}:{doc_type}:{idx}"
        metadata["chunk_id"] = f"local_reference:{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:32]}"
        output.append({"text": chunk["text"], "metadata": metadata})
    return output


def ingest_local_references(files: list[str | Path], *, enable_ocr: bool = True, ingest: bool = True) -> dict[str, Any]:
    LOCAL_REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
    chunks: list[dict[str, Any]] = []
    file_results: list[dict[str, Any]] = []
    for item in files:
        path = Path(item)
        if not path.exists():
            file_results.append({"file": str(path), "status": "missing", "chunks": 0})
            continue
        file_chunks = reference_chunks_for_file(path, enable_ocr=enable_ocr)
        chunks.extend(file_chunks)
        meta = file_chunks[0]["metadata"] if file_chunks else {}
        file_results.append({
            "file": str(path),
            "status": "ok",
            "doc_type": meta.get("doc_type"),
            "chunks": len(file_chunks),
            "extraction_method": meta.get("extraction_method"),
            "ocr_status": meta.get("ocr_status"),
        })

    upserted = 0
    if ingest and chunks:
        from src.rag.vector_store import upsert_chunks

        upserted = upsert_chunks(COLLECTION_COMMENTARY, chunks, batch_size=8)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": file_results,
        "chunks": len(chunks),
        "upserted": upserted,
        "collection": COLLECTION_COMMENTARY,
    }
    manifest_dir = LOCAL_REFERENCES_DIR / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = manifest_dir / f"{timestamp}_local_references_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = manifest_dir / "latest_local_references_manifest.json"
    latest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(path)
    manifest["latest_manifest_path"] = str(latest)
    return manifest
