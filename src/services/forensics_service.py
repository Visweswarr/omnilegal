"""OmniLegal Citation Forensics service.

Takes a chunk of legal text (potentially output from another LLM such as
ChatGPT) and verifies every citation against our grounded corpus.

For each detected citation we attempt to:
  1. extract the citation text (statute / case / treaty / article)
  2. retrieve the closest passage from our 22 collections
  3. compute n-gram overlap between the surrounding sentence and the
     retrieved passage
  4. label as ``verified | partial | suspicious | hallucinated | not_found``

We also produce an annotated rendering of the original text where each
sentence is wrapped with its verification status so the React client can
highlight in red / green / amber.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.forensics")


# Citation patterns we recognise. Order matters — most-specific first so the
# longest match wins.
_CITATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("us_case",        re.compile(r"\b\d{1,3}\s+U\.?S\.?\s+\d{1,4}\b")),
    ("us_code",        re.compile(r"\b\d{1,2}\s+U\.?S\.?C\.?\s*§+\s*\d+(?:\([a-z0-9]+\))*\b")),
    ("uk_case",        re.compile(r"\[\d{4}\]\s+[A-Z]{1,5}(?:\s\d+)?\s+\d+\b")),
    ("ecHR",           re.compile(r"\b\d+\s+E\.?H\.?R\.?R\.?\s+\d+\b")),
    ("indian_section", re.compile(r"\bSection\s+\d+[A-Za-z]?(?:\s+of\s+the\s+[A-Z][\w\s]+(?:Act|Code))?", re.IGNORECASE)),
    ("treaty_article", re.compile(r"\bArticle\s+\d+(?:\s*\([A-Za-z0-9]+\))?\s+of\s+the\s+[A-Z][\w\s]+", re.IGNORECASE)),
    ("treaty_short",   re.compile(r"\bArt(?:icle)?\.?\s+\d+(?:\s*\([A-Za-z0-9]+\))?\b", re.IGNORECASE)),
    ("constitution",   re.compile(r"\bConstitution(?:al)?\s+(?:Article|Amendment)\s+\d+\b", re.IGNORECASE)),
    ("named_case",     re.compile(r"\b[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*\s+v\.?\s+[A-Z][A-Za-z']+(?:\s+[A-Z][A-Za-z']+)*", )),
]


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"\u201C\u2018\(\[])")

# Legal abbreviations that contain a period and must NOT be treated as a
# sentence boundary. The string ``v.`` in particular shows up in literally
# every case citation. We replace each with a sentinel before splitting and
# restore it afterwards.
_LEGAL_ABBREVIATIONS = [
    "v.", "vs.", "Inc.", "Ltd.", "Co.", "Corp.", "Bros.", "Cir.", "Fed.",
    "U.S.", "U.S.C.", "U.K.", "Art.", "Sec.", "No.", "St.", "Ct.", "App.",
    "Ass'n", "Mr.", "Mrs.", "Ms.", "Dr.", "Prof.", "Hon.", "Jr.", "Sr.",
]
_ABBR_SENTINEL = {abbr: f"<<<ABBR{i}>>>" for i, abbr in enumerate(_LEGAL_ABBREVIATIONS)}


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(tok) > 3}


def _ngram(text: str, n: int = 4) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(tokens[i : i + n]) for i in range(len(tokens) - n + 1) if len(tokens) >= n}


def _split_sentences(text: str) -> list[tuple[int, int, str]]:
    if not text or not text.strip():
        return []
    out: list[tuple[int, int, str]] = []
    cursor = 0
    cleaned = text.replace("\r", "")
    # Pre-mask legal abbreviations so periods inside them don't trigger splits.
    masked = cleaned
    for abbr, sentinel in _ABBR_SENTINEL.items():
        masked = masked.replace(abbr, sentinel)
    for chunk in _SENTENCE_SPLIT.split(masked):
        # Restore abbreviations
        for abbr, sentinel in _ABBR_SENTINEL.items():
            chunk = chunk.replace(sentinel, abbr)
        chunk = chunk.strip()
        if not chunk:
            continue
        idx = text.find(chunk, cursor)
        if idx == -1:
            idx = cursor
        out.append((idx, idx + len(chunk), chunk))
        cursor = idx + len(chunk)
    return out


def _extract_citations_from_sentence(sentence: str) -> list[dict[str, Any]]:
    cites: list[dict[str, Any]] = []
    for kind, pat in _CITATION_PATTERNS:
        for match in pat.finditer(sentence):
            cites.append({
                "kind": kind,
                "text": match.group(0),
                "start": match.start(),
                "end": match.end(),
            })
    # Dedupe overlapping matches — keep the longest span at each position.
    cites.sort(key=lambda c: (c["start"], -(c["end"] - c["start"])))
    deduped: list[dict[str, Any]] = []
    last_end = -1
    for c in cites:
        if c["start"] >= last_end:
            deduped.append(c)
            last_end = c["end"]
    return deduped


def _retrieve_for_citation(citation_text: str) -> list[dict[str, Any]]:
    try:
        from src.services.retrieval_qa import retrieve_passages
    except Exception as exc:  # noqa: BLE001
        log.warning("retrieval unavailable: %s", exc)
        return []
    try:
        passages = retrieve_passages(citation_text, k=4, comparative=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("retrieve_passages failed: %s", exc)
        return []
    return [
        {
            "source_name": p.citation.source_name,
            "marker": p.citation.marker,
            "jurisdiction": p.citation.jurisdiction,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:280],
            "content": p.content[:600],
        }
        for p in passages
    ]


def _score_overlap(sentence: str, passage_text: str) -> float:
    """Return a 0..1 overlap score combining n-gram + token overlap."""
    if not passage_text:
        return 0.0
    sent_tokens = _tokenize(sentence)
    pass_tokens = _tokenize(passage_text)
    if not sent_tokens:
        return 0.0
    token_overlap_ratio = len(sent_tokens & pass_tokens) / max(1, len(sent_tokens))
    ng_sent = _ngram(sentence, n=3)
    ng_pass = _ngram(passage_text, n=3)
    if not ng_sent:
        return token_overlap_ratio
    ng_ratio = len(ng_sent & ng_pass) / max(1, len(ng_sent))
    return round(min(1.0, 0.4 * token_overlap_ratio + 0.6 * ng_ratio + (0.1 if ng_ratio > 0 else 0)), 3)


def _grade(overlap: float, has_match: bool) -> str:
    if not has_match:
        return "not_found"
    if overlap >= 0.45:
        return "verified"
    if overlap >= 0.20:
        return "partial"
    if overlap >= 0.08:
        return "suspicious"
    return "hallucinated"


def verify_text(text: str) -> dict[str, Any]:
    """Run forensic citation analysis on a block of legal prose."""
    text = (text or "").strip()
    if not text:
        return {
            "input_text": "",
            "annotated_segments": [],
            "claims": [],
            "summary": {"verified": 0, "partial": 0, "suspicious": 0, "hallucinated": 0,
                        "not_found": 0, "no_citations": 0, "total_sentences": 0,
                        "total_citations": 0},
            "overall_grade": "no_input",
            "overall_score": 0.0,
        }

    sentences = _split_sentences(text)
    annotated_segments: list[dict[str, Any]] = []
    claims: list[dict[str, Any]] = []
    summary = {
        "verified": 0, "partial": 0, "suspicious": 0,
        "hallucinated": 0, "not_found": 0, "no_citations": 0,
        "total_sentences": len(sentences), "total_citations": 0,
    }

    for start, end, sent in sentences:
        cites = _extract_citations_from_sentence(sent)
        if not cites:
            annotated_segments.append({
                "start": start, "end": end,
                "sentence": sent,
                "status": "no_citations",
                "citations": [],
            })
            summary["no_citations"] += 1
            continue

        sentence_claims: list[dict[str, Any]] = []
        best_status = "not_found"
        best_overlap = 0.0
        for cite in cites:
            summary["total_citations"] += 1
            passages = _retrieve_for_citation(cite["text"])
            if not passages:
                claim = {
                    "citation_kind": cite["kind"],
                    "citation_text": cite["text"],
                    "sentence": sent,
                    "overlap": 0.0,
                    "status": "not_found",
                    "best_match": None,
                    "supporting_passages": [],
                }
                sentence_claims.append(claim)
                claims.append(claim)
                summary["not_found"] += 1
                continue
            scored = sorted(
                ((p, _score_overlap(sent, p["content"])) for p in passages),
                key=lambda item: item[1], reverse=True,
            )
            best_passage, best_score = scored[0]
            status = _grade(best_score, has_match=True)
            claim = {
                "citation_kind": cite["kind"],
                "citation_text": cite["text"],
                "sentence": sent,
                "overlap": best_score,
                "status": status,
                "best_match": {
                    "source_name": best_passage["source_name"],
                    "marker": best_passage["marker"],
                    "page": best_passage["page"],
                    "jurisdiction": best_passage["jurisdiction"],
                    "excerpt": best_passage["excerpt"],
                },
                "supporting_passages": passages[:3],
            }
            sentence_claims.append(claim)
            claims.append(claim)
            summary[status] = summary.get(status, 0) + 1
            if best_score > best_overlap:
                best_overlap = best_score
                best_status = status

        annotated_segments.append({
            "start": start, "end": end,
            "sentence": sent,
            "status": best_status,
            "overlap": best_overlap,
            "citations": [{"kind": c["kind"], "text": c["text"]} for c in cites],
            "claim_indices": list(range(len(claims) - len(sentence_claims), len(claims))),
        })

    cited = summary["total_citations"]
    if cited == 0:
        overall = "no_citations"
        overall_score = 0.0
    else:
        overall_score = round(
            (summary["verified"] * 1.0 + summary["partial"] * 0.6
             + summary["suspicious"] * 0.25 + summary["hallucinated"] * 0.0
             + summary["not_found"] * 0.0) / max(1, cited),
            3,
        )
        if overall_score >= 0.7:
            overall = "high_trust"
        elif overall_score >= 0.45:
            overall = "medium_trust"
        elif overall_score >= 0.2:
            overall = "low_trust"
        else:
            overall = "untrustworthy"

    return {
        "input_text": text,
        "annotated_segments": annotated_segments,
        "claims": claims,
        "summary": summary,
        "overall_grade": overall,
        "overall_score": overall_score,
    }
