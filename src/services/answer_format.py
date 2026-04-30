from __future__ import annotations

import re
from typing import Any


SECTION_ORDER = [
    "sourced_authority",
    "general_principles",
    "practical_steps",
    "disclaimer",
]

LONG_SECTION_ORDER = [
    "bottom_line",
    "legal_issue",
    "international_law",
    "malcolm_shaw",
    "judgments_precedents",
    "local_law",
    "conflict_check",
    "conclusion",
    "sources",
]

SECTION_TITLES = {
    "sourced_authority": "Sourced Authority",
    "general_principles": "General Principles / Common Practice",
    "practical_steps": "Practical Steps",
    "disclaimer": "Disclaimer",
}

LONG_SECTION_TITLES = {
    "bottom_line": "Bottom Line",
    "legal_issue": "Legal Issue",
    "international_law": "International Law",
    "malcolm_shaw": "Malcolm Shaw",
    "judgments_precedents": "Judgments / Precedents",
    "local_law": "Local Law",
    "conflict_check": "Conflict Check",
    "conclusion": "Conclusion",
    "sources": "Sources",
}

_SHORT_PATTERNS = [
    r"\bbrief\b",
    r"\bsummary\b",
    r"\bone[- ]line\b",
    r"\bshort answer\b",
]
_LONG_PATTERNS = [
    r"\bdetailed\b",
    r"\blong answer\b",
    r"\bin detail\b",
    r"\bwith legal reasoning\b",
]


def detect_answer_style(text: str) -> str | None:
    lowered = str(text or "").lower()
    if any(re.search(pattern, lowered) for pattern in _SHORT_PATTERNS):
        return "short"
    if any(re.search(pattern, lowered) for pattern in _LONG_PATTERNS):
        return "long"
    return None


def _canonical_section_key(heading: str) -> str | None:
    lowered = re.sub(r"\s+", " ", heading.strip().lower())
    if lowered == "bottom line":
        return "bottom_line"
    if lowered == "legal issue":
        return "legal_issue"
    if lowered == "international law":
        return "international_law"
    if lowered == "malcolm shaw":
        return "malcolm_shaw"
    if "judgments" in lowered or "judgements" in lowered or "precedents" in lowered:
        return "judgments_precedents"
    if lowered == "local law":
        return "local_law"
    if lowered == "conflict check":
        return "conflict_check"
    if lowered == "conclusion":
        return "conclusion"
    if lowered == "sources":
        return "sources"
    if "sourced authority" in lowered or lowered == "authority" or lowered == "relevant law":
        return "sourced_authority"
    if "general principles" in lowered or "common practice" in lowered or "general guidance" in lowered:
        return "general_principles"
    if "practical steps" in lowered or "next steps" in lowered or "likely procedure" in lowered:
        return "practical_steps"
    if "disclaimer" in lowered:
        return "disclaimer"
    return None


def split_answer_sections(text: str) -> dict[str, str]:
    sections = {key: "" for key in [*SECTION_ORDER, *LONG_SECTION_ORDER]}
    current_key: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer, current_key
        if current_key is None:
            return
        body = "\n".join(buffer).strip()
        if body:
            sections[current_key] = body
        buffer = []

    for line in str(text or "").splitlines():
        match = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", line)
        if match:
            next_key = _canonical_section_key(match.group(1))
            if next_key:
                flush()
                current_key = next_key
                continue
        buffer.append(line)
    flush()

    if not any(sections.values()):
        body = str(text or "").strip()
        if re.search(r"\[\d+\]", body):
            sections["sourced_authority"] = body
        else:
            sections["general_principles"] = body
    return sections


def format_answer_sections(sections: dict[str, str]) -> str:
    if any(str((sections or {}).get(key) or "").strip() for key in LONG_SECTION_ORDER):
        parts: list[str] = []
        for key in LONG_SECTION_ORDER:
            body = str((sections or {}).get(key) or "").strip()
            if body or key != "sources":
                parts.append(f"## {LONG_SECTION_TITLES[key]}\n{body}".rstrip())
        return "\n\n".join(parts).strip()

    parts: list[str] = []
    for key in SECTION_ORDER:
        body = str((sections or {}).get(key) or "").strip()
        parts.append(f"## {SECTION_TITLES[key]}\n{body}".rstrip())
    return "\n\n".join(parts).strip()


def sentence_chunks(text: str) -> list[str]:
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return []
    pattern = re.compile(r".+?(?:[.!?](?:\s*\[\d+\])?)(?=\s+(?:[A-Z#]|$)|$)|.+$")
    return [match.group(0).strip() for match in pattern.finditer(cleaned) if match.group(0).strip()]


def missing_citation_sentences(text: str) -> list[str]:
    missing: list[str] = []
    for sentence in sentence_chunks(text):
        if len(sentence) < 25:
            continue
        if sentence.startswith(">"):
            continue
        if "INSUFFICIENT EVIDENCE" in sentence.upper():
            continue
        if re.search(r"\[[0-9]+\]", sentence):
            continue
        missing.append(sentence)
    return missing
