"""Citation verifier — parses [S#] tags, verifies each claim is grounded.

A sentence is "supported" when:
  - it contains at least one [S#] tag that refers to an actual retrieved source,
  - OR the sentence is a heading / bullet marker / insufficient-evidence note.

Unsupported claims are annotated with a ⚠ UNSUPPORTED marker so the user sees
exactly what is not grounded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CITATION_RE = re.compile(r"\[\s*(S\d+(?:\s*,\s*S\d+)*)\s*\]")
_INSUFFICIENT_RE = re.compile(r"^\s*insufficient evidence[:\-]", re.IGNORECASE)
_HEADING_RE = re.compile(r"^\s*(?:#+|\*\*[^*]+\*\*\s*:?\s*)\s*$")


@dataclass
class VerificationReport:
    answer: str  # possibly annotated with ⚠ markers
    total_sentences: int
    cited_sentences: int
    uncited_sentences: int
    invalid_citations: list[str]
    grounded_ratio: float
    has_insufficient_flag: bool


def _split_sentences(text: str) -> list[str]:
    # Split on sentence boundaries but preserve bullets / markdown lines.
    out: list[str] = []
    for line in (text or "").splitlines():
        if not line.strip():
            out.append(line)
            continue
        stripped = line.lstrip("-*•> ").strip()
        # Numbered list "1. something" — treat as one unit
        is_numbered = bool(re.match(r"^\s*\d+[.)]\s+\S", line))
        if (
            line.lstrip().startswith(("-", "*", "•", ">", "#"))
            or _HEADING_RE.match(line)
            or is_numbered
        ):
            out.append(line)
            continue
        # Otherwise, split into sentences; avoid splitting right after a digit+period.
        chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z(\"'])", stripped)
        prefix_ws = line[: len(line) - len(line.lstrip())]
        for i, ch in enumerate(chunks):
            if not ch.strip():
                continue
            out.append((prefix_ws if i == 0 else "") + ch)
    return out


def verify(answer: str, sources: list[dict]) -> VerificationReport:
    valid_labels = {s["label"] for s in sources}
    sentences = _split_sentences(answer)

    # If model emitted an "INSUFFICIENT EVIDENCE" block, treat as honest abstention.
    insufficient = any(_INSUFFICIENT_RE.match(s) for s in sentences if s.strip())
    if insufficient:
        return VerificationReport(
            answer=answer,
            total_sentences=len(sentences),
            cited_sentences=0,
            uncited_sentences=0,
            invalid_citations=[],
            grounded_ratio=1.0,
            has_insufficient_flag=True,
        )

    invalid_citations: list[str] = []
    cited = 0
    uncited = 0
    total_claims = 0
    annotated_lines: list[str] = []

    for line in sentences:
        stripped = line.strip()
        if not stripped:
            annotated_lines.append(line)
            continue
        if stripped.startswith(("#", "**", "_")) and stripped.endswith(("#", "**", "_", ":")):
            annotated_lines.append(line)
            continue
        if stripped.startswith(("-", "*", "•", ">")) and len(stripped) < 3:
            annotated_lines.append(line)
            continue
        # Count this as a claim.
        matches = _CITATION_RE.findall(line)
        if matches:
            labels = []
            for m in matches:
                labels.extend(tok.strip() for tok in m.split(","))
            bad = [lbl for lbl in labels if lbl not in valid_labels]
            if bad:
                invalid_citations.extend(bad)
                annotated_lines.append(
                    f"{line}  ⚠ CITATION NOT IN SOURCES: {', '.join(bad)}"
                )
                uncited += 1
            else:
                cited += 1
                annotated_lines.append(line)
            total_claims += 1
        else:
            # Short bullet titles or lead-in labels get a pass if they end with ":"
            if stripped.endswith(":") and len(stripped) < 80:
                annotated_lines.append(line)
                continue
            uncited += 1
            total_claims += 1
            annotated_lines.append(f"{line}  ⚠ UNSUPPORTED — no source cited")

    ratio = (cited / total_claims) if total_claims else 1.0
    return VerificationReport(
        answer="\n".join(annotated_lines),
        total_sentences=len(sentences),
        cited_sentences=cited,
        uncited_sentences=uncited,
        invalid_citations=invalid_citations,
        grounded_ratio=ratio,
        has_insufficient_flag=False,
    )
