"""Citation verifier v2 — deterministic + API-backed verification.

Pipeline:
  1. Regex extraction of citation-like strings from draft text
  2. Cross-reference against retrieved passages
  3. CourtListener API lookup for US citations (if token available)
  4. Grade assignment: verified / unverified / fabricated / not_found
"""
from __future__ import annotations

import logging
import re
from typing import Any

import requests as http_requests

from src.config import COURTLISTENER_TOKEN
from src.schemas import CitationGrade

try:
    from eyecite import get_citations
except ImportError:
    get_citations = None

logger = logging.getLogger(__name__)

# ── Citation extraction patterns ──────────────────────────────────────────

# Matches patterns like "[1]", "[2]", etc.
_MARKER_PATTERN = re.compile(r"\[(\d+)\]")

# US reporter citations: "123 U.S. 456", "456 F.2d 789", etc.
_US_REPORTER = re.compile(
    r"\b(\d{1,4})\s+"
    r"(U\.?S\.?|S\.?\s*Ct\.?|L\.?\s*Ed\.?|F\.?\s*(?:2d|3d|4th)?|"
    r"F\.?\s*Supp\.?\s*(?:2d|3d)?|"
    r"S\.?W\.?\s*(?:2d|3d)?|N\.?E\.?\s*(?:2d|3d)?|"
    r"N\.?W\.?\s*(?:2d)?|S\.?E\.?\s*(?:2d)?|"
    r"A\.?\s*(?:2d|3d)?|P\.?\s*(?:2d|3d)?)"
    r"\s+(\d{1,4})\b"
)

# Case name pattern: "Party v. Party" or "Party vs. Party"
_CASE_NAME = re.compile(r"([A-Z][a-zA-Z\s]+)\s+v\.?\s+([A-Z][a-zA-Z\s]+)")

# Statute reference: "Section 123", "Article 5", "§ 123"
_STATUTE_REF = re.compile(r"(?:Section|Art(?:icle)?\.?|§)\s*(\d+[A-Za-z]?(?:\(\d+\))?)")


def extract_citations(text: str) -> list[dict[str, str]]:
    """Extract all citation-like strings from text."""
    citations: list[dict[str, str]] = []
    seen: set[str] = set()

    # Numeric markers [1], [2], etc.
    for m in _MARKER_PATTERN.finditer(text):
        key = f"marker:{m.group(1)}"
        if key not in seen:
            seen.add(key)
            citations.append({"type": "marker", "text": m.group(0), "number": m.group(1)})

    # US reporter citations
    if get_citations:
        try:
            cites = get_citations(text)
            for c in cites:
                full = c.matched_text().strip()
                if full not in seen:
                    seen.add(full)
                    citations.append({"type": "us_reporter", "text": full})
        except Exception as e:
            logger.debug(f"Eyecite extraction failed: {e}")
            # Fallback
            for m in _US_REPORTER.finditer(text):
                full = m.group(0).strip()
                if full not in seen:
                    seen.add(full)
                    citations.append({"type": "us_reporter", "text": full})
    else:
        for m in _US_REPORTER.finditer(text):
            full = m.group(0).strip()
            if full not in seen:
                seen.add(full)
                citations.append({"type": "us_reporter", "text": full})

    # Case names
    for m in _CASE_NAME.finditer(text):
        full = m.group(0).strip()
        if full not in seen and len(full) < 120:
            seen.add(full)
            citations.append({"type": "case_name", "text": full})

    return citations


def _marker_in_retrieved(marker_num: str, retrieved: list[dict[str, Any]]) -> bool:
    """Check if marker [N] corresponds to a retrieved passage index."""
    try:
        idx = int(marker_num) - 1
        return 0 <= idx < len(retrieved)
    except (ValueError, TypeError):
        return False


def _text_in_retrieved(citation_text: str, retrieved: list[dict[str, Any]]) -> bool:
    """Check if a citation text appears in any retrieved passage."""
    lower = citation_text.lower()
    for p in retrieved:
        source_text = " ".join([
            (p.get("text") or "").lower(),
            ((p.get("metadata") or {}).get("source_name") or "").lower(),
            ((p.get("metadata") or {}).get("citation") or "").lower(),
        ])
        if lower in source_text:
            return True
    return False


def _courtlistener_verify(citation_text: str) -> bool:
    """Verify a US citation via CourtListener API."""
    if not COURTLISTENER_TOKEN:
        return False
    try:
        resp = http_requests.get(
            "https://www.courtlistener.com/api/rest/v4/search/",
            params={"q": f'cite:"{citation_text}"', "type": "o"},
            headers={"Authorization": f"Token {COURTLISTENER_TOKEN}"},
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return (data.get("count") or 0) > 0
    except Exception as exc:
        logger.debug("CourtListener lookup failed for %s: %s", citation_text, exc)
    return False


def verify_citations(
    draft: str,
    retrieved: list[dict[str, Any]],
    *,
    use_api: bool = True,
) -> list[CitationGrade]:
    """Verify all citations in a draft against retrieved passages and APIs."""
    citations = extract_citations(draft)
    grades: list[CitationGrade] = []

    for cit in citations:
        cit_type = cit["type"]
        cit_text = cit["text"]

        if cit_type == "marker":
            # Check if marker maps to a retrieved passage
            if _marker_in_retrieved(cit.get("number", ""), retrieved):
                grades.append(CitationGrade(
                    citation_text=cit_text,
                    status="verified",
                    source_excerpt=f"Maps to retrieved passage #{cit.get('number')}",
                ))
            else:
                grades.append(CitationGrade(
                    citation_text=cit_text,
                    status="fabricated",
                    source_excerpt="No matching retrieved passage",
                ))
        elif cit_type == "us_reporter":
            in_sources = _text_in_retrieved(cit_text, retrieved)
            api_verified = False
            if use_api and not in_sources:
                api_verified = _courtlistener_verify(cit_text)
            if in_sources:
                grades.append(CitationGrade(
                    citation_text=cit_text, status="verified",
                    reporter_match=True, source_excerpt="Found in retrieved sources",
                ))
            elif api_verified:
                grades.append(CitationGrade(
                    citation_text=cit_text, status="verified",
                    reporter_match=True, api_verified=True,
                    source_excerpt="Verified via CourtListener API",
                ))
            else:
                grades.append(CitationGrade(
                    citation_text=cit_text, status="unverified",
                    source_excerpt="Not in sources and not API-verified",
                ))
        elif cit_type == "case_name":
            if _text_in_retrieved(cit_text, retrieved):
                grades.append(CitationGrade(
                    citation_text=cit_text, status="verified",
                    source_excerpt="Found in retrieved sources",
                ))
            else:
                grades.append(CitationGrade(
                    citation_text=cit_text, status="unverified",
                    source_excerpt="Case name not in retrieved sources",
                ))

    return grades


def strip_fabricated_citations(draft: str, grades: list[CitationGrade]) -> str:
    """Remove fabricated citations from draft text."""
    fabricated = {g.citation_text for g in grades if g.status == "fabricated"}
    result = draft
    for cit in fabricated:
        result = result.replace(cit, "")
    return result


def strip_unverified_citations(draft: str, grades: list[CitationGrade]) -> str:
    """Remove every citation that was not verified."""
    bad = {g.citation_text for g in grades if g.status != "verified"}
    result = draft
    for cit in bad:
        result = result.replace(cit, "")
    return result
