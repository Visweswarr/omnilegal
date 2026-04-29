"""Structure-aware chunking helpers for legal corpora."""
from __future__ import annotations

import re
from typing import Any


def _normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _chunk_metadata(base: dict[str, Any], idx: int, **extra: Any) -> dict[str, Any]:
    data = dict(base)
    data.update(extra)
    data["chunk_index"] = idx
    return data


def _word_chunks(text: str, base: dict[str, Any], *, max_words: int, structure: str) -> list[dict[str, Any]]:
    words = text.split()
    if not words:
        return []
    step = max(1, max_words - 100)
    chunks: list[dict[str, Any]] = []
    for idx, start in enumerate(range(0, len(words), step)):
        body = " ".join(words[start:start + max_words]).strip()
        if body:
            chunks.append({
                "text": body,
                "metadata": _chunk_metadata(base, idx, structure=structure),
            })
    return chunks


def _bounded_piece_chunks(
    pieces: list[tuple[str, dict[str, Any]]],
    base: dict[str, Any],
    *,
    max_words: int,
    structure: str,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for heading, meta in pieces:
        text = heading.strip()
        if not text:
            continue
        if _word_count(text) <= max_words:
            idx = len(chunks)
            chunks.append({
                "text": text,
                "metadata": _chunk_metadata(base, idx, structure=structure, **meta),
            })
            continue
        for sub in _word_chunks(text, {**base, **meta}, max_words=max_words, structure=structure):
            sub["metadata"]["chunk_index"] = len(chunks)
            chunks.append(sub)
    return chunks


def _split_by_heading(text: str, pattern: str) -> list[tuple[str, str]]:
    matches = list(re.finditer(pattern, text, flags=re.IGNORECASE | re.MULTILINE))
    if not matches:
        return []
    pieces: list[tuple[str, str]] = []
    if matches[0].start() > 0:
        prefix = text[:matches[0].start()].strip()
        if prefix:
            pieces.append(("preamble", prefix))
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        heading = match.group(1).strip()
        body = text[match.start():end].strip()
        pieces.append((heading, body))
    return pieces


def _treaty_chunks(text: str, base: dict[str, Any], *, max_words: int) -> list[dict[str, Any]]:
    pieces = _split_by_heading(text, r"^\s*(Article\s+[0-9A-Za-z().-]+[^\n]*)")
    if not pieces:
        return []
    structured: list[tuple[str, dict[str, Any]]] = []
    for heading, body in pieces:
        article = "preamble"
        if heading.lower() != "preamble":
            match = re.search(r"Article\s+([0-9A-Za-z().-]+)", heading, flags=re.IGNORECASE)
            article = match.group(1) if match else heading
        structured.append((body, {
            "article_number": article,
            "hierarchy_path": heading,
            "citable_unit": heading,
        }))
    return _bounded_piece_chunks(structured, base, max_words=max_words, structure="treaty_article")


def _statute_chunks(text: str, base: dict[str, Any], *, max_words: int) -> list[dict[str, Any]]:
    section_pattern = r"^\s*((?:Title|Chapter|Part|Section|Sec\.|§)\s+[A-Za-z0-9_.:-]+[^\n]*)"
    pieces = _split_by_heading(text, section_pattern)
    if not pieces:
        return []
    breadcrumb: list[str] = []
    structured: list[tuple[str, dict[str, Any]]] = []
    for heading, body in pieces:
        lower = heading.lower()
        if lower.startswith(("title ", "chapter ", "part ")):
            depth = 1 if lower.startswith("title ") else 2 if lower.startswith("chapter ") else 3
            breadcrumb = breadcrumb[: depth - 1] + [heading]
        section_id = heading
        path = " > ".join(breadcrumb + ([heading] if heading not in breadcrumb else []))
        structured.append((body, {
            "section_id": section_id,
            "hierarchy_path": path or heading,
            "citable_unit": heading,
        }))
    return _bounded_piece_chunks(structured, base, max_words=max_words, structure="statute_section")


def _case_chunks(text: str, base: dict[str, Any], *, max_words: int) -> list[dict[str, Any]]:
    para_pattern = re.compile(r"^\s*(?:\[(\d+)\]|\((\d+)\)|(\d+)\.)\s+(.*)", re.MULTILINE)
    matches = list(para_pattern.finditer(text))
    if not matches:
        return []
    paragraphs: list[tuple[int, str]] = []
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        num = int(next(group for group in match.groups()[:3] if group))
        paragraphs.append((num, text[match.start():end].strip()))

    chunks: list[dict[str, Any]] = []
    group: list[tuple[int, str]] = []
    words = 0
    for para in paragraphs:
        para_words = _word_count(para[1])
        if group and (len(group) >= 5 or words + para_words > max_words):
            start, end = group[0][0], group[-1][0]
            chunks.append({
                "text": "\n\n".join(p[1] for p in group),
                "metadata": _chunk_metadata(base, len(chunks), structure="case_paragraphs", paragraph_start=start, paragraph_end=end),
            })
            group, words = [], 0
        group.append(para)
        words += para_words
    if group:
        start, end = group[0][0], group[-1][0]
        chunks.append({
            "text": "\n\n".join(p[1] for p in group),
            "metadata": _chunk_metadata(base, len(chunks), structure="case_paragraphs", paragraph_start=start, paragraph_end=end),
        })
    return chunks


def _commentary_chunks(text: str, base: dict[str, Any], *, max_words: int) -> list[dict[str, Any]]:
    lines = text.splitlines()
    pieces: list[tuple[str, dict[str, Any]]] = []
    current_heading = "untitled"
    current: list[str] = []
    heading_re = re.compile(r"^\s*(#{1,6}\s+.+|[A-Z][A-Za-z0-9 ,;:'()/-]{3,100}|[0-9]+(?:\.[0-9]+)*\s+.+)\s*$")
    for line in lines:
        stripped = line.strip()
        if stripped and heading_re.match(stripped) and _word_count(stripped) <= 14:
            if current:
                pieces.append(("\n".join(current).strip(), {"heading": current_heading, "parent_id": current_heading}))
            current_heading = stripped.lstrip("# ").strip()
            current = [stripped]
        else:
            current.append(line)
    if current:
        pieces.append(("\n".join(current).strip(), {"heading": current_heading, "parent_id": current_heading}))
    if not pieces:
        return []
    return _bounded_piece_chunks(pieces, base, max_words=max_words, structure="heading")


def _contract_chunks(text: str, base: dict[str, Any], *, max_words: int) -> list[dict[str, Any]]:
    pieces = _split_by_heading(text, r"^\s*((?:Clause|Section|Article)\s+[0-9A-Za-z().-]+[^\n]*)")
    if not pieces:
        return []
    structured = [(body, {"clause_id": heading, "hierarchy_path": heading, "citable_unit": heading}) for heading, body in pieces]
    return _bounded_piece_chunks(structured, base, max_words=max_words, structure="contract_clause")


def structured_legal_chunks(
    text: str,
    *,
    base_metadata: dict[str, Any] | None = None,
    doc_type: str = "",
    source_type: str = "",
    max_words: int = 700,
) -> list[dict[str, Any]]:
    """Return chunks preserving legal structure where recognizable."""
    normalized = _normalize(text)
    if not normalized:
        return []
    base = dict(base_metadata or {})
    probe = f"{doc_type} {source_type} {normalized[:1000]}".lower()

    ordered_strategies = []
    if "treaty" in probe or "convention" in probe:
        ordered_strategies.append(_treaty_chunks)
    if any(term in probe for term in ["statute", "regulation", "code", "legislation", "cfr", "act "]):
        ordered_strategies.append(_statute_chunks)
    if any(term in probe for term in ["case", "judgment", "opinion", "court"]):
        ordered_strategies.append(_case_chunks)
    if any(term in probe for term in ["contract", "edgar", "cuad", "agreement"]):
        ordered_strategies.append(_contract_chunks)
    if any(term in probe for term in ["commentary", "source_map", "project_reference", "source map"]):
        ordered_strategies.append(_commentary_chunks)

    for strategy in ordered_strategies + [_treaty_chunks, _statute_chunks, _case_chunks, _contract_chunks, _commentary_chunks]:
        chunks = strategy(normalized, base, max_words=max_words)
        if chunks:
            return chunks
    return _word_chunks(normalized, base, max_words=max_words, structure="fixed_window")
