"""Lightweight CRAG-style citation verification.

Given a generated answer with `[S#]` citation markers and the list of
retrieved passages, verifies that each cited claim has supporting language
inside the marked passage. We use an n-gram overlap heuristic that's cheap
enough to run in-line on every answer; for high-stakes answers the same
service can be re-invoked with an LLM verifier.

Status grades:
    "verified"   — the cited passage contains substantive overlap with the
                   sentence claiming it.
    "partial"    — some overlap, but weak (suggest reviewer attention).
    "unverified" — citation marker points to a passage that doesn't seem to
                   support the claim.
    "not_found"  — citation marker has no matching passage at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class VerifiedClaim:
    sentence: str
    citations: list[str]
    status: str
    overlap_score: float
    supporting_excerpt: str = ""


_CITATION_RE = re.compile(r"\[S(\d+(?:\s*,\s*S?\d+)*)\]", flags=re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\u201C\u2018\(\[])")


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(tok) > 3}


def _ngram(text: str, n: int = 4) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1) if len(tokens) >= n}


def _best_excerpt(claim: str, passage_text: str, max_chars: int = 220) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(passage_text.split()))
    claim_tokens = _tokenize(claim)
    if not claim_tokens or not sentences:
        return passage_text[:max_chars]
    scored: list[tuple[int, str]] = []
    for sent in sentences:
        score = len(_tokenize(sent) & claim_tokens)
        scored.append((score, sent))
    scored.sort(key=lambda item: item[0], reverse=True)
    excerpt = scored[0][1] if scored and scored[0][0] > 0 else passage_text
    return excerpt[:max_chars]


def _split_sentences(text: str) -> list[str]:
    if not text or not text.strip():
        return []
    cleaned = " ".join(text.split())
    sentences = _SENTENCE_SPLIT.split(cleaned)
    return [s.strip() for s in sentences if s.strip()]


def _expand_marker_group(raw: str) -> list[str]:
    """Turn '1' or 'S1, 2, S3' into ['S1','S2','S3']."""
    pieces = re.split(r"\s*,\s*", raw)
    out: list[str] = []
    for piece in pieces:
        digits = re.search(r"\d+", piece)
        if digits:
            out.append(f"S{digits.group(0)}")
    return out


def verify_answer_citations(
    answer_text: str,
    retrieved_passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Verify each [S#] marker in the answer.

    Returns: {
        "verified_claims": list[dict],
        "summary": {"verified": int, "partial": int, "unverified": int,
                    "not_found": int, "total_claims": int},
        "overall_grade": "high|medium|low",
    }
    """
    indexed: dict[str, str] = {}
    for idx, passage in enumerate(retrieved_passages or [], start=1):
        text = passage.get("text") or passage.get("content") or ""
        meta = passage.get("metadata") or {}
        excerpt = passage.get("excerpt") or text
        # Collapse the passage into a small searchable string
        indexed[f"S{idx}"] = excerpt or text or meta.get("source_name", "")

    claims: list[VerifiedClaim] = []
    for sentence in _split_sentences(answer_text):
        markers = []
        for match in _CITATION_RE.finditer(sentence):
            markers.extend(_expand_marker_group(match.group(1)))
        if not markers:
            continue
        clean_sentence = _CITATION_RE.sub("", sentence).strip()
        clean_sentence = re.sub(r"\s+", " ", clean_sentence)

        per_marker_scores: list[tuple[str, float, str]] = []
        for marker in markers:
            passage_text = indexed.get(marker, "")
            if not passage_text:
                per_marker_scores.append((marker, -1.0, ""))
                continue
            overlap = _ngram(clean_sentence, n=3) & _ngram(passage_text, n=3)
            base_tokens_overlap = len(_tokenize(clean_sentence) & _tokenize(passage_text))
            score = (len(overlap) * 2.0) + (base_tokens_overlap * 0.4)
            per_marker_scores.append((marker, score, passage_text))

        if not per_marker_scores:
            continue

        not_found = all(score < 0 for _, score, _ in per_marker_scores)
        if not_found:
            status = "not_found"
            best_text = ""
            best_score = 0.0
        else:
            best = max(per_marker_scores, key=lambda item: item[1])
            best_score = max(0.0, best[1])
            best_text = best[2]
            if best_score >= 4:
                status = "verified"
            elif best_score >= 1.5:
                status = "partial"
            else:
                status = "unverified"
        claims.append(
            VerifiedClaim(
                sentence=clean_sentence,
                citations=[m for m, _, _ in per_marker_scores],
                status=status,
                overlap_score=round(best_score, 2),
                supporting_excerpt=_best_excerpt(clean_sentence, best_text) if best_text else "",
            )
        )

    summary = {"verified": 0, "partial": 0, "unverified": 0, "not_found": 0}
    for claim in claims:
        summary[claim.status] = summary.get(claim.status, 0) + 1
    summary["total_claims"] = len(claims)

    if not claims:
        overall = "no_claims_with_citations"
    elif summary["verified"] / max(1, len(claims)) >= 0.7:
        overall = "high"
    elif summary["verified"] + summary["partial"] >= len(claims) * 0.6:
        overall = "medium"
    else:
        overall = "low"

    return {
        "verified_claims": [
            {
                "sentence": c.sentence,
                "citations": c.citations,
                "status": c.status,
                "overlap_score": c.overlap_score,
                "supporting_excerpt": c.supporting_excerpt,
            }
            for c in claims
        ],
        "summary": summary,
        "overall_grade": overall,
    }


def render_verification_markdown(verification: dict[str, Any]) -> str:
    """Render a compact Markdown audit block for the Chainlit UI."""
    summary = verification.get("summary") or {}
    overall = verification.get("overall_grade", "—")
    icon = {
        "high": "🟢",
        "medium": "🟡",
        "low": "🔴",
        "no_claims_with_citations": "⚪",
    }.get(overall, "⚪")
    bits = [
        f"**Citation audit**: {icon} {overall.replace('_', ' ').title()} "
        f"· verified {summary.get('verified', 0)} "
        f"· partial {summary.get('partial', 0)} "
        f"· unverified {summary.get('unverified', 0)} "
        f"· not-found {summary.get('not_found', 0)} "
        f"· total claims {summary.get('total_claims', 0)}",
    ]
    flagged = [
        c for c in verification.get("verified_claims", [])
        if c.get("status") in {"unverified", "not_found"}
    ]
    if flagged:
        bits.append("\n_Flagged claims_:")
        for c in flagged[:4]:
            cits = ", ".join(c.get("citations") or [])
            bits.append(f"- `{c.get('status')}` {cits}: {c.get('sentence')[:200]}")
    return "\n".join(bits)
