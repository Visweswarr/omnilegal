"""
Step 8: citation verification.

Local deterministic defaults:
- every [N] marker must point to a retrieved passage
- quoted text near a marker must appear verbatim in that passage
- unsupported markers are stripped and the response becomes insufficient evidence

Optional production hooks:
- HHEM-2.1 / NLI entailment when heavy models are enabled
- Anthropic Citations API can be added without changing the output contract
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_REQUEST_TIMEOUT_SECONDS,
    LEGAL_RESEARCH_SHORT_DISCLAIMER,
    NLI_MODEL,
    OMNILEGAL_ENABLE_CITATION_SELF_CRITIQUE,
    OMNILEGAL_ENABLE_HEAVY_MODELS,
    OMNILEGAL_ENABLE_NLI_VERIFIER,
)
from src.pipeline.state import PipelineStateDict
from src.models.heavy_nlp import get_nli_verifier
from src.services.answer_format import (
    format_answer_sections,
    missing_citation_sentences,
    sentence_chunks,
    split_answer_sections,
)
from src.services.authority import (
    authority_gaps_from_status,
    grounding_status_from_passages,
    infer_authority_tier,
    is_merits_citable_tier,
)
from src.services.groq_client import generate_groq_chat

_MARKER_RE = re.compile(r"\[(\d+)\]")
_MARKER_GROUP_RE = re.compile(r"\[((?:\d+\s*,\s*)+\d+)\]")
# Converts [S1], [S2, S3] style markers (from merged synthesizer) to [1], [2, 3]
_S_MARKER_RE = re.compile(r"\[S(\d+)\]")
_S_MARKER_GROUP_RE = re.compile(r"\[S(\d+)(?:\s*,\s*S(\d+))*\]")
_QUOTE_RE = re.compile(r'"([^"]{8,300})"|“([^”]{8,300})”|\'([^\']{8,300})\'')


def _normalise_s_markers(draft: str) -> str:
    """Convert [S1], [S2, S3] style tags (from merged synthesizer) to [1], [2, 3]."""
    # Groups like [S1, S2, S3] → [1, 2, 3]
    def _group_repl(m: re.Match) -> str:
        inner = m.group(0)[1:-1]  # strip outer brackets
        nums = re.findall(r"S(\d+)", inner)
        return "[" + ", ".join(nums) + "]" if nums else m.group(0)

    draft = re.sub(r"\[S\d+(?:\s*,\s*S\d+)+\]", _group_repl, draft)
    # Single [S#] → [#]
    return _S_MARKER_RE.sub(r"[\1]", draft)


def _normalise_marker_groups(draft: str) -> str:
    def repl(match: re.Match[str]) -> str:
        markers = [part.strip() for part in match.group(1).split(",") if part.strip()]
        return " ".join(f"[{marker}]" for marker in markers)

    return _MARKER_GROUP_RE.sub(repl, draft)


def _oscola_citation(meta: dict[str, Any]) -> str:
    doc_type = meta.get("doc_type", "")
    source = meta.get("source_name") or meta.get("citation") or "Unknown source"
    year = meta.get("year") or "n.d."
    art = meta.get("article_number") or ""
    if doc_type == "treaty":
        article = f", art. {art}" if art and art != "preamble" else ""
        return f"{source}{article} ({year})"
    if doc_type == "case_law":
        return f"{source} [{year}]"
    if meta.get("collection") == "SHAW_PRIVATE":
        return f"{source}, short private-corpus excerpt"
    return str(source)


def _bluebook_citation(meta: dict[str, Any]) -> str:
    source = meta.get("source_name") or meta.get("citation") or "Unknown source"
    year = meta.get("year") or "n.d."
    art = meta.get("article_number") or ""
    if art:
        return f"{source} art. {art} ({year})"
    return f"{source} ({year})"


def _citation_style(meta: dict[str, Any]) -> str:
    jurisdiction = (meta.get("jurisdiction") or "").lower()
    return _bluebook_citation(meta) if jurisdiction in {"us", "united_states"} else _oscola_citation(meta)


def _claim_before_marker(marker_idx: int, draft: str) -> str:
    pattern = re.compile(r"([^.!?\n]{20,220}(?:[.!?])?)\s*\[" + str(marker_idx) + r"\]")
    match = pattern.search(draft)
    return match.group(1).strip() if match else ""


def _quotes_near_marker(marker_idx: int, draft: str) -> list[str]:
    marker = f"[{marker_idx}]"
    pos = draft.find(marker)
    if pos < 0:
        return []
    window = draft[max(0, pos - 500): pos + len(marker)]
    quotes: list[str] = []
    for match in _QUOTE_RE.finditer(window):
        quote = next(group for group in match.groups() if group)
        quotes.append(" ".join(quote.split()))
    return quotes


def _normalise_for_match(text: str) -> str:
    return " ".join((text or "").lower().split())


def _normalise_jurisdiction_code(value: Any) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    mapping = {
        "india": "in",
        "indian": "in",
        "russia": "ru",
        "russian": "ru",
        "russian federation": "ru",
        "united states": "us",
        "usa": "us",
        "u.s.": "us",
        "american": "us",
        "uk": "gb",
        "united kingdom": "gb",
        "british": "gb",
        "international": "international",
    }
    return mapping.get(cleaned, cleaned)


def _forced_quote_passes(marker_idx: int, draft: str, passage_text: str) -> tuple[bool, list[str]]:
    quotes = _quotes_near_marker(marker_idx, draft)
    if not quotes:
        return True, []
    passage_norm = _normalise_for_match(passage_text)
    missing = [quote for quote in quotes if _normalise_for_match(quote) not in passage_norm]
    return not missing, missing


def _lexical_support_ratio(claim_text: str, passage_text: str) -> float:
    claim_words = set(re.findall(r"\b[a-z]{4,}\b", claim_text.lower()))
    passage_words = set(re.findall(r"\b[a-z]{4,}\b", passage_text.lower()))
    if not claim_words:
        return 0.0
    return len(claim_words & passage_words) / len(claim_words)


def _support_quote_span(claim_text: str, passage_text: str) -> dict[str, Any] | None:
    """Return the best exact source sentence span supporting a claim."""
    claim_words = set(re.findall(r"\b[a-z]{4,}\b", claim_text.lower()))
    if not claim_words:
        return None
    best: tuple[float, int, int, str] | None = None
    for match in re.finditer(r"[^.!?\n]{20,500}(?:[.!?]|\n|$)", passage_text):
        sentence = " ".join(match.group(0).split())
        if not sentence:
            continue
        words = set(re.findall(r"\b[a-z]{4,}\b", sentence.lower()))
        if not words:
            continue
        overlap = len(claim_words & words) / len(claim_words)
        if best is None or overlap > best[0]:
            best = (overlap, match.start(), match.end(), sentence)
    if best is None or best[0] < 0.30:
        return None
    return {
        "start": best[1],
        "end": best[2],
        "quote": best[3],
        "overlap": best[0],
    }


_NAMED_AUTHORITIES = [
    "corfu channel", "nicaragua", "oil platforms", "caroline", "drc v. uganda",
    "lotus", "barcelona traction", "nottebohm", "chorzow factory",
    "tinoco", "tinoco arbitration", "island of palmas", "trail smelter",
    "alabama claims", "rainbow warrior", "tadic", "akayesu", "pinochet",
    "reparations for injuries", "nuclear tests", "wall advisory opinion",
    "south west africa", "la grand", "lagrand", "avena",
]


def _named_authority_mismatch(claim_text: str, passage_text: str) -> str | None:
    claim_lower = claim_text.lower()
    passage_lower = passage_text.lower()
    for authority in _NAMED_AUTHORITIES:
        if authority in claim_lower and authority not in passage_lower:
            # Only fail hard when the claim explicitly quotes or cites the case
            # by name (contains "held", "decided", "ruled", or a quote marker).
            # Otherwise AMBIGUOUS is more appropriate than INCORRECT.
            if any(word in claim_lower for word in ["held", "decided", "ruled", "stated", '"', "'"]):
                return authority
    return None


_NOISE_SOURCES = {"nato", "unctad", "african court", "isds"}


def _is_noise_source(source_name: str, query: str) -> bool:
    """Return True if the source is a noise source not mentioned in the query."""
    lowered_source = (source_name or "").lower()
    lowered_query = query.lower()
    for noise in _NOISE_SOURCES:
        if noise in lowered_source:
            if noise in lowered_query:
                return False
            return True
    return False


def _is_source_discovery_query(query: str) -> bool:
    lowered = query.lower()
    return any(
        term in lowered
        for term in [
            "source", "sources", "dataset", "datasets", "corpus", "available",
            "ingested", "download", "license", "coverage", "api", "where can",
            "source map", "project reference", "blocked",
        ]
    )


def _nli_entailment_probability(claim_text: str, passage_text: str) -> float | None:
    """Optional HHEM/NLI hook. Returns None when the local model is unavailable."""
    if not OMNILEGAL_ENABLE_HEAVY_MODELS or not OMNILEGAL_ENABLE_NLI_VERIFIER:
        return None

    model_attempts = [
        (NLI_MODEL, "trust_remote_code"),
        ("cross-encoder/nli-deberta-base", ""),
    ]
    last_error: Exception | None = None
    for model_name, kwargs_str in model_attempts:
        try:
            nli = get_nli_verifier(model_name, kwargs_str)
            if nli is None:
                continue
            result = nli({"text": passage_text[:2048], "text_pair": claim_text[:512]})
            if isinstance(result, list):
                result = result[0]
            label = str(result.get("label", "")).lower()
            score = float(result.get("score", 0.0))
            return score if "entail" in label or "consistent" in label else 1.0 - score
        except Exception as exc:
            last_error = exc
            continue
    print(f"Warning: NLI verifier unavailable: {last_error}")
    return None


def _two_pass_self_critique(claim_text: str, passage_text: str) -> str | None:
    """Second-pass Groq check for AMBIGUOUS citations.

    Asks: 'Does this claim follow from this passage?' Returns 'CORRECT',
    'INCORRECT', or None when the API is unavailable.
    """
    if not GROQ_API_KEY or not OMNILEGAL_ENABLE_CITATION_SELF_CRITIQUE:
        return None
    try:
        prompt = (
            "You are a strict legal fact-checker. "
            "Answer exactly one word: CORRECT if the claim follows from the passage, "
            "or INCORRECT if it does not.\n\n"
            f"PASSAGE:\n{passage_text[:1200]}\n\n"
            f"CLAIM:\n{claim_text[:400]}\n\n"
            "Answer (CORRECT or INCORRECT):"
        )
        generation = generate_groq_chat(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4,
            temperature=0.0,
            timeout=GROQ_REQUEST_TIMEOUT_SECONDS,
        )
        if generation.error:
            return None
        verdict = generation.text.strip().upper()
        if verdict.startswith("CORRECT"):
            return "CORRECT"
        if verdict.startswith("INCORRECT"):
            return "INCORRECT"
        return None
    except Exception as exc:
        print(f"Warning: two-pass self-critique unavailable: {exc}")
        return None


def _grade_citation(marker_idx: int, draft: str, retrieved: list[dict[str, Any]], *, query: str = "", state: PipelineStateDict | None = None) -> dict[str, Any]:
    if marker_idx < 1 or marker_idx > len(retrieved):
        return {"grade": "INCORRECT", "reason": "marker does not map to a retrieved source"}

    passage = retrieved[marker_idx - 1]
    passage_text = passage.get("text", "") or ""
    if not passage_text.strip():
        return {"grade": "INCORRECT", "reason": "retrieved passage is empty"}
    meta = passage.get("metadata", {}) or {}
    non_authority_doc_types = {"source_catalog", "source_map", "project_reference", "ingestion_manifest"}
    if (
        str(meta.get("doc_type", "")).lower() in non_authority_doc_types
        or meta.get("not_legal_authority") is True
    ) and not _is_source_discovery_query(query):
        return {
            "grade": "INCORRECT",
            "reason": "source metadata or project reference material cannot support a legal-merits claim",
            "quote_match": True,
        }

    if _is_noise_source(meta.get("source_name", ""), query):
        return {
            "grade": "INCORRECT",
            "reason": f"noise source ({meta.get('source_name', '')}) not relevant to query",
            "quote_match": True,
        }

    quote_ok, missing_quotes = _forced_quote_passes(marker_idx, draft, passage_text)
    if not quote_ok:
        return {
            "grade": "INCORRECT",
            "reason": "forced quote text was not found verbatim in the cited passage",
            "missing_quotes": missing_quotes,
            "quote_match": False,
        }

    claim_text = _claim_before_marker(marker_idx, draft)
    if not claim_text:
        return {"grade": "INCORRECT", "reason": "could not isolate the cited claim", "quote_match": True}

    authority_mismatch = _named_authority_mismatch(claim_text, passage_text)
    if authority_mismatch:
        return {
            "grade": "INCORRECT",
            "reason": f"cited passage does not mention named authority: {authority_mismatch}",
            "quote_match": True,
        }

    ratio = _lexical_support_ratio(claim_text, passage_text)
    entailment = _nli_entailment_probability(claim_text, passage_text)
    if entailment is not None and entailment < 0.7:
        return {
            "grade": "INCORRECT",
            "reason": f"NLI entailment below threshold: {entailment:.2f}",
            "quote_match": True,
            "entailment_probability": entailment,
            "lexical_support": ratio,
        }

    # Evidence-first thresholds: tightened to reduce false-positive citations.
    # Legal claims must have meaningful lexical overlap with source passages.
    if ratio >= 0.35:
        grade = "CORRECT"
    elif ratio >= 0.15:
        grade = "AMBIGUOUS"
    else:
        grade = "INCORRECT"

    quote_span = _support_quote_span(claim_text, passage_text)
    if grade == "CORRECT" and quote_span is None:
        grade = "INCORRECT"

    if grade == "CORRECT" and state:
        iso_codes = state.get("entities", {}).get("iso_country_codes", [])
        intent_primary = state.get("query_intent", {}).get("primary", [])
        passage_jur = _normalise_jurisdiction_code(meta.get("jurisdiction", ""))
        if iso_codes and passage_jur not in {"international", "unknown", ""}:
            if passage_jur not in [_normalise_jurisdiction_code(c) for c in iso_codes]:
                if "jurisdiction_comparison" not in intent_primary and "case_comparison" not in intent_primary:
                    grade = "AMBIGUOUS"
                    return {
                        "grade": grade,
                        "reason": f"retrieved passage jurisdiction ({passage_jur}) does not match query constraints and comparative intent is absent",
                        "quote_match": True,
                        "lexical_support": ratio,
                        "entailment_probability": entailment,
                    }

    return {

        "grade": grade,
        "reason": "lexical support check",
        "quote_match": True,
        "lexical_support": ratio,
        "entailment_probability": entailment,
        "retrieved_chunk_id": meta.get("chunk_id") or meta.get("canonical_doc_id") or marker_idx,
        "source_quote_span": quote_span,
    }


def _strip_incorrect_markers(draft: str, grades: dict[str, dict[str, Any]]) -> str:
    verified = draft
    for marker, detail in sorted(grades.items(), key=lambda item: int(item[0]), reverse=True):
        if detail["grade"] == "CORRECT":
            continue
        verified = verified.replace(f"[{marker}]", "")
    return verified


def _replace_correct_markers(draft: str, grades: dict[str, dict[str, Any]], retrieved: list[dict[str, Any]]) -> str:
    verified = draft
    for marker, detail in sorted(grades.items(), key=lambda item: int(item[0]), reverse=True):
        idx = int(marker)
        if detail["grade"] != "CORRECT" or idx > len(retrieved):
            continue
        meta = retrieved[idx - 1].get("metadata", {})
        verified = verified.replace(f"[{marker}]", f"[{_citation_style(meta)}]")
    return verified


def _short_excerpt(text: str, limit: int = 220) -> str:
    clean = " ".join((text or "").split())
    return clean[:limit]


def _clean_source_excerpt(text: str, limit: int = 220) -> str:
    raw = " ".join((text or "").split())
    if not raw:
        return ""
    if "\n\n" in text:
        candidate = " ".join(text.split("\n\n", 1)[1].split())
        if candidate:
            raw = candidate
    raw = raw.replace("Source URL:", "").strip()
    return raw[:limit]


def _scenario_sourced_line(index: int, passage: dict[str, Any], scenario_context: dict[str, Any]) -> str:
    meta = passage.get("metadata", {}) or {}
    source = meta.get("source_name", "Retrieved source")
    collection = str(meta.get("collection") or "").upper()
    jurisdiction = str(meta.get("jurisdiction") or "").strip().lower()
    text = " ".join(
        str(part or "")
        for part in [source, meta.get("citation"), passage.get("text")]
    ).lower()
    location_iso = str(scenario_context.get("location_iso") or "").strip().lower()
    passport_iso = str(scenario_context.get("passport_iso") or "").strip().lower()
    licence_iso = str(scenario_context.get("licence_issuing_iso") or "").strip().lower()
    excerpt = _clean_source_excerpt(passage.get("text", ""))

    if excerpt:
        return f"{source} excerpt: {excerpt} [{index}]."
    if collection == "INTL_TREATIES" and "consular" in text:
        return (
            "The Vienna Convention on Consular Relations is the retrieved treaty "
            f"source on consular notification and consular access for detained foreign nationals [{index}]."
        )
    if collection == "INTL_TREATIES" and any(
        term in text
        for term in ["road traffic", "driving permit", "driving licence", "driving license", "foreign driving"]
    ):
        return (
            "The Convention on Road Traffic is the retrieved treaty overlay on foreign-licence "
            f"recognition and international driving permits, subject to local implementation rules [{index}]."
        )
    if location_iso and jurisdiction == location_iso and any(
        term in text
        for term in ["road traffic safety", "administrative offences", "administrative liability", "traffic", "driving", "licence", "license"]
    ):
        return (
            f"{source} appears relevant to how the place-of-stop jurisdiction treats traffic licensing "
            f"issues and whether the matter is framed as a local road-traffic violation [{index}]."
        )
    if location_iso and jurisdiction == location_iso and any(
        term in text
        for term in ["detention", "arrest", "police", "procedure", "interpreter", "counsel"]
    ):
        return (
            f"{source} appears relevant if the roadside matter escalates into detention, questioning, "
            f"or formal criminal procedure in the place-of-stop jurisdiction [{index}]."
        )
    if jurisdiction and jurisdiction in {passport_iso, licence_iso} and any(
        term in text for term in ["passport", "driving", "licence", "license", "permit", "motor vehicles"]
    ):
        return (
            f"{source} is the home-country motor-vehicle and driver-licensing statute, so it is "
            f"relevant to the status of the Indian driving licence as a home-country document [{index}]."
        )
    if excerpt:
        return f"{source} indicates: {excerpt} [{index}]."
    return f"{source} appears relevant to the user's scenario [{index}]."


def _markers_in_text(text: str) -> list[int]:
    return [int(marker) for marker in _MARKER_RE.findall(text or "")]


def _cited_sentences_only(text: str) -> str:
    kept = [sentence for sentence in sentence_chunks(text) if _MARKER_RE.search(sentence)]
    return " ".join(kept).strip()


def _state_jurisdictions(state: PipelineStateDict) -> list[str]:
    values: list[str] = []
    scenario_context = ((state.get("entities") or {}).get("scenario_context") or {})

    def normalise(value: str) -> str:
        cleaned = str(value or "").strip().lower()
        mapping = {
            "india": "in",
            "indian": "in",
            "russia": "ru",
            "russian federation": "ru",
            "russian": "ru",
            "united states": "us",
            "american": "us",
            "united kingdom": "gb",
            "uk": "gb",
            "british": "gb",
            "international": "international",
        }
        return mapping.get(cleaned, cleaned)

    for code in [
        scenario_context.get("location_iso"),
        scenario_context.get("passport_iso"),
        scenario_context.get("licence_issuing_iso"),
    ]:
        cleaned = normalise(str(code or ""))
        if cleaned and cleaned not in values:
            values.append(cleaned)
    for analysis in state.get("jurisdiction_analyses", []) or []:
        jurisdiction = normalise(str(analysis.get("jurisdiction") or "").strip())
        if jurisdiction and jurisdiction not in values:
            values.append(jurisdiction)
    for code in (state.get("query_intent", {}) or {}).get("iso_codes", []) or []:
        cleaned = normalise(str(code or "").strip().lower())
        if cleaned and cleaned not in values:
            values.append(cleaned)
    if "international_overlay" in ((state.get("query_intent", {}) or {}).get("labels") or []) and "international" not in values:
        values.append("international")
    return values


def _state_legal_domains(state: PipelineStateDict) -> list[str]:
    values: list[str] = []
    for label in state.get("issue_labels", []) or []:
        cleaned = str(label or "").strip()
        if cleaned and cleaned not in values:
            values.append(cleaned)
    return values


def _normalised_sections(draft: str) -> dict[str, str]:
    sections = split_answer_sections(draft)
    sections["disclaimer"] = sections.get("disclaimer") or LEGAL_RESEARCH_SHORT_DISCLAIMER
    return sections


def _grounding_status_for_answer(
    retrieved: list[dict[str, Any]],
    *,
    cited_markers: list[int] | None = None,
) -> str:
    if cited_markers:
        return grounding_status_from_passages(retrieved, cited_markers=cited_markers)

    tiers = {infer_authority_tier((passage.get("metadata") or {})) for passage in retrieved}
    if "reference_dataset" in tiers and not any(is_merits_citable_tier(tier) for tier in tiers):
        return "secondary_only"
    return "no_authority"


def _grounded_fallback_draft(query: str, retrieved: list[dict[str, Any]], state: PipelineStateDict) -> str:
    answer_style = str(state.get("answer_style") or "long")
    sourced_lines: list[str] = []
    scenario_context = ((state.get("entities") or {}).get("scenario_context") or {})
    intent_primary = set((state.get("query_intent") or {}).get("primary") or [])
    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2
        and token not in {"the", "and", "for", "about", "tell", "what", "how", "case", "law", "legal"}
    }
    if "cross_border_scenario" in intent_primary:
        query_terms |= {"traffic", "road", "driving", "licence", "license", "permit", "foreign", "administrative"}
        treaty_focus = set(scenario_context.get("treaty_focus") or [])
        if "consular_notification" in treaty_focus:
            query_terms |= {"consular", "notification", "access", "detained", "foreign", "nationals"}
        if "foreign_licence_recognition" in treaty_focus:
            query_terms |= {"recognition", "driving", "permit", "licence", "license"}

    def match_count(passage: dict[str, Any]) -> int:
        text = f"{passage.get('metadata', {}).get('source_name', '')} {passage.get('text', '')}".lower()
        return sum(1 for term in query_terms if term in text)

    def score(passage: dict[str, Any]) -> float:
        return match_count(passage) + float(passage.get("score", 0.0)) * 0.01

    indexed = list(enumerate(retrieved, 1))
    matched = [
        item for item in indexed
        if match_count(item[1]) > 0 and is_merits_citable_tier(infer_authority_tier(item[1].get("metadata", {})))
    ]
    required_roles = list((state.get("source_plan") or {}).get("required_roles") or [])
    required_indexes: set[int] = set()
    if required_roles:
        required_matches = [
            item for item in indexed
            if is_merits_citable_tier(infer_authority_tier(item[1].get("metadata", {})))
            and any(_cited_passage_matches_requirement(item[1], req) for req in required_roles)
        ]
        required_indexes = {item[0] for item in required_matches}
        matched = required_matches + [item for item in matched if item[0] not in required_indexes]

    if "cross_border_scenario" in intent_primary and matched:
        def norm_jur(value: str) -> str:
            lowered = str(value or "").strip().lower()
            mapping = {
                "india": "in",
                "russia": "ru",
                "international": "international",
            }
            return mapping.get(lowered, lowered)

        location_iso = norm_jur(scenario_context.get("location_iso", ""))
        passport_iso = norm_jur(scenario_context.get("passport_iso", ""))
        licence_iso = norm_jur(scenario_context.get("licence_issuing_iso", ""))
        home_isos = {code for code in {passport_iso, licence_iso} if code}

        buckets: dict[str, list[tuple[int, dict[str, Any]]]] = {
            "traffic_local": [],
            "treaty_road": [],
            "treaty_consular": [],
            "home_documents": [],
            "procedure_local": [],
            "other": [],
        }
        for item in matched:
            original_idx, passage = item
            meta = passage.get("metadata", {}) or {}
            collection = str(meta.get("collection") or "").upper()
            jurisdiction = norm_jur(meta.get("jurisdiction", ""))
            text = " ".join(
                str(part or "")
                for part in [meta.get("source_name"), meta.get("citation"), passage.get("text")]
            ).lower()
            if collection == "INTL_TREATIES" and "consular" in text:
                buckets["treaty_consular"].append(item)
            elif collection == "INTL_TREATIES" and any(term in text for term in ["road traffic", "driving permit", "driving licence", "driving license", "foreign driving"]):
                buckets["treaty_road"].append(item)
            elif location_iso and jurisdiction == location_iso and any(term in text for term in ["road traffic", "driving", "licence", "license", "administrative"]):
                buckets["traffic_local"].append(item)
            elif location_iso and jurisdiction == location_iso and any(term in text for term in ["procedure", "detention", "arrest", "police", "interpreter", "counsel"]):
                buckets["procedure_local"].append(item)
            elif home_isos and jurisdiction in home_isos and any(term in text for term in ["passport", "driving", "licence", "license", "permit", "motor vehicles"]):
                buckets["home_documents"].append(item)
            else:
                buckets["other"].append(item)

        selected: list[tuple[int, dict[str, Any]]] = []
        seen_indexes: set[int] = set()
        target_count = 3 if answer_style == "short" else 4
        for bucket_name in ["traffic_local", "treaty_road", "treaty_consular", "home_documents", "procedure_local", "other"]:
            bucket = sorted(buckets[bucket_name], key=lambda item: score(item[1]), reverse=True)
            if not bucket:
                continue
            original_idx, passage = bucket[0]
            if original_idx in seen_indexes:
                continue
            selected.append((original_idx, passage))
            seen_indexes.add(original_idx)
            if len(selected) >= target_count:
                break
        if len(selected) < target_count:
            for item in sorted(matched, key=lambda item: score(item[1]), reverse=True):
                original_idx, passage = item
                if original_idx in seen_indexes:
                    continue
                selected.append((original_idx, passage))
                seen_indexes.add(original_idx)
                if len(selected) >= target_count:
                    break
        ranked = selected
    else:
        ranked_by_score = sorted(matched, key=lambda item: score(item[1]), reverse=True)
        if required_indexes:
            required_ranked = [item for item in matched if item[0] in required_indexes]
            ranked = required_ranked + [item for item in ranked_by_score if item[0] not in required_indexes]
        else:
            ranked = ranked_by_score

    limit = 3 if answer_style == "short" else 4
    sourced_items: list[tuple[int, dict[str, Any]]] = []
    for original_idx, passage in ranked[:limit]:
        text = " ".join((passage.get("text") or "").split())
        if not text:
            continue
        sourced_items.append((original_idx, passage))
        if "cross_border_scenario" in intent_primary:
            sourced_lines.append(_scenario_sourced_line(original_idx, passage, scenario_context))
        else:
            excerpt = _clean_source_excerpt(passage.get("text", ""))
            source = passage.get("metadata", {}).get("source_name", "Retrieved source")
            excerpt_sentence = sentence_chunks(excerpt)[0] if sentence_chunks(excerpt) else excerpt
            sourced_lines.append(f"{source} excerpt: {excerpt_sentence} [{original_idx}].")
    if answer_style == "short":
        bullets = [f"- {line}" for line in sourced_lines[:6]]
        if not bullets:
            bullets = ["- INSUFFICIENT EVIDENCE: no verified retrieved source span can answer this question."]
        return "In plain English:\n" + "\n".join(bullets)

    long_sections = {
        "bottom_line": "INSUFFICIENT EVIDENCE: the answer below is limited to verified retrieved source excerpts.",
        "legal_issue": "INSUFFICIENT EVIDENCE: no uncited legal issue statement is generated in fallback mode.",
        "international_law": "",
        "malcolm_shaw": "",
        "judgments_precedents": "",
        "local_law": "",
        "conflict_check": "INSUFFICIENT EVIDENCE: no source-backed international/local conflict comparison was generated.",
        "conclusion": "INSUFFICIENT EVIDENCE: no broader legal conclusion is generated beyond the cited source excerpts.",
        "sources": "",
    }

    source_lines: list[str] = []
    for line, (original_idx, passage) in zip(sourced_lines, sourced_items):
        meta = passage.get("metadata", {}) or {}
        collection = str(meta.get("collection") or "").upper()
        role = str(meta.get("source_role") or meta.get("doc_type") or "").lower()
        source_name = meta.get("source_name", "Retrieved source")
        source_lines.append(f"- {source_name} [{original_idx}]")
        if collection == "SHAW_PRIVATE" or role == "commentary":
            bucket = "malcolm_shaw"
        elif role in {"case_law", "local_case"} or "CASE_LAW" in collection:
            bucket = "judgments_precedents"
        elif role == "treaty" or collection == "INTL_TREATIES":
            bucket = "international_law"
        else:
            bucket = "local_law"
        current = long_sections.get(bucket, "")
        long_sections[bucket] = (current + "\n" + line).strip() if current else line

    if not sourced_lines:
        long_sections["local_law"] = "INSUFFICIENT EVIDENCE: no verified retrieved source span can answer this question."
    long_sections["sources"] = "\n".join(source_lines)
    return format_answer_sections(long_sections)


def _insufficient_final(
    query: str,
    retrieved: list[dict[str, Any]],
    grades: dict[str, Any],
    reason: str,
    state: PipelineStateDict,
    *,
    cited_markers: list[int] | None = None,
) -> dict[str, Any]:
    gap_lines = "\n".join(f"- {gap}" for gap in [reason, *authority_gaps_from_status("no_authority", retrieved)])
    sections = {
        "sourced_authority": "",
        "general_principles": "The retrieved source set did not pass verification, so OmniLegal cannot give a legal conclusion.",
        "practical_steps": "Add or ingest the missing primary source material, then ask again with the relevant country, statute, treaty, or case name.",
        "disclaimer": LEGAL_RESEARCH_SHORT_DISCLAIMER,
    }
    grounding_status = _grounding_status_for_answer(retrieved, cited_markers=cited_markers or [])
    authority_gaps = [reason, *authority_gaps_from_status(grounding_status, retrieved)]
    answer = (
        "## Insufficient Verified Sources\n"
        f"{gap_lines or reason}\n\n"
        f"## General Principles / Common Practice\n{sections['general_principles']}\n\n"
        f"## Practical Steps\n{sections['practical_steps']}\n\n"
        f"## Disclaimer\n{sections['disclaimer']}"
    )
    return {
        "query": query,
        "answer": answer,
        "citations": [],
        "sources": retrieved,
        "jurisdictions_considered": _state_jurisdictions(state),
        "legal_domains": _state_legal_domains(state),
        "grounding_status": grounding_status,
        "authority_gaps": authority_gaps,
        "answer_style": str(state.get("answer_style") or "long"),
        "sections": sections,
        "used_model": GROQ_MODEL,
        "used_groq": bool(GROQ_API_KEY),
        "retrieval_strategy": "qdrant_hybrid_rrf_rerank",
        "verification_grades": grades,
        "insufficient_context": grounding_status != "primary_present",
    }


def _build_verified_final(
    query: str,
    draft: str,
    retrieved: list[dict[str, Any]],
    details: dict[str, dict[str, Any]],
    state: PipelineStateDict,
) -> tuple[str, dict[str, Any]]:
    grades = {marker: detail["grade"] for marker, detail in details.items()}
    ambiguous = [marker for marker, grade in grades.items() if grade == "AMBIGUOUS"]
    correct_markers = [int(marker) for marker, grade in grades.items() if grade == "CORRECT"]
    verified = _replace_correct_markers(draft, details, retrieved).strip()
    sections = _normalised_sections(verified)
    answer_style = str(state.get("answer_style") or "long")
    if ambiguous:
        note = "Some cited points remain ambiguous and should be checked directly: " + ", ".join(f"[{m}]" for m in ambiguous)
        existing = sections.get("general_principles", "")
        sections["general_principles"] = (existing + "\n\n" + note).strip() if existing else note
    sections["disclaimer"] = LEGAL_RESEARCH_SHORT_DISCLAIMER
    if answer_style == "short":
        if LEGAL_RESEARCH_SHORT_DISCLAIMER not in verified:
            verified = f"{verified}\n\n{LEGAL_RESEARCH_SHORT_DISCLAIMER}"
    else:
        verified = format_answer_sections(sections)

    citations = []
    for marker, grade in grades.items():
        idx = int(marker)
        if idx > len(retrieved):
            continue
        meta = retrieved[idx - 1].get("metadata", {})
        text = retrieved[idx - 1].get("text", "")
        citations.append({
            "marker": marker,
            "grade": grade,
            "authority_tier": infer_authority_tier(meta),
            "source_name": meta.get("source_name", "Unknown"),
            "jurisdiction": meta.get("jurisdiction", ""),
            "article": meta.get("article_number", ""),
            "citation": _citation_style(meta),
            "excerpt": _short_excerpt(text, 180 if meta.get("collection") == "SHAW_PRIVATE" else 220),
        })

    grounding_status = _grounding_status_for_answer(retrieved, cited_markers=correct_markers)
    authority_gaps = authority_gaps_from_status(grounding_status, retrieved)
    final = {
        "query": query,
        "answer": verified,
        "citations": citations,
        "sources": retrieved,
        "jurisdictions_considered": _state_jurisdictions(state),
        "legal_domains": _state_legal_domains(state),
        "grounding_status": grounding_status,
        "authority_gaps": authority_gaps,
        "answer_style": answer_style,
        "sections": sections,
        "jurisdiction_analyses": state.get("jurisdiction_analyses", []),
        "conflicts": state.get("conflicts", []),
        "used_model": GROQ_MODEL,
        "used_groq": bool(GROQ_API_KEY),
        "retrieval_strategy": "qdrant_hybrid_rrf_rerank",
        "verification_grades": details,
        "insufficient_context": grounding_status != "primary_present",
    }
    return verified, final


def _check_source_plan_sufficiency(
    state: PipelineStateDict,
    cited_markers: list[int],
    retrieved: list[dict[str, Any]],
) -> list[str]:
    """Verify that required source roles from source_plan are represented in cited passages."""
    source_plan = state.get("source_plan") or {}
    required_roles = source_plan.get("required_roles") or []
    if not required_roles:
        return []

    cited_roles: set[str] = set()
    cited_passages: list[dict[str, Any]] = []
    for idx in cited_markers:
        if 1 <= idx <= len(retrieved):
            cited_passages.append(retrieved[idx - 1])
            meta = retrieved[idx - 1].get("metadata", {}) or {}
            role = str(meta.get("source_role", "") or "").lower()
            if not role:
                doc_type = str(meta.get("doc_type", "") or "").lower()
                collection = str(meta.get("collection", "") or "").upper()
                if doc_type == "treaty" or collection == "INTL_TREATIES":
                    role = "treaty"
                elif doc_type == "case_law" or "CASE_LAW" in collection:
                    role = "case_law"
                elif doc_type == "official_guidance" or collection.startswith("NATIONAL_"):
                    role = "official_guidance"
                elif doc_type in {"statute", "legislation", "domestic_law"} or "STATUTES" in collection:
                    role = "local_statute"
                elif doc_type == "commentary" or "COMMENTARY" in collection or collection == "SHAW_PRIVATE":
                    role = "commentary"
            cited_roles.add(role.lower())

    missing: list[str] = []
    for req in required_roles:
        role = req.get("role", "")
        if role.lower() not in cited_roles:
            desc = req.get("description", role)
            missing.append(f"Required {role} source not cited: {desc}")
            continue
        pattern = str(req.get("source_pattern") or "").strip()
        collection = str(req.get("collection") or "").upper()
        if pattern or collection:
            if not any(_cited_passage_matches_requirement(p, req) for p in cited_passages):
                desc = req.get("description", role)
                missing.append(f"Required source not cited: {desc}")
    return missing


def _cited_passage_matches_requirement(passage: dict[str, Any], requirement: dict[str, Any]) -> bool:
    meta = passage.get("metadata", {}) or {}
    req_collection = str(requirement.get("collection") or "").upper()
    collection = str(meta.get("collection") or "").upper()
    if req_collection and collection != req_collection:
        return False
    pattern = str(requirement.get("source_pattern") or "").strip()
    if not pattern:
        return True
    haystack = " ".join(
        str(part or "")
        for part in [
            meta.get("source_name"),
            meta.get("citation"),
            meta.get("source_url"),
            meta.get("doc_type"),
            meta.get("jurisdiction"),
            meta.get("article_number"),
            passage.get("text"),
        ]
    )
    try:
        return bool(re.search(pattern, haystack, re.IGNORECASE))
    except re.error:
        return pattern.lower() in haystack.lower()


def _compute_confidence_badge(grounded_ratio: float, invalid: list, insufficient: bool) -> str:
    if insufficient:
        return "_Verification: abstention (insufficient evidence)_"
    if invalid:
        return f"_Verification: {len(invalid)} invalid citation tag(s) - flagged above_"
    if grounded_ratio >= 0.9:
        return f"_Verification: {int(grounded_ratio * 100)}% of claims grounded_"
    if grounded_ratio >= 0.6:
        return f"_Verification: {int(grounded_ratio * 100)}% of claims grounded - check flagged lines_"
    return f"_Verification: only {int(grounded_ratio * 100)}% of claims grounded - treat with caution_"


def _regenerate_once(
    state: PipelineStateDict,
    retrieved: list[dict[str, Any]],
    *,
    reason: str,
) -> PipelineStateDict | None:
    """Retry generation once with a strict repair prompt, then re-run verification."""
    if int(state.get("regeneration_attempt") or 0) >= 1:
        return None
    try:
        from src.pipeline.llm import complete
        from src.pipeline.prompts import build_repair_message, system_for

        query = state.get("raw_input", "")
        style = str(state.get("answer_style") or "long")
        valid_labels = {f"S{i}" for i in range(1, len(retrieved) + 1)}
        user = build_repair_message(query, retrieved, style, valid_labels)
        user += (
            "\n\nVerification failure to repair: "
            f"{reason}. Every factual sentence must cite a valid source tag and be directly supported by an exact source sentence."
        )
        mode = str(state.get("mode") or "research")
        repaired, provider = complete(system_for(mode), user, temperature=0.03)
        if not repaired.strip():
            return None
        retry_state: PipelineStateDict = {
            **state,
            "draft": repaired,
            "provider": provider,
            "regeneration_attempt": 1,
        }
        return verify_citations(retry_state)
    except Exception as exc:
        print(f"Warning: strict citation regeneration failed: {exc}")
        return None


def _try_extractive_retry(
    state: PipelineStateDict,
    query: str,
    retrieved: list[dict[str, Any]],
) -> PipelineStateDict | None:
    """Switch to deterministic extractive fallback after LLM verification failure."""
    if state.get("provider") == "extractive_fallback":
        return None
    fallback_draft = _grounded_fallback_draft(query, retrieved, {**state, "regeneration_attempt": 1})
    fallback_markers = _markers_in_text(fallback_draft)
    if not fallback_markers:
        return None
    return verify_citations(
        {
            **state,
            "draft": fallback_draft,
            "provider": "extractive_fallback",
            "regeneration_attempt": 1,
        }
    )


def verify_citations(state: PipelineStateDict) -> PipelineStateDict:
    # Normalize [S#] markers emitted by merged synthesizer → [#] for grading
    draft = _normalise_marker_groups(_normalise_s_markers(state.get("draft", "") or ""))
    retrieved = state.get("retrieved", []) or []
    query = state.get("raw_input", "")

    if not draft.strip():
        final = _insufficient_final(query, retrieved, {}, "The generation step did not produce a draft.", state)
        return {**state, "verified_draft": final["answer"], "citation_grades": {}, "verification_grades": {}, "grounding_status": final["grounding_status"], "authority_gaps": final["authority_gaps"], "answer_sections": final["sections"], "insufficient_context": final["insufficient_context"], "final": final}

    markers = [int(m) for m in _MARKER_RE.findall(draft)]
    if not retrieved:
        final = _insufficient_final(query, retrieved, {}, "No retrieved source passages were available for verification.", state)
        return {**state, "verified_draft": final["answer"], "citation_grades": {}, "verification_grades": {}, "grounding_status": final["grounding_status"], "authority_gaps": final["authority_gaps"], "answer_sections": final["sections"], "insufficient_context": final["insufficient_context"], "final": final}

    if not markers:
        draft = _grounded_fallback_draft(query, retrieved, state)
        markers = [int(m) for m in _MARKER_RE.findall(draft)]
        if not markers:
            final = _insufficient_final(query, retrieved, {}, "The draft did not include source markers, so its claims could not be verified.", state)
            return {**state, "verified_draft": final["answer"], "citation_grades": {}, "verification_grades": {}, "grounding_status": final["grounding_status"], "authority_gaps": final["authority_gaps"], "answer_sections": final["sections"], "insufficient_context": final["insufficient_context"], "final": final}

    sections = _normalised_sections(draft)
    citation_required_text = "\n".join(
        body
        for key, body in sections.items()
        if key not in {"disclaimer", "sources"} and str(body or "").strip()
    )
    uncited_sourced_sentences = missing_citation_sentences(citation_required_text)
    if uncited_sourced_sentences:
        repaired = _regenerate_once(
            {**state, "draft": draft},
            retrieved,
            reason="one or more factual sentences had no citation marker",
        )
        if repaired is not None and not repaired.get("insufficient_context"):
            return repaired
        if int(state.get("regeneration_attempt") or 0) < 1 and state.get("provider") != "extractive_fallback":
            fallback_draft = _grounded_fallback_draft(query, retrieved, {**state, "regeneration_attempt": 1})
            fallback_markers = _markers_in_text(fallback_draft)
            if fallback_markers:
                return verify_citations({**state, "draft": fallback_draft, "provider": "extractive_fallback", "regeneration_attempt": 1})
        final = _insufficient_final(
            query,
            retrieved,
            {},
            "One or more factual sentences had no citation marker, so the answer was rejected.",
            state,
        )
        return {
            **state,
            "verified_draft": final["answer"],
            "citation_grades": {},
            "verification_grades": {},
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"],
            "answer_sections": final["sections"],
            "insufficient_context": True,
            "final": final,
        }

    details = {str(idx): _grade_citation(idx, draft, retrieved, query=query, state=state) for idx in sorted(set(markers))}

    sourced_markers = set(_markers_in_text(sections.get("sourced_authority", "")))
    for marker in sourced_markers:
        if marker < 1 or marker > len(retrieved):
            continue
        detail = details.get(str(marker))
        if not detail:
            continue
        tier = infer_authority_tier(retrieved[marker - 1].get("metadata", {}))
        if not is_merits_citable_tier(tier):
            detail["grade"] = "INCORRECT"
            detail["reason"] = f"sourced authority may only rely on primary authority or case law, not {tier}"

    # Two-pass self-critique: re-check AMBIGUOUS citations via a second Groq call.
    for marker, detail in details.items():
        if detail.get("grade") != "AMBIGUOUS":
            continue
        idx = int(marker)
        if idx < 1 or idx > len(retrieved):
            continue
        claim_text = _claim_before_marker(idx, draft)
        passage_text = (retrieved[idx - 1].get("text") or "")
        if claim_text and passage_text:
            verdict = _two_pass_self_critique(claim_text, passage_text)
            if verdict is not None:
                detail["grade"] = verdict
                detail["self_critique"] = verdict

    grades = {marker: detail["grade"] for marker, detail in details.items()}

    incorrect = [marker for marker, grade in grades.items() if grade == "INCORRECT"]
    ambiguous = [marker for marker, grade in grades.items() if grade == "AMBIGUOUS"]

    if incorrect:
        repaired = _regenerate_once(
            {**state, "draft": draft},
            retrieved,
            reason=f"invalid citation markers: {', '.join(f'[{m}]' for m in incorrect)}",
        )
        if repaired is not None and not repaired.get("insufficient_context"):
            return repaired
        fallback = _try_extractive_retry(state, query, retrieved)
        if fallback is not None and not fallback.get("insufficient_context"):
            return fallback

        reason = (
            "One or more cited claims failed verification against exact retrieved source spans. "
            f"Failed markers: {', '.join(f'[{m}]' for m in incorrect)}."
        )
        final = _insufficient_final(query, retrieved, details, reason, state)
        return {
            **state,
            "verified_draft": final["answer"],
            "citation_grades": grades,
            "verification_grades": details,
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"],
            "answer_sections": final["sections"],
            "insufficient_context": True,
            "final": final,
        }

        correct_count = len([g for g in grades.values() if g == "CORRECT"])
        quote_failures = [
            marker for marker in incorrect
            if details.get(marker, {}).get("quote_match") is False
        ]

        # Strategy A: try grounded fallback draft first (original path).
        if not quote_failures:
            fallback_draft = _grounded_fallback_draft(query, retrieved, state)
            fallback_markers = [int(m) for m in _MARKER_RE.findall(fallback_draft)]
            fallback_details = {
                str(idx): _grade_citation(idx, fallback_draft, retrieved, query=query, state=state)
                for idx in sorted(set(fallback_markers))
            }
            fallback_grades = {marker: detail["grade"] for marker, detail in fallback_details.items()}
            fallback_incorrect = [
                marker for marker, grade in fallback_grades.items() if grade == "INCORRECT"
            ]
            if fallback_markers and not fallback_incorrect:
                verified, final = _build_verified_final(
                    query,
                    fallback_draft,
                    retrieved,
                    fallback_details,
                    state,
                )
                final["rejected_draft"] = _strip_incorrect_markers(draft, details)
                return {
                    **state,
                    "verified_draft": verified,
                    "citation_grades": fallback_grades,
                    "verification_grades": fallback_details,
                    "grounding_status": final["grounding_status"],
                    "authority_gaps": final["authority_gaps"],
                    "answer_sections": final["sections"],
                    "insufficient_context": final["insufficient_context"],
                    "final": final,
                }

        # Strategy B: if at least one citation is CORRECT, strip the failed
        # markers and return a partial answer rather than hard-failing.
        # This prevents total output loss when only a subset of citations fail.
        if correct_count > 0:
            cleaned_draft = _strip_incorrect_markers(draft, details)
            partial_details = {m: d for m, d in details.items() if d["grade"] != "INCORRECT"}
            verified, final = _build_verified_final(
                query,
                cleaned_draft,
                retrieved,
                partial_details,
                state,
            )
            final["partial_verification"] = True
            final["failed_markers"] = incorrect
            return {
                **state,
                "verified_draft": verified,
                "citation_grades": {m: d["grade"] for m, d in partial_details.items()},
                "verification_grades": details,
                "grounding_status": final["grounding_status"],
                "authority_gaps": final["authority_gaps"],
                "answer_sections": final["sections"],
                "insufficient_context": final["insufficient_context"],
                "final": final,
            }

        # Strategy C: all citations failed — produce insufficient_final.
        cleaned = _strip_incorrect_markers(draft, details)
        reason = (
            "All cited claims failed verification. "
            f"Failed markers: {', '.join(f'[{m}]' for m in incorrect)}."
        )
        final = _insufficient_final(query, retrieved, details, reason, state)
        final["rejected_draft"] = cleaned
        return {
            **state,
            "verified_draft": final["answer"],
            "citation_grades": grades,
            "verification_grades": details,
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"],
            "answer_sections": final["sections"],
            "insufficient_context": final["insufficient_context"],
            "final": final,
        }

    if ambiguous:
        repaired = _regenerate_once(
            {**state, "draft": draft},
            retrieved,
            reason=f"ambiguous citation support: {', '.join(f'[{m}]' for m in ambiguous)}",
        )
        if repaired is not None and not repaired.get("insufficient_context"):
            return repaired
        fallback = _try_extractive_retry(state, query, retrieved)
        if fallback is not None and not fallback.get("insufficient_context"):
            return fallback
        final = _insufficient_final(
            query,
            retrieved,
            details,
            "One or more cited claims were ambiguous against retrieved source spans.",
            state,
        )
        return {
            **state,
            "verified_draft": final["answer"],
            "citation_grades": grades,
            "verification_grades": details,
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"],
            "answer_sections": final["sections"],
            "insufficient_context": True,
            "final": final,
        }

    verified, final = _build_verified_final(query, draft, retrieved, details, state)

    # Source-plan sufficiency check: ensure required roles are cited
    correct_markers = [int(m) for m, d in details.items() if d["grade"] == "CORRECT"]
    role_gaps = _check_source_plan_sufficiency(state, correct_markers, retrieved)
    if role_gaps:
        fallback = _try_extractive_retry(state, query, retrieved)
        if fallback is not None and not fallback.get("insufficient_context"):
            return fallback
        final = _insufficient_final(
            query,
            retrieved,
            details,
            "Required source roles were not cited by verified claims: " + "; ".join(role_gaps),
            state,
            cited_markers=correct_markers,
        )
        return {
            **state,
            "verified_draft": final["answer"],
            "citation_grades": grades,
            "verification_grades": details,
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"] + role_gaps,
            "answer_sections": final["sections"],
            "insufficient_context": True,
            "final": final,
        }

    if state.get("provider") == "extractive_fallback":
        confidence_badge = f"_Verification: {len(correct_markers)}/{len(details)} cited source spans verified_"
        final["answer"] = final.get("answer", verified) + f"\n\n{confidence_badge}"
        verified = final["answer"]
        return {
            **state,
            "verified_draft": verified,
            "citation_grades": grades,
            "verification_grades": details,
            "grounding_status": final["grounding_status"],
            "authority_gaps": final["authority_gaps"],
            "answer_sections": final["sections"],
            "insufficient_context": final["insufficient_context"],
            "grounded_ratio": 1.0,
            "confidence_badge": confidence_badge,
            "final": final,
        }

    # Merged: v2 VerificationReport — grounded_ratio, repair pass, confidence badge
    grounded_ratio = 1.0
    confidence_badge = ""
    try:
        from pipeline_v2.citation_verifier import verify as _v2_verify

        vreport = _v2_verify(verified, retrieved)
        grounded_ratio = vreport.grounded_ratio

        # Repair pass: re-call LLM with stricter prompt if too few claims are grounded
        if (
            not vreport.has_insufficient_flag
            and (grounded_ratio < 0.6 or vreport.invalid_citations)
            and state.get("provider", "template_fallback") != "template_fallback"
        ):
            try:
                from src.pipeline.llm import complete
                from src.pipeline.prompts import build_repair_message, system_for

                mode = str(state.get("mode") or "research")
                valid_labels = {f"S{i}" for i in range(1, len(retrieved) + 1)}
                repair_user = build_repair_message(query, retrieved, str(state.get("answer_style") or "long"), valid_labels)
                repaired_text, repair_provider = complete(system_for(mode), repair_user, temperature=0.05)
                repaired_norm = _normalise_marker_groups(_normalise_s_markers(repaired_text))
                repair_report = _v2_verify(repaired_text, retrieved)
                if repair_report.grounded_ratio > grounded_ratio or (
                    not repair_report.invalid_citations and vreport.invalid_citations
                ):
                    # Use repaired draft
                    repair_details = {
                        str(idx): _grade_citation(idx, repaired_norm, retrieved, query=query, state=state)
                        for idx in sorted(set(int(m) for m in _MARKER_RE.findall(repaired_norm)))
                    }
                    repair_grades = {m: d["grade"] for m, d in repair_details.items()}
                    if repair_grades and all(grade == "CORRECT" for grade in repair_grades.values()):
                        verified, final = _build_verified_final(query, repaired_norm, retrieved, repair_details, state)
                        grades = repair_grades
                        grounded_ratio = repair_report.grounded_ratio
            except Exception as _repair_exc:  # noqa: BLE001
                print(f"Warning: repair pass failed: {_repair_exc}")

        confidence_badge = _compute_confidence_badge(
            grounded_ratio,
            vreport.invalid_citations,
            vreport.has_insufficient_flag,
        )
        # Append badge to final answer
        final["answer"] = final.get("answer", verified) + f"\n\n{confidence_badge}"
        verified = final["answer"]
    except Exception as _badge_exc:  # noqa: BLE001
        print(f"Warning: v2 VerificationReport unavailable: {_badge_exc}")

    return {
        **state,
        "verified_draft": verified,
        "citation_grades": grades,
        "verification_grades": details,
        "grounding_status": final["grounding_status"],
        "authority_gaps": final["authority_gaps"],
        "answer_sections": final["sections"],
        "insufficient_context": final["insufficient_context"],
        "grounded_ratio": grounded_ratio,
        "confidence_badge": confidence_badge,
        "final": final,
    }
