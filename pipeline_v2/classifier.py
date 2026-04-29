"""Deterministic classifier: mode + jurisdictions + doc type intent.

No LLM needed. Pattern-driven so it is predictable & explainable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Supported jurisdictions and their aliases (lowercase word boundaries).
_JUR_PATTERNS: list[tuple[str, list[str]]] = [
    ("US", [r"\bunited states\b", r"\bu\.?s\.?a?\b", r"\bamerican\b", r"\bus law\b"]),
    ("UK", [r"\bunited kingdom\b", r"\buk\b", r"\bbritish\b", r"\bengland\b", r"\bscotland\b"]),
    ("EU", [r"\beuropean union\b", r"\beu law\b", r"\bbrussels\b", r"\bgdpr\b"]),
    ("IN", [r"\bindia\b", r"\bindian\b", r"\bbharat\b", r"\bipc\b", r"\bbns\b"]),
    ("RU", [r"\brussia\b", r"\brussian\b", r"\brussian federation\b"]),
    ("IL", [r"\bisrael\b", r"\bisraeli\b"]),
    ("FR", [r"\bfrance\b", r"\bfrench\b"]),
    ("DE", [r"\bgermany\b", r"\bgerman\b"]),
    ("JP", [r"\bjapan\b", r"\bjapanese\b"]),
    ("CN", [r"\bchina\b", r"\bchinese\b"]),
    ("CA", [r"\bcanada\b", r"\bcanadian\b"]),
    ("AU", [r"\baustralia\b", r"\baustralian\b"]),
    ("AE", [r"\buae\b", r"\bunited arab emirates\b", r"\bdubai\b", r"\babu dhabi\b"]),
    ("SA", [r"\bsaudi arabia\b", r"\bsaudi\b"]),
    ("TR", [r"\bturkey\b", r"\bturkish\b"]),
    ("BR", [r"\bbrazil\b", r"\bbrazilian\b"]),
]

_TOURIST_RE = re.compile(
    r"\b(tourist|tourism|travel(?:ing|ling)?|visit|visa|passport|airport|customs|border|"
    r"driving licen[cs]e|international driving permit|embassy|consular|foreign national|"
    r"traveller|traveler)\b",
    re.IGNORECASE,
)
_CONFLICT_RE = re.compile(
    r"\b(conflict|supremac(?:y|ies)|which (?:law|treaty) (?:wins|prevails|is superior|is higher)|"
    r"international vs (?:local|domestic|national)|treaty vs (?:statute|law)|"
    r"override|preempt|supersede|hierarchy of laws|compare .* laws)\b",
    re.IGNORECASE,
)
_CASE_LAW_RE = re.compile(
    r"\b(case(?: law)?|judgment|judgement|precedent|court|v\.\s|ruling|decision|held that)\b",
    re.IGNORECASE,
)
_STATUTE_RE = re.compile(
    r"\b(statute|section|article|act|code|regulation|ordinance|provision|clause)\b",
    re.IGNORECASE,
)
_TREATY_RE = re.compile(
    r"\b(treaty|convention|protocol|covenant|charter|iccpr|icescr|un charter|vienna convention)\b",
    re.IGNORECASE,
)


@dataclass
class QueryAnalysis:
    mode: str  # "tourist" | "conflict" | "research"
    jurisdictions: list[str]  # ISO codes like ["US", "IN"]
    include_international: bool
    doc_types: list[str]  # subset of ["case_law", "statute", "treaty", "commentary"]
    raw_query: str

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "jurisdictions": self.jurisdictions,
            "include_international": self.include_international,
            "doc_types": self.doc_types,
        }


def _detect_jurisdictions(q: str) -> list[str]:
    found: list[str] = []
    for iso, patterns in _JUR_PATTERNS:
        if any(re.search(p, q, flags=re.IGNORECASE) for p in patterns):
            if iso not in found:
                found.append(iso)
    return found


def _detect_doc_types(q: str) -> list[str]:
    types: list[str] = []
    if _CASE_LAW_RE.search(q):
        types.append("case_law")
    if _STATUTE_RE.search(q):
        types.append("statute")
    if _TREATY_RE.search(q):
        types.append("treaty")
    if not types:
        types = ["treaty", "statute", "case_law", "commentary"]
    return types


def analyze_query(query: str, forced_mode: str | None = None) -> QueryAnalysis:
    q = (query or "").strip()
    jurisdictions = _detect_jurisdictions(q)

    if forced_mode in {"tourist", "conflict", "research"}:
        mode = forced_mode
    elif _TOURIST_RE.search(q):
        mode = "tourist"
    elif _CONFLICT_RE.search(q) or len(jurisdictions) >= 2:
        mode = "conflict"
    else:
        mode = "research"

    include_international = True
    doc_types = _detect_doc_types(q)

    return QueryAnalysis(
        mode=mode,
        jurisdictions=jurisdictions,
        include_international=include_international,
        doc_types=doc_types,
        raw_query=q,
    )
