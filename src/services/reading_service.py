"""OmniLegal Reading Studio (Pillar 12).

Auto-annotate any pasted legal text. For each paragraph we surface:
  • detected legal terms (with plain-English glosses)
  • detected citations (linked back to the corpus where possible)
  • a one-line paragraph summary

Glosses come from a deterministic lexicon first (instant, free), then a
single Groq call enriches anything we don't recognise.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.reading")


# Curated lexicon of common legal terms — instant gloss, no API call needed.
_LEGAL_LEXICON: dict[str, str] = {
    "habeas corpus": "Court order requiring a detained person be brought before a judge to test the legality of detention.",
    "mens rea": "The mental element required for criminal liability — guilty mind.",
    "actus reus": "The physical, voluntary act element of a crime.",
    "stare decisis": "Doctrine that courts should follow prior decisions on the same legal issue.",
    "ratio decidendi": "The legal rule that is the necessary basis of a court's decision; binding precedent.",
    "obiter dicta": "Statements in a judgment that are not necessary for the decision; persuasive only.",
    "ex parte": "Proceeding involving only one party, without notice to the other.",
    "amicus curiae": "Friend of the court — a non-party who provides expertise to assist the court.",
    "ultra vires": "Beyond the legal powers or authority of the actor.",
    "prima facie": "On the face of it; sufficient at first appearance.",
    "due process": "Constitutional guarantee of fair procedure before deprivation of life, liberty, or property.",
    "estoppel": "A bar preventing a party from asserting something inconsistent with a prior position.",
    "tort": "A civil wrong (other than breach of contract) actionable in damages.",
    "negligence": "Failure to exercise the standard of care a reasonable person would in the circumstances.",
    "consideration": "Something of value exchanged between parties to make a contract enforceable.",
    "force majeure": "An unforeseeable event excusing performance under a contract.",
    "indemnify": "To compensate or hold harmless against loss or liability.",
    "jurisdiction": "A court's authority to hear and decide a matter.",
    "subpoena": "Court order compelling a person to appear or produce evidence.",
    "writ": "A formal written court order commanding a specified action.",
    "injunction": "Court order requiring a party to do or refrain from doing something.",
    "specific performance": "Court order compelling actual performance of a contract.",
    "mens rea specific intent": "Heightened mental state requiring purpose to bring about a specific result.",
    "burden of proof": "The duty placed on a party to prove a fact in dispute.",
    "preponderance of evidence": "The civil standard — more likely than not.",
    "beyond reasonable doubt": "The criminal standard — no reasonable doubt remains.",
    "voir dire": "Preliminary examination of a witness or juror by the court.",
    "double jeopardy": "Constitutional rule against being tried twice for the same offence.",
    "self-incrimination": "A person's right not to be compelled to testify against themselves.",
    "mens rea recklessness": "Awareness of and conscious disregard for a substantial risk.",
    "doctrine of basic structure": "Indian constitutional doctrine: Parliament cannot amend the Constitution's essential features.",
    "margin of appreciation": "ECHR doctrine giving states latitude in implementing Convention rights.",
    "proportionality": "Test that a state measure must be suitable, necessary, and not excessive relative to its aim.",
    "chilling effect": "Indirect suppression of lawful conduct (esp. speech) through fear of legal sanction.",
    "necessity defence": "Justification that conduct prevented a greater harm.",
    "self-defence": "Lawful use of force to repel an imminent unlawful attack.",
}


_CITATION_RE = re.compile(
    r"(\b\d{1,4}\s+U\.?S\.?\s+\d{1,4}(?:\s*\(\d{4}\))?"  # US case
    r"|\[\d{4}\]\s+[A-Z]{2,5}\s*\d+"                      # UK case
    r"|\bSection\s+\d+[A-Z]?\b"                          # Indian section
    r"|\bArticle\s+\d+[A-Z]?\b"                          # Treaty article
    r"|\b\d{1,3}\s+U\.?S\.?C\.?\s*§?\s*\d+[a-z\-\d]*)",  # USC
    re.IGNORECASE,
)


def _split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", (text or "").replace("\r\n", "\n"))
    return [p.strip() for p in parts if p.strip()]


def _find_lexicon_terms(paragraph: str) -> list[dict[str, Any]]:
    """Find every occurrence of every lexicon term, longest first.

    Longest-first matching prevents 'mens rea' from masking
    'mens rea specific intent'. Spans are word-boundary-aware so
    'tort' inside 'tortious' is not falsely matched.
    """
    found: list[dict[str, Any]] = []
    lower = paragraph.lower()
    # Longest-first so multi-word terms win over their substrings.
    sorted_terms = sorted(_LEGAL_LEXICON.items(), key=lambda kv: -len(kv[0]))
    claimed: list[tuple[int, int]] = []  # (start, end) ranges already taken

    def _overlaps(s: int, e: int) -> bool:
        return any(not (e <= cs or s >= ce) for cs, ce in claimed)

    for term, gloss in sorted_terms:
        n = len(term)
        start = 0
        while True:
            idx = lower.find(term, start)
            if idx == -1:
                break
            end = idx + n
            # Word-boundary guard
            before = lower[idx - 1] if idx > 0 else " "
            after  = lower[end] if end < len(lower) else " "
            if (before.isalnum() or before == "_") or (after.isalnum() or after == "_"):
                start = idx + 1
                continue
            if not _overlaps(idx, end):
                found.append({
                    "span_start": idx,
                    "span_end": end,
                    "term": paragraph[idx:end],
                    "kind": "term",
                    "gloss": gloss,
                    "source": "lexicon",
                })
                claimed.append((idx, end))
            start = end
    return found


def _find_citations(paragraph: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in _CITATION_RE.finditer(paragraph):
        out.append({
            "span_start": m.start(),
            "span_end": m.end(),
            "term": m.group(0),
            "kind": "citation",
            "gloss": "Detected citation — see source rail.",
            "source": "regex",
        })
    return out


def _summarise_paragraphs(paragraphs: list[str]) -> tuple[dict[int, str], str, list[dict[str, Any]]]:
    """One LLM call to produce one-line summaries for each paragraph.

    Returns (summaries_by_index, used_model, attempts_log).
    """
    if not paragraphs:
        return {}, "deterministic", []
    numbered = "\n\n".join(f"[P{i}] {p[:600]}" for i, p in enumerate(paragraphs[:30]))
    system = (
        "Summarise each paragraph in ONE clear sentence. Output STRICT JSON: "
        '{"summaries": [{"index": 0, "summary": "..."}, ...]}. Use the [P#] '
        "index, never invent paragraphs."
    )

    from src.services.llm_waterfall import generate_json, attempts_as_dicts

    def _validate(d: dict[str, Any]) -> bool:
        return isinstance(d, dict) and isinstance(d.get("summaries"), list)

    parsed, used, attempts = generate_json(
        system=system, prompt=numbered,
        validate=_validate, max_tokens=1800, temperature=0.2,
    )
    if parsed is None:
        return {}, "none", attempts_as_dicts(attempts)

    out: dict[int, str] = {}
    for entry in parsed.get("summaries") or []:
        try:
            out[int(entry["index"])] = str(entry.get("summary", ""))[:300]
        except Exception:
            continue
    return out, used, attempts_as_dicts(attempts)


def annotate(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"error": "Empty text."}
    paragraphs = _split_paragraphs(text)
    if len(paragraphs) > 60:
        paragraphs = paragraphs[:60]

    summaries, summary_model, summary_attempts = _summarise_paragraphs(paragraphs)

    annotated = []
    total_terms = 0
    total_cites = 0
    for i, para in enumerate(paragraphs):
        terms = _find_lexicon_terms(para)
        cites = _find_citations(para)
        # Sort by span_start, dedupe overlapping spans
        spans = sorted(terms + cites, key=lambda s: s["span_start"])
        deduped: list[dict[str, Any]] = []
        last_end = -1
        for sp in spans:
            if sp["span_start"] >= last_end:
                deduped.append(sp)
                last_end = sp["span_end"]
        annotated.append({
            "index": i,
            "text": para,
            "summary": summaries.get(i, ""),
            "spans": deduped,
        })
        total_terms += sum(1 for s in deduped if s["kind"] == "term")
        total_cites += sum(1 for s in deduped if s["kind"] == "citation")

    return {
        "paragraphs": annotated,
        "stats": {
            "paragraph_count": len(annotated),
            "term_count": total_terms,
            "citation_count": total_cites,
        },
        "used_model": summary_model,
        "provider_attempts": summary_attempts,
    }
