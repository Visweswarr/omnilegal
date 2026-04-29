"""
Step 3 — Intent-first retrieval with hard collection filtering
           and semantic quality enforcement.

Key design rules:
  1. HARD FILTER collections before any search — never "search everything"
  2. No fabricated query rewriting — use original + keyword + domain variants
  3. Strict top-k PER COLLECTION (3 each) to prevent one source dominating
  4. DISCARD wrong-jurisdiction results, not penalty
  5. Multiplicative weight boosting, not additive
  6. Pre-retrieval guard: if no valid collections, return early with explanation
  7. KEYWORD ANCHOR: reject passages with zero overlap on key query terms
  8. MINIMUM TERM COVERAGE: passages must match N key terms to survive
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    CASE_LAW_COLLECTIONS,
    COLLECTION_ALIAS_MAP,
    COLLECTION_CASE_LAW,
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_US,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_REFERENCE_DATASET_EU,
    COLLECTION_REFERENCE_DATASET_GLOBAL,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    RERANK_TOP_N,
)
from src.pipeline.state import PipelineStateDict
from src.services.authority import (
    annotate_authority_tier,
    authority_rank,
    infer_authority_tier,
)

_CASE_ENTITY_LABELS = {"icj case", "legal_case", "legal case", "arbitration case", "international arbitration"}

# ── Country code → NATIONAL collection mapping ────────────────────────────
_ISO_TO_NATIONAL = {
    "in": COLLECTION_NATIONAL_IN,
    "us": COLLECTION_NATIONAL_US,
    "gb": COLLECTION_NATIONAL_UK,
    "uk": COLLECTION_NATIONAL_UK,
    "eu": COLLECTION_NATIONAL_EU,
    "ru": COLLECTION_NATIONAL_RU,
    "il": COLLECTION_NATIONAL_IL,
}

_ISO_TO_PHYSICAL = {
    "in": [COLLECTION_STATUTES_IN, COLLECTION_CASE_LAW_IN],
    "us": [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    "gb": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "uk": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "eu": [COLLECTION_STATUTES_EU, COLLECTION_CASE_LAW_EU],
    "ru": [COLLECTION_STATUTES_RU, COLLECTION_CASE_LAW_RU],
    "il": [COLLECTION_STATUTES_IL, COLLECTION_CASE_LAW_IL],
}

_ISO_TO_CASE = {
    "in": COLLECTION_CASE_LAW_IN,
    "us": COLLECTION_CASE_LAW_US,
    "gb": COLLECTION_CASE_LAW_UK,
    "uk": COLLECTION_CASE_LAW_UK,
    "eu": COLLECTION_CASE_LAW_EU,
    "ru": COLLECTION_CASE_LAW_RU,
    "il": COLLECTION_CASE_LAW_IL,
}

# All NATIONAL_* collection names for fast membership checks
_ALL_NATIONAL_COLLECTIONS = {
    COLLECTION_NATIONAL_IN, COLLECTION_NATIONAL_US, COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_EU, COLLECTION_NATIONAL_RU, COLLECTION_NATIONAL_IL,
    COLLECTION_STATUTES_IN, COLLECTION_STATUTES_US, COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_EU, COLLECTION_STATUTES_RU, COLLECTION_STATUTES_IL,
}

_TOP_K_PER_COLLECTION = 5  # strict cap per collection
_MIN_TERM_OVERLAP_RATIO = 0.3  # FIX 1: dynamic — overlap >= max(2, len(terms) * ratio)
_MIN_TERM_OVERLAP_FLOOR = 2    # absolute minimum

# ── Legal concept synonyms — jurisdiction-aware (FIX 2) ───────────────────
# Each synonym is tagged with which jurisdictions it applies to.
# "*" = universal, "IN" = India only, "US" = US only, etc.
_LEGAL_SYNONYMS: dict[str, list[tuple[str, str]]] = {
    "freedom of speech": [
        ("freedom of expression", "*"),
        ("article 19", "IN"),        # India constitution
        ("first amendment", "US"),   # US constitution — NOT for India queries
        ("free speech", "*"),
        ("right to expression", "*"),
    ],
    "freedom of expression": [
        ("freedom of speech", "*"),
        ("article 19", "IN"),
        ("first amendment", "US"),
        ("free speech", "*"),
    ],
    "death penalty": [
        ("capital punishment", "*"),
        ("execution", "*"),
        ("death sentence", "*"),
        ("right to life", "*"),
        ("eighth amendment", "US"),
        ("article 21", "IN"),
    ],
    "capital punishment": [
        ("death penalty", "*"),
        ("execution", "*"),
        ("death sentence", "*"),
    ],
    "erga omnes": [
        ("obligations erga omnes", "*"),
        ("obligations owed to all", "*"),
        ("community obligations", "*"),
        ("barcelona traction", "*"),
    ],
    "jus cogens": [
        ("peremptory norm", "*"),
        ("peremptory norms", "*"),
        ("non-derogable", "*"),
    ],
    "state responsibility": [
        ("international responsibility", "*"),
        ("state wrongful act", "*"),
        ("ILC articles", "*"),
    ],
    "self-defense": [
        ("self-defence", "*"),
        ("article 51", "*"),
        ("anticipatory self-defense", "*"),
        ("inherent right", "*"),
    ],
    "self-defence": [
        ("self-defense", "*"),
        ("article 51", "*"),
        ("anticipatory self-defence", "*"),
    ],
    "sovereignty": [
        ("territorial sovereignty", "*"),
        ("sovereign rights", "*"),
        ("sovereign equality", "*"),
    ],
    "territorial sovereignty": [
        ("sovereignty", "*"),
        ("territorial integrity", "*"),
    ],
    "human rights": [
        ("fundamental rights", "*"),
        ("civil liberties", "*"),
        ("ICCPR", "*"),
        ("UDHR", "*"),
    ],
    "right to life": [
        ("article 21", "IN"),
        ("article 6 ICCPR", "*"),
    ],
    "torture": [
        ("CAT", "*"),
        ("prohibition of torture", "*"),
        ("cruel inhuman", "*"),
        ("degrading treatment", "*"),
    ],
    "genocide": [
        ("genocide convention", "*"),
        ("crime of genocide", "*"),
    ],
    "use of force": [
        ("article 2(4)", "*"),
        ("prohibition of force", "*"),
        ("armed attack", "*"),
    ],
    "immunity": [
        ("sovereign immunity", "*"),
        ("state immunity", "*"),
        ("diplomatic immunity", "*"),
    ],
    "diplomatic immunity": [
        ("vienna convention on diplomatic relations", "*"),
        ("diplomatic privileges", "*"),
        ("consular immunity", "*"),
        ("inviolability", "*"),
        ("persona non grata", "*"),
        ("diplomatic agent", "*"),
        ("immunity from jurisdiction", "*"),
    ],
    "extradition": [
        ("extradite", "*"),
        ("surrender", "*"),
    ],
    "refugee": [
        ("refugee convention", "*"),
        ("asylum", "*"),
        ("non-refoulement", "*"),
    ],
    "non-refoulement": [
        ("refugee", "*"),
        ("asylum", "*"),
        ("prohibition of return", "*"),
    ],
}

# FIX 5: Negative keyword domains — passages with these terms are penalized
# when they don't appear in the query itself.
_NEGATIVE_DOMAIN_TERMS: dict[str, set[str]] = {
    # When searching for speech/expression, tax/property/zoning = irrelevant
    "freedom of speech": {"tax", "property", "zoning", "bankruptcy", "patent", "trademark"},
    "freedom of expression": {"tax", "property", "zoning", "bankruptcy"},
    "death penalty": {"tax", "property", "trademark", "patent", "zoning", "commercial"},
    "erga omnes": {"tax", "property", "trademark", "patent", "zoning", "commercial", "rental"},
    "human rights": {"tax", "property", "patent", "trademark", "zoning", "bankruptcy"},
    "sovereignty": {"tax", "bankruptcy", "patent", "trademark"},
}

_COUNTRY_QUERY_PATTERNS = [
    ("IN", (r"\bindia\b", r"\bindian\b")),
    ("US", (r"\bunited states\b", r"\bu\.?s\.?a?\b", r"\bamerican\b")),
    ("GB", (r"\bunited kingdom\b", r"\buk\b", r"\bbritish\b", r"\bgreat britain\b")),
    ("EU", (r"\beuropean union\b", r"\beu\b", r"\beuropean\b")),
    ("RU", (r"\brussia\b", r"\brussian federation\b", r"\brussian\b")),
    ("IL", (r"\bisrael\b", r"\bisraeli\b")),
]

_JURISDICTION_ALIASES = {
    "in": "in", "india": "in", "indian": "in",
    "us": "us", "usa": "us", "u.s.": "us", "united states": "us", "american": "us",
    "gb": "gb", "uk": "gb", "united kingdom": "gb", "british": "gb", "great britain": "gb",
    "eu": "eu", "european union": "eu", "european": "eu",
    "ru": "ru", "russia": "ru", "russian federation": "ru", "russian": "ru",
    "il": "il", "israel": "il", "israeli": "il",
    "international": "international", "intl": "international", "global": "international",
    "un": "international", "united nations": "international", "icj": "international",
}

_COLLECTION_JURISDICTIONS = {
    COLLECTION_NATIONAL_IN: "in",
    COLLECTION_NATIONAL_US: "us",
    COLLECTION_NATIONAL_UK: "gb",
    COLLECTION_NATIONAL_EU: "eu",
    COLLECTION_NATIONAL_RU: "ru",
    COLLECTION_NATIONAL_IL: "il",
    COLLECTION_STATUTES_IN: "in",
    COLLECTION_STATUTES_US: "us",
    COLLECTION_STATUTES_UK: "gb",
    COLLECTION_STATUTES_EU: "eu",
    COLLECTION_STATUTES_RU: "ru",
    COLLECTION_STATUTES_IL: "il",
    COLLECTION_CASE_LAW_IN: "in",
    COLLECTION_CASE_LAW_US: "us",
    COLLECTION_CASE_LAW_UK: "gb",
    COLLECTION_CASE_LAW_EU: "eu",
    COLLECTION_CASE_LAW_RU: "ru",
    COLLECTION_CASE_LAW_IL: "il",
    COLLECTION_CASE_LAW_GLOBAL: "international",
    COLLECTION_COMMENTARY_GLOBAL: "international",
    COLLECTION_INTL_TREATIES: "international",
    COLLECTION_SHAW_PRIVATE: "international",
    COLLECTION_COMMENTARY: "international",
    COLLECTION_REFERENCE_DATASET_GLOBAL: "international",
    COLLECTION_REFERENCE_DATASET_EU: "eu",
}

_REFERENCE_DATASET_COLLECTIONS = {
    COLLECTION_REFERENCE_DATASET_GLOBAL,
    COLLECTION_REFERENCE_DATASET_EU,
}
_CROSS_BORDER_SCENARIO_RE = re.compile(
    r"\b(passport|visa|driving licen[cs]e|driver'?s licen[cs]e|international driving permit|foreign licen[cs]e|arrest|detention|custody|consular|embassy|border|immigration|deport)\b",
    re.IGNORECASE,
)


def _extract_iso_codes(query: str, issue_profile: dict) -> list[str]:
    """Combine pipeline country detection with conservative raw-query matching."""
    codes: list[str] = []
    seen: set[str] = set()
    for code in issue_profile.get("iso_country_codes", []) or []:
        normalized = str(code or "").upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            codes.append(normalized)

    for code, patterns in _COUNTRY_QUERY_PATTERNS:
        if code in seen:
            continue
        if any(re.search(pattern, query, flags=re.IGNORECASE) for pattern in patterns):
            seen.add(code)
            codes.append(code)
    return codes


def _query_requests_case_law(query: str) -> bool:
    return bool(re.search(
        r"\b(case law|cases?|judgments?|judgements?|precedents?|court|supreme court|holding|decision)\b",
        query,
        flags=re.IGNORECASE,
    ))


def _source_discovery_query(query: str) -> bool:
    return bool(re.search(
        r"\b(sources?|datasets?|corpus|available|ingested|downloaded|license|api|coverage|blocked)\b",
        query,
        flags=re.IGNORECASE,
    ))


def _infer_intent_primary(
    query: str,
    intent_primary: list[str],
    iso_codes: list[str],
    has_named_case: bool,
) -> list[str]:
    """Backstop intent inference when upstream state is missing or too weak."""
    primary = [str(item) for item in intent_primary if item]
    if primary and primary != ["mixed"]:
        return primary

    lowered = query.lower()
    inferred: list[str] = []
    if len(iso_codes) >= 2 and _CROSS_BORDER_SCENARIO_RE.search(lowered):
        inferred.append("cross_border_scenario")
    if re.search(r"\b(compare|contrast|difference between|versus|vs\.?)\b", lowered) or len(iso_codes) >= 2:
        inferred.append("jurisdiction_comparison")
    if has_named_case:
        inferred.append("named_case")
    if re.search(
        r"\b(what is|what are|explain|tell me about|doctrine|principle|concept|meaning|is .+ lawful|is .+ legal|freedom|right to|death penalty|erga omnes|jus cogens)\b",
        lowered,
    ):
        inferred.append("conceptual")
    if not inferred and iso_codes:
        inferred.append("country")
    if not inferred:
        inferred.append("conceptual")
    return _dedup(inferred)


def _normalize_jurisdiction(value: str) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not cleaned:
        return ""
    return _JURISDICTION_ALIASES.get(cleaned, cleaned)


def _hit_collection(hit: dict) -> str:
    metadata = hit.get("metadata", {}) or {}
    collection = str(metadata.get("collection") or metadata.get("qdrant_collection") or "").upper()
    return collection


def _collection_jurisdiction(collection: str) -> str:
    return _COLLECTION_JURISDICTIONS.get(str(collection or "").upper(), "")


# ── Quality layer: key terms, anchor filter, phrase matching ──────────────

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "about", "with", "from",
    "into", "through", "during", "before", "after", "above", "below",
    "to", "for", "of", "on", "at", "by", "in", "tell", "me", "brief",
    "explain", "what", "how", "compare", "between", "and", "or", "but",
    "if", "when", "where", "why", "this", "that", "these", "those",
    "i", "am", "get", "out", "case", "having", "without", "not",
}

_COMMON_QUERY_PHRASES = [
    "driving licence",
    "driving license",
    "international driving permit",
    "foreign driving licence",
    "foreign driving license",
    "indian passport",
    "consular notification",
    "consular access",
    "administrative offence",
    "administrative offense",
    "criminal procedure",
    "traffic offence",
    "traffic offense",
]


def _get_jurisdiction_filtered_synonyms(concept: str, iso_codes: list[str]) -> list[str]:
    """FIX 2: Return only synonyms valid for the detected jurisdictions.

    'first amendment' is excluded for India queries.
    'article 19' is excluded for US queries.
    '*' synonyms are always included.
    """
    entries = _LEGAL_SYNONYMS.get(concept, [])
    if not entries:
        return []
    if not iso_codes:
        # No jurisdiction constraint — include universal synonyms only
        return [syn for syn, jur in entries if jur == "*"]
    allowed_jurs = {code.upper() for code in iso_codes} | {"*"}
    return [syn for syn, jur in entries if jur in allowed_jurs]


def _extract_key_terms(query: str, iso_codes: list[str] | None = None) -> set[str]:
    """Extract the substantive terms from a query for keyword anchoring.

    Strips stop words, keeps legal terms, and expands via jurisdiction-aware
    domain synonyms.
    """
    words = re.findall(r"[a-z][a-z0-9]+", query.lower())
    key_terms = {w for w in words if w not in _STOP_WORDS and len(w) > 2}

    # Expand with jurisdiction-filtered synonyms (FIX 2)
    lowered = query.lower()
    for concept in _LEGAL_SYNONYMS:
        if concept in lowered:
            filtered_syns = _get_jurisdiction_filtered_synonyms(concept, iso_codes or [])
            for syn in filtered_syns:
                for word in re.findall(r"[a-z][a-z0-9]+", syn.lower()):
                    if len(word) > 2 and word not in _STOP_WORDS:
                        key_terms.add(word)

    # Remove very generic legal terms that match everything
    key_terms -= {"law", "legal", "case", "court", "right", "rights", "act", "section", "free"}
    return key_terms


def _extract_query_phrases(query: str) -> list[str]:
    """FIX 3: Extract multi-word legal phrases for phrase-level matching."""
    lowered = query.lower()
    phrases = []
    # Check for known legal concepts as phrases
    for concept in _LEGAL_SYNONYMS:
        if concept in lowered:
            phrases.append(concept)
    for phrase in _COMMON_QUERY_PHRASES:
        if phrase in lowered:
            phrases.append(phrase)
    # Also extract quoted phrases
    for m in re.finditer(r'"([^"]{3,60})"', query):
        phrases.append(m.group(1).lower())
    return phrases


def _scenario_anchor_terms(
    *,
    intent_primary: list[str],
    issue_labels: list[str],
    scenario_context: dict[str, Any] | None,
) -> tuple[set[str], list[str]]:
    if "cross_border_scenario" not in intent_primary:
        return set(), []

    extra_terms = {
        "foreign",
        "driving",
        "licence",
        "license",
        "permit",
        "traffic",
        "road",
        "administrative",
    }
    extra_phrases = [
        "foreign driving licence",
        "foreign driving license",
        "international driving permit",
        "road traffic",
        "road traffic safety",
        "administrative offence",
        "administrative offense",
    ]

    if {"criminal_procedure", "consular_assistance", "immigration_and_mobility"} & set(issue_labels):
        extra_terms |= {"consular", "notification", "access", "detention", "interpreter", "lawyer", "police"}
        extra_phrases.extend([
            "consular notification",
            "consular access",
            "vienna convention on consular relations",
        ])

    if "criminal_procedure" in issue_labels:
        extra_terms |= {"criminal", "procedure", "counsel"}
        extra_phrases.extend([
            "criminal procedure",
            "criminal procedure code",
            "federal law on police",
        ])

    treaty_focus = set((scenario_context or {}).get("treaty_focus") or [])
    if "foreign_licence_recognition" in treaty_focus:
        extra_terms |= {"recognition"}
        extra_phrases.append("convention on road traffic")
    if "consular_notification" in treaty_focus:
        extra_terms |= {"foreign", "national"}

    return extra_terms, extra_phrases


def _compute_dynamic_min_overlap(key_terms: set[str]) -> int:
    """FIX 1: Dynamic minimum overlap: max(2, len(terms) * 0.3).

    Single-word overlap like 'freedom' matching 'freedom of movement in Canada'
    is NOT enough.
    """
    return max(_MIN_TERM_OVERLAP_FLOOR, int(len(key_terms) * _MIN_TERM_OVERLAP_RATIO))


def _negative_keyword_penalty(query: str, text: str) -> float:
    """FIX 5: Penalize passages with unrelated domain terms.

    If the query is about 'freedom of speech' and the passage mentions
    'tax assessment' or 'property valuation', it's almost certainly irrelevant.
    Returns a negative penalty (0.0 = no penalty, -5.0 = strong penalty).
    """
    lowered = query.lower()
    text_lower = text.lower()
    for concept, negative_terms in _NEGATIVE_DOMAIN_TERMS.items():
        if concept in lowered:
            neg_count = sum(1 for term in negative_terms if term in text_lower)
            if neg_count >= 2:
                return -5.0  # Strong penalty: multiple unrelated domain terms
            elif neg_count == 1:
                return -2.0
    return 0.0


def _keyword_anchor_filter(
    hits: list[dict],
    key_terms: set[str],
    query_phrases: list[str],
    query: str,
) -> list[dict]:
    """Reject passages below the dynamic overlap threshold.

    Also applies:
    - FIX 3: phrase-level match boost (exact phrase = +2.0 score)
    - FIX 5: negative keyword penalty
    - FIX 7: explainability (selection_reason on each passage)
    """
    if not key_terms:
        return hits

    min_overlap = _compute_dynamic_min_overlap(key_terms)

    filtered = []
    for h in hits:
        text_lower = h.get("text", "").lower()
        meta = h.get("metadata", {}) or {}
        source_lower = str(meta.get("source_name", "")).lower()
        alias_parts = [
            str(meta.get("source_name", "")),
            str(meta.get("citation", "")),
            str(meta.get("case_name", "")),
            str(meta.get("english_title", "")),
            str(meta.get("translated_title", "")),
            str(meta.get("keyword_aliases", "")),
        ]
        alias_text = " ".join(alias_parts).lower()
        haystack = text_lower + " " + source_lower + " " + alias_text

        # Term overlap count
        matched_terms = [term for term in key_terms if term in haystack]
        overlap = len(matched_terms)

        # FIX 3: Phrase-level boost
        phrase_bonus = 0.0
        matched_phrases = []
        for phrase in query_phrases:
            if phrase in haystack:
                phrase_bonus += 2.0
                matched_phrases.append(phrase)

        # FIX 5: Negative keyword penalty
        neg_penalty = _negative_keyword_penalty(query, h.get("text", ""))

        # Effective overlap: if a phrase matches, it counts as extra term matches
        effective_overlap = overlap + (2 * len(matched_phrases))

        if effective_overlap >= min_overlap:
            h["term_overlap"] = overlap
            h["phrase_matches"] = matched_phrases
            h["phrase_bonus"] = phrase_bonus
            h["neg_penalty"] = neg_penalty
            # FIX 7: Explainability — WHY this passage was selected
            h["selection_reason"] = (
                f"matched {overlap}/{len(key_terms)} key terms: {matched_terms[:5]}; "
                f"phrases: {matched_phrases or 'none'}; "
                f"collection: {meta.get('collection', '?')}; "
                f"neg_penalty: {neg_penalty}"
            )
            filtered.append(h)

    return filtered


_CASE_ANCHOR_STOP_WORDS = {
    "case", "advisory", "opinion", "judgment", "judgement", "arbitration",
    "award", "decision", "court", "legal", "law", "the", "and", "for",
}


def _case_anchor_filter(hits: list[dict], case_names: list[str]) -> list[dict]:
    """For named-case queries, keep passages tied to at least one named case."""
    anchors: list[set[str]] = []
    for name in case_names:
        tokens = {
            token
            for token in re.findall(r"[a-z][a-z0-9]+", str(name).lower())
            if len(token) > 3 and token not in _CASE_ANCHOR_STOP_WORDS
        }
        if tokens:
            anchors.append(tokens)
    if not anchors:
        return hits

    filtered: list[dict] = []
    for hit in hits:
        meta = hit.get("metadata", {}) or {}
        haystack = " ".join(
            str(part or "")
            for part in [
                meta.get("source_name"),
                meta.get("citation"),
                hit.get("text"),
            ]
        ).lower()
        if any(any(token in haystack for token in tokens) for tokens in anchors):
            filtered.append(hit)
    return filtered


def _build_query_variants(
    query: str,
    intent_primary: list[str],
    iso_codes: list[str],
    case_names: list[str] | None = None,
    issue_labels: list[str] | None = None,
    local_model_hints: list[str] | None = None,
) -> list[str]:
    """Build retrieval query variants from the original query.

    Rules:
      - Always include the original query verbatim
      - Create a keyword-only version (stop words removed)
      - Add jurisdiction-aware synonym expansion variant
      - NEVER fabricate case names, party names, or legal citations
    """
    original = query.strip()
    variants = [original]

    # Keyword variant
    words = query.split()
    keywords = [w for w in words if w.lower() not in _STOP_WORDS and len(w) > 1]
    if keywords and len(keywords) < len(words):
        variants.append(" ".join(keywords))

    # Jurisdiction-aware synonym expansion (FIX 2)
    lowered = query.lower()
    synonym_parts: list[str] = []
    for concept in _LEGAL_SYNONYMS:
        if concept in lowered:
            filtered_syns = _get_jurisdiction_filtered_synonyms(concept, iso_codes)
            synonym_parts.extend(filtered_syns[:2])
    if synonym_parts:
        syn_query = " ".join(keywords) + " " + " ".join(synonym_parts)
        variants.append(syn_query.strip())

    if "cross_border_scenario" in intent_primary:
        cross_border_variants = [
            "foreign driving licence international driving permit recognition administrative offence",
            "consular notification consular access interpreter lawyer detention rights",
            "traffic offence police stop administrative fine criminal procedure appeal",
        ]
        if "traffic_offences" in (issue_labels or []):
            cross_border_variants.append("road safety foreign licence driver licensing motor vehicle law")
        if "criminal_procedure" in (issue_labels or []):
            cross_border_variants.append("arrest detention custody charge interpreter defence counsel")
        if "consular_assistance" in (issue_labels or []):
            cross_border_variants.append("vienna convention consular relations embassy notification access")
        if "RU" in [code.upper() for code in iso_codes]:
            cross_border_variants.append("Russia foreign driving licence administrative offence road safety police supervision")
        if "IN" in [code.upper() for code in iso_codes]:
            cross_border_variants.append("India motor vehicles act driving licence international driving permit")
        variants.extend(cross_border_variants)

    for hint in local_model_hints or []:
        clean_hint = " ".join(str(hint).split()).strip()
        if clean_hint:
            variants.append(clean_hint)

    for case_name in case_names or []:
        clean = case_name.strip()
        if not clean:
            continue
        variants.append(clean)
        variants.append(f"{clean} facts holding reasoning legal principle")

    return _dedup(variants)


# ── FIX 1: Hard collection filter based on intent ─────────────────────────

def _hard_filter_collections(
    intent_primary: list[str],
    iso_codes: list[str],
    has_named_case: bool,
    query_requests_cases: bool,
) -> list[str]:
    """Determine the EXACT set of collections to search.

    This is a hard filter — collections NOT in this list are never searched.
    No "search everything and hope reranking fixes it."
    """
    collections: list[str] = []

    # Map ISO codes to their NATIONAL collections
    relevant_nationals = []
    for code in iso_codes:
        col = _ISO_TO_NATIONAL.get(code.lower())
        if col:
            relevant_nationals.append(col)

    # ── Named case / case comparison: focus on case sources ────────────
    if "named_case" in intent_primary or "case_comparison" in intent_primary:
        collections = [COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY]
        if relevant_nationals:
            collections.extend(relevant_nationals)
        return _dedup(collections)

    if "cross_border_scenario" in intent_primary:
        for code in iso_codes:
            collections.extend(_ISO_TO_PHYSICAL.get(code.lower(), []))
        collections.extend([
            COLLECTION_INTL_TREATIES,
            COLLECTION_CASE_LAW_GLOBAL,
            COLLECTION_COMMENTARY,
            COLLECTION_COMMENTARY_GLOBAL,
            COLLECTION_SHAW_PRIVATE,
            COLLECTION_REFERENCE_DATASET_GLOBAL,
            COLLECTION_REFERENCE_DATASET_EU,
        ])
        return _dedup(collections)

    # ── Jurisdiction comparison: ONLY the relevant national collections ──
    if "jurisdiction_comparison" in intent_primary:
        if relevant_nationals:
            collections = list(relevant_nationals)
        collections.extend([
            COLLECTION_COMMENTARY,
            COLLECTION_SHAW_PRIVATE,
            COLLECTION_INTL_TREATIES,
            COLLECTION_REFERENCE_DATASET_GLOBAL,
            COLLECTION_REFERENCE_DATASET_EU,
        ])
        # EXCLUDE global CASE_LAW — it floods with irrelevant results
        return _dedup(collections)

    # ── Conceptual: commentary + textbooks, case law only if named case ──
    if "conceptual" in intent_primary:
        collections = [
            COLLECTION_COMMENTARY,
            COLLECTION_SHAW_PRIVATE,
            COLLECTION_INTL_TREATIES,
            COLLECTION_REFERENCE_DATASET_GLOBAL,
            COLLECTION_REFERENCE_DATASET_EU,
        ]
        if has_named_case or query_requests_cases:
            if iso_codes:
                collections.extend(_ISO_TO_CASE.get(code.lower(), COLLECTION_CASE_LAW_GLOBAL) for code in iso_codes)
            else:
                collections.append(COLLECTION_CASE_LAW)
        if relevant_nationals:
            collections.extend(relevant_nationals)
        return _dedup(collections)

    # ── Country-specific (non-comparative): ONLY that country + commentary ─
    if iso_codes and "jurisdiction_comparison" not in intent_primary:
        if relevant_nationals:
            collections = list(relevant_nationals)
        collections.extend([COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY, COLLECTION_SHAW_PRIVATE])
        if has_named_case or query_requests_cases:
            collections.extend(_ISO_TO_CASE.get(code.lower(), COLLECTION_CASE_LAW_GLOBAL) for code in iso_codes)
        return _dedup(collections)

    # ── Mixed / general: broad but still structured ───────────────────
    collections = [
        COLLECTION_SHAW_PRIVATE,
        COLLECTION_COMMENTARY,
        COLLECTION_INTL_TREATIES,
        COLLECTION_REFERENCE_DATASET_GLOBAL,
        COLLECTION_REFERENCE_DATASET_EU,
    ]
    if has_named_case:
        collections.insert(0, COLLECTION_CASE_LAW)
    if relevant_nationals:
        collections.extend(relevant_nationals)
    return _dedup(collections)


def _dedup(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _expand_collection_aliases(collections: list[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for collection in collections:
        targets = COLLECTION_ALIAS_MAP.get(collection, [collection])
        for target in targets:
            if target not in seen:
                seen.add(target)
                expanded.append(target)
    return expanded


# ── FIX 4: Hard jurisdiction discard filter ───────────────────────────────

def _jurisdiction_discard(
    hits: list[dict],
    iso_codes: list[str],
    intent_primary: list[str],
    *,
    query: str = "",
) -> list[dict]:
    """Remove results from wrong jurisdictions.

    For comparative queries, keep all jurisdictions that were requested.
    For single-jurisdiction queries, DISCARD anything from another domestic jurisdiction.
    International sources are always kept.
    """
    if not iso_codes:
        if _source_discovery_query(query):
            return hits
        return [
            h for h in hits
            if str((h.get("metadata", {}) or {}).get("doc_type", "")).lower() != "source_catalog"
        ]

    # For comparative queries, allow all requested jurisdictions
    if "jurisdiction_comparison" in intent_primary or "case_comparison" in intent_primary or "cross_border_scenario" in intent_primary:
        allowed = {_normalize_jurisdiction(code) for code in iso_codes} | {"international"}
    else:
        # Single jurisdiction: only allow THAT jurisdiction + international
        allowed = {_normalize_jurisdiction(code) for code in iso_codes} | {"international"}

    filtered = []
    for h in hits:
        metadata = h.get("metadata", {}) or {}
        doc_type = str(metadata.get("doc_type", "")).lower()
        collection = _hit_collection(h)
        meta_jur = _normalize_jurisdiction(str(metadata.get("jurisdiction", "")))
        collection_jur = _collection_jurisdiction(collection)
        effective_jur = meta_jur or collection_jur

        if doc_type == "source_catalog" and not _source_discovery_query(query):
            continue

        # NATIONAL collections: ONLY allow if jurisdiction matches
        if collection in _ALL_NATIONAL_COLLECTIONS and collection_jur not in allowed:
            continue

        # CASE_LAW: ONLY allow if jurisdiction matches or unknown
        if collection == COLLECTION_CASE_LAW or collection in CASE_LAW_COLLECTIONS:
            if effective_jur and effective_jur not in allowed:
                continue

        # International sources (commentary, treaties, shaw): ALWAYS keep
        if collection in {COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL, COLLECTION_INTL_TREATIES, COLLECTION_SHAW_PRIVATE, COLLECTION_CASE_LAW_GLOBAL}:
            filtered.append(h)
            continue

        # For other sources: keep if jurisdiction matches or is unknown
        if not effective_jur or effective_jur in allowed:
            filtered.append(h)

    return filtered


# ── Noise source hard filter ──────────────────────────────────────────────

_NOISE_SOURCES = {"nato", "unctad", "african court", "isds"}


def _discard_noise(hits: list[dict], query: str) -> list[dict]:
    """Hard remove noise sources unless the query explicitly mentions them."""
    query_lower = query.lower()
    # If the query mentions a noise source, don't filter it
    query_mentions_noise = any(noise in query_lower for noise in _NOISE_SOURCES)
    if query_mentions_noise:
        return hits

    filtered = []
    for h in hits:
        source = str(h.get("metadata", {}).get("source_name", "")).lower()
        if any(noise in source for noise in _NOISE_SOURCES):
            continue  # DISCARD, not penalty
        filtered.append(h)
    return filtered


# ── Case entity helpers ───────────────────────────────────────────────────

def _has_case_entity(state: PipelineStateDict) -> bool:
    entities = (state.get("entities") or {}).get("entities") or []
    return any(e.get("label", "").lower() in _CASE_ENTITY_LABELS for e in entities)


def _named_case_entities(state: PipelineStateDict) -> list[str]:
    entities = (state.get("entities") or {}).get("entities") or []
    return [
        e["text"] for e in entities
        if e.get("label", "").lower() in _CASE_ENTITY_LABELS
    ]


# ── Second pass for named cases ───────────────────────────────────────────

def _second_pass_case_retrieval(
    case_names: list[str],
    primary_results: dict[str, list],
    *,
    iso_codes: list[str],
    intent_primary: list[str],
    collection_weights: dict[str, float],
    query: str,
) -> dict[str, list]:
    """For each named case run targeted sub-queries for facts/holding/reasoning."""
    from src.rag.retriever import hybrid_search

    aspects = ["facts", "holding", "reasoning", "legal principle"]
    for case_name in case_names[:3]:
        for aspect in aspects:
            sub_query = f"{case_name} {aspect}"
            for col in (*CASE_LAW_COLLECTIONS, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE):
                try:
                    hits = hybrid_search(sub_query, col, k=max(_TOP_K_PER_COLLECTION * 2, 6))
                    for hit in hits:
                        metadata = hit.setdefault("metadata", {})
                        if isinstance(metadata, dict):
                            metadata.setdefault("collection", col)
                    hits = _jurisdiction_discard(hits, iso_codes, intent_primary, query=query)
                    hits = _discard_noise(hits, query)
                    hits = _apply_collection_weight(hits, collection_weights.get(col, 1.0))
                    if hits:
                        existing = primary_results.get(col, [])
                        existing_prefixes = {h["text"][:80] for h in existing}
                        new_hits = [h for h in hits if h["text"][:80] not in existing_prefixes]
                        primary_results[col] = existing + new_hits[:3]
                except Exception:
                    pass
    return primary_results


# ── FIX 5: Multiplicative weight application ─────────────────────────────

def _apply_collection_weight(hits: list[dict], weight: float) -> list[dict]:
    """Apply multiplicative weight to scores — weight DOMINATES, not suggests."""
    for h in hits:
        h["score"] = h.get("score", 0.0) * weight
        h["collection_weight"] = weight
        metadata = h.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["collection_weight"] = weight
    return hits


# ── Collection weight assignment ──────────────────────────────────────────

def _get_collection_weights(
    collections: list[str],
    intent_primary: list[str],
    iso_codes: list[str],
    has_named_case: bool,
) -> dict[str, float]:
    """Assign multiplicative weights — these MULTIPLY scores, not add."""
    weights: dict[str, float] = {col: 1.0 for col in collections}

    if "named_case" in intent_primary or "case_comparison" in intent_primary:
        for col in [COLLECTION_CASE_LAW, *CASE_LAW_COLLECTIONS]:
            if col in weights:
                weights[col] = 3.0
        if COLLECTION_SHAW_PRIVATE in weights:
            weights[COLLECTION_SHAW_PRIVATE] = 2.5

    if "conceptual" in intent_primary:
        for col in (COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL):
            if col in weights:
                weights[col] = 3.0
        if COLLECTION_SHAW_PRIVATE in weights:
            weights[COLLECTION_SHAW_PRIVATE] = 2.5
        for col in _REFERENCE_DATASET_COLLECTIONS:
            if col in weights:
                weights[col] = 0.6
        for col in [COLLECTION_CASE_LAW, *CASE_LAW_COLLECTIONS]:
            if col in weights:
                weights[col] = 0.5  # Actively deweight

    if "cross_border_scenario" in intent_primary:
        for col in (COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL):
            if col in weights:
                weights[col] = 2.4
        if COLLECTION_CASE_LAW_GLOBAL in weights:
            weights[COLLECTION_CASE_LAW_GLOBAL] = 1.8
        if COLLECTION_SHAW_PRIVATE in weights:
            weights[COLLECTION_SHAW_PRIVATE] = 1.6
        for col in _REFERENCE_DATASET_COLLECTIONS:
            if col in weights:
                weights[col] = 0.45
        for code in iso_codes:
            for col in _ISO_TO_PHYSICAL.get(code.lower(), []):
                if col and col in weights:
                    weights[col] = 3.2

    if "jurisdiction_comparison" in intent_primary:
        for col in (COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL):
            if col in weights:
                weights[col] = 2.0
        for col in _REFERENCE_DATASET_COLLECTIONS:
            if col in weights:
                weights[col] = 0.5
        for code in iso_codes:
            for col in _ISO_TO_PHYSICAL.get(code.lower(), []):
                if col and col in weights:
                    weights[col] = 2.5

    # For country-specific queries, boost that country's collection
    if iso_codes and "jurisdiction_comparison" not in intent_primary:
        for code in iso_codes:
            for col in _ISO_TO_PHYSICAL.get(code.lower(), []):
                if col and col in weights:
                    weights[col] = 3.0

    return weights


def _annotate_retrieved_hits(hits: list[dict]) -> list[dict]:
    annotated: list[dict] = []
    for hit in hits:
        metadata = annotate_authority_tier(hit.get("metadata") or {})
        annotated.append({**hit, "metadata": metadata, "authority_tier": metadata["authority_tier"]})
    return annotated


def _scenario_relevance_score(
    hit: dict[str, Any],
    *,
    intent_primary: list[str],
    issue_labels: list[str],
    scenario_context: dict[str, Any] | None,
) -> float:
    if "cross_border_scenario" not in intent_primary:
        return 0.0

    meta = hit.get("metadata", {}) or {}
    collection = str(meta.get("collection") or "").upper()
    jurisdiction = _normalize_jurisdiction(meta.get("jurisdiction", ""))
    text = " ".join(
        str(part or "")
        for part in [
            meta.get("source_name"),
            meta.get("citation"),
            hit.get("text"),
        ]
    ).lower()

    location_iso = _normalize_jurisdiction((scenario_context or {}).get("location_iso", ""))
    passport_iso = _normalize_jurisdiction((scenario_context or {}).get("passport_iso", ""))
    licence_iso = _normalize_jurisdiction((scenario_context or {}).get("licence_issuing_iso", ""))
    home_isos = {code for code in {passport_iso, licence_iso} if code}

    score = 0.0
    if collection == COLLECTION_INTL_TREATIES:
        if any(term in text for term in ["consular", "consular relations", "consular notification", "consular access"]):
            score += 5.5
        if any(term in text for term in ["road traffic", "driving permit", "driving licence", "driving license", "foreign driving"]):
            score += 5.5

    if collection == COLLECTION_CASE_LAW_GLOBAL and any(
        term in text for term in ["consular", "lagrand", "avena", "tehran", "foreign national"]
    ):
        score += 3.5

    if location_iso and jurisdiction == location_iso:
        score += 3.0
        if any(term in text for term in ["administrative", "traffic", "road traffic", "driving", "police", "detention", "criminal procedure", "interpreter", "counsel"]):
            score += 3.0

    if home_isos and jurisdiction in home_isos:
        score += 1.5
        if any(term in text for term in ["driving", "licence", "license", "permit", "passport", "motor vehicles"]):
            score += 2.0

    if "traffic_offences" in issue_labels and any(term in text for term in ["driving", "licence", "license", "traffic", "road"]):
        score += 1.5
    if "criminal_procedure" in issue_labels and any(term in text for term in ["detention", "arrest", "police", "interpreter", "counsel", "procedure"]):
        score += 1.5

    if (
        "passport" in text
        and not any(term in text for term in ["driving", "licence", "license", "traffic", "consular", "detention", "police", "administrative"])
    ):
        score -= 5.0
    if "landmark cases" in text and "passport" in text and "driving" not in text:
        score -= 4.0

    return score


def _apply_scenario_relevance(
    hits: list[dict[str, Any]],
    *,
    intent_primary: list[str],
    issue_labels: list[str],
    scenario_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for hit in hits:
        scenario_bonus = _scenario_relevance_score(
            hit,
            intent_primary=intent_primary,
            issue_labels=issue_labels,
            scenario_context=scenario_context,
        )
        enriched = dict(hit)
        enriched["scenario_bonus"] = scenario_bonus
        enriched["score"] = float(enriched.get("score", 0.0) or 0.0) + scenario_bonus
        adjusted.append(enriched)
    return adjusted


def _filter_non_merits_hits(hits: list[dict], query: str) -> list[dict]:
    if _source_discovery_query(query):
        return hits
    filtered: list[dict] = []
    for hit in hits:
        if str(hit.get("text", "")).lstrip().lower().startswith("source catalog entry:"):
            continue
        tier = infer_authority_tier(hit.get("metadata") or {})
        if tier == "project_reference":
            continue
        if tier == "official_source_catalog":
            continue
        filtered.append(hit)
    return filtered


def _limit_reference_dataset_hits(hits: list[dict], *, max_reference_hits: int = 2) -> list[dict]:
    if not hits:
        return hits
    annotated = _annotate_retrieved_hits(hits)
    has_high_authority = any(
        infer_authority_tier(item.get("metadata") or {}) in {"primary_authority", "case_law"}
        for item in annotated
    )
    if not has_high_authority:
        return annotated

    kept: list[dict] = []
    reference_hits = 0
    for item in sorted(
        annotated,
        key=lambda candidate: (
            authority_rank(candidate.get("authority_tier") or ""),
            float(candidate.get("score", 0.0)),
        ),
        reverse=True,
    ):
        tier = item.get("authority_tier") or infer_authority_tier(item.get("metadata") or {})
        if tier == "reference_dataset":
            if reference_hits >= max_reference_hits:
                continue
            reference_hits += 1
        kept.append(item)
    return kept


# ── FIX 4: Source diversity enforcement ───────────────────────────────────

def _enforce_source_diversity(
    retrieved: list[dict],
    intent_primary: list[str] | None = None,
    iso_codes: list[str] | None = None,
) -> list[dict]:
    """Prevent the final result set from being dominated by one collection."""
    intent_primary = intent_primary or []
    iso_codes = iso_codes or []
    commentary: list[dict] = []
    case_law: list[dict] = []
    treaties: list[dict] = []
    national: list[dict] = []
    other: list[dict] = []

    for p in retrieved:
        meta = p.get("metadata", {}) or {}
        doc_type = str(meta.get("doc_type", "")).lower()
        collection = str(meta.get("collection", "")).upper()

        if doc_type in {"commentary", "textbook"} or collection in {"SHAW_PRIVATE", "COMMENTARY", "COMMENTARY_GLOBAL"}:
            commentary.append(p)
        elif doc_type == "case_law" or collection == "CASE_LAW" or collection in CASE_LAW_COLLECTIONS:
            case_law.append(p)
        elif collection == "INTL_TREATIES":
            treaties.append(p)
        elif "NATIONAL" in collection:
            national.append(p)
        else:
            other.append(p)

    for bucket in (commentary, case_law, treaties, national, other):
        bucket.sort(key=lambda p: p.get("score", 0.0), reverse=True)

    if "jurisdiction_comparison" in intent_primary or iso_codes:
        bucket_order = [national, treaties, commentary, case_law, other]
    elif "conceptual" in intent_primary:
        bucket_order = [treaties, commentary, national, case_law, other]
    else:
        bucket_order = [case_law, treaties, commentary, national, other]

    diverse: list[dict] = []
    seen: set[str] = set()
    per_collection: dict[str, int] = {}

    # First pass: at most one from each source type, in intent-aware order.
    for bucket in bucket_order:
        if bucket and bucket[0]["text"][:80] not in seen:
            item = bucket[0]
            collection = str((item.get("metadata") or {}).get("collection", "")).upper()
            diverse.append(item)
            seen.add(item["text"][:80])
            per_collection[collection] = per_collection.get(collection, 0) + 1

    # Fill remaining slots with a soft cap of two per collection while possible.
    all_remaining = sorted(
        [p for p in retrieved if p["text"][:80] not in seen],
        key=lambda p: p.get("score", 0.0),
        reverse=True,
    )
    for p in all_remaining:
        if len(diverse) >= len(retrieved):
            break
        collection = str((p.get("metadata") or {}).get("collection", "")).upper()
        if per_collection.get(collection, 0) >= 2:
            continue
        diverse.append(p)
        seen.add(p["text"][:80])
        per_collection[collection] = per_collection.get(collection, 0) + 1

    if len(diverse) < len(retrieved):
        for p in all_remaining:
            if len(diverse) >= len(retrieved):
                break
            if p["text"][:80] not in seen:
                diverse.append(p)
                seen.add(p["text"][:80])

    return diverse


def _enforce_cross_border_coverage(
    retrieved: list[dict[str, Any]],
    *,
    scenario_context: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not retrieved:
        return retrieved

    location_iso = _normalize_jurisdiction((scenario_context or {}).get("location_iso", ""))
    passport_iso = _normalize_jurisdiction((scenario_context or {}).get("passport_iso", ""))
    licence_iso = _normalize_jurisdiction((scenario_context or {}).get("licence_issuing_iso", ""))
    home_isos = {code for code in {passport_iso, licence_iso} if code}

    def bucket(hit: dict[str, Any]) -> str:
        meta = hit.get("metadata", {}) or {}
        collection = str(meta.get("collection") or "").upper()
        jurisdiction = _normalize_jurisdiction(meta.get("jurisdiction", ""))
        text = " ".join(
            str(part or "")
            for part in [meta.get("source_name"), meta.get("citation"), hit.get("text")]
        ).lower()
        if collection == COLLECTION_INTL_TREATIES and any(
            term in text for term in ["consular", "road traffic", "driving permit", "foreign driving"]
        ):
            return "treaty_overlay"
        if location_iso and jurisdiction == location_iso:
            return "location_domestic"
        if home_isos and jurisdiction in home_isos:
            return "home_document_domestic"
        if collection == COLLECTION_CASE_LAW_GLOBAL:
            return "international_case_law"
        return "other"

    buckets: dict[str, list[dict[str, Any]]] = {
        "location_domestic": [],
        "treaty_overlay": [],
        "home_document_domestic": [],
        "international_case_law": [],
        "other": [],
    }
    for passage in sorted(retrieved, key=lambda item: item.get("score", 0.0), reverse=True):
        buckets[bucket(passage)].append(passage)

    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bucket_name in ["location_domestic", "treaty_overlay", "home_document_domestic", "international_case_law"]:
        for passage in buckets[bucket_name][:1]:
            key = passage.get("text", "")[:120]
            if key in seen:
                continue
            ordered.append(passage)
            seen.add(key)

    for passage in sorted(retrieved, key=lambda item: item.get("score", 0.0), reverse=True):
        key = passage.get("text", "")[:120]
        if key in seen:
            continue
        ordered.append(passage)
        seen.add(key)

    return ordered


# ── FIX 6: Retrieval confidence scoring ───────────────────────────────────

def _compute_retrieval_confidence(
    retrieved: list[dict],
    key_terms: set[str],
) -> dict[str, Any]:
    """Compute a retrieval confidence score for downstream use.

    Returns:
        {
            "level": "high" | "medium" | "low",
            "score": float (0.0 - 1.0),
            "reason": str,
            "avg_term_overlap": float,
            "avg_score": float,
            "passage_count": int,
        }
    """
    if not retrieved:
        return {
            "level": "low",
            "score": 0.0,
            "reason": "no passages retrieved",
            "avg_term_overlap": 0.0,
            "avg_score": 0.0,
            "passage_count": 0,
        }

    overlaps = [p.get("term_overlap", 0) for p in retrieved]
    scores = [p.get("score", 0.0) for p in retrieved]
    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
    avg_score = sum(scores) / len(scores) if scores else 0.0
    n_terms = len(key_terms) if key_terms else 1

    # Normalized overlap ratio (how many key terms are covered on average)
    overlap_ratio = avg_overlap / n_terms

    # Weighted confidence: 50% term coverage, 30% avg score, 20% passage count
    passage_factor = min(len(retrieved) / 5.0, 1.0)
    confidence_score = (
        0.50 * min(overlap_ratio, 1.0)
        + 0.30 * min(avg_score, 1.0)
        + 0.20 * passage_factor
    )

    if confidence_score >= 0.6:
        level = "high"
        reason = f"strong term coverage ({avg_overlap:.1f}/{n_terms} terms), {len(retrieved)} passages"
    elif confidence_score >= 0.3:
        level = "medium"
        reason = f"moderate coverage ({avg_overlap:.1f}/{n_terms} terms), some passages may be tangential"
    else:
        level = "low"
        reason = f"weak coverage ({avg_overlap:.1f}/{n_terms} terms), results may not fully address the query"

    return {
        "level": level,
        "score": round(confidence_score, 3),
        "reason": reason,
        "avg_term_overlap": round(avg_overlap, 2),
        "avg_score": round(avg_score, 4),
        "passage_count": len(retrieved),
    }


from typing import Any
# MAIN RETRIEVAL ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

def retrieve(state: PipelineStateDict) -> PipelineStateDict:
    import time as _time
    from src.config import OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS
    _retrieval_start = _time.monotonic()
    _deadline = _retrieval_start + OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS

    from src.rag.retriever import (
        expand_linked_passages,
        hybrid_search,
        rerank,
        _rrf_merge,
    )

    query = state["raw_input"]
    query_intent = state.get("query_intent") or {}
    issue_profile = state.get("issue_profile", {}) or {}
    iso_codes = _extract_iso_codes(query, issue_profile)
    has_case = _has_case_entity(state)
    intent_primary = _infer_intent_primary(
        query,
        list(query_intent.get("primary", []) or []),
        iso_codes,
        has_case,
    )
    case_names = _named_case_entities(state)
    query_requests_cases = _query_requests_case_law(query)
    issue_labels = list(state.get("issue_labels", []) or [])
    scenario_context = ((state.get("entities") or {}).get("scenario_context") or {})

    # ── FIX 1: Hard filter collections ────────────────────────────────
    logical_collections = _hard_filter_collections(intent_primary, iso_codes, has_case, query_requests_cases)
    collections = _expand_collection_aliases(logical_collections)

    # ── FIX 6: Pre-retrieval guard ────────────────────────────────────
    if not collections:
        return {
            **state,
            "retrieved": [],
            "queries": {},
            "retrieval_note": "No relevant collections identified for this query. "
                              "Please rephrase with specific legal terms, jurisdictions, or case names.",
        }

    # ── FIX 5: Get multiplicative weights ─────────────────────────────
    collection_weights = _get_collection_weights(collections, intent_primary, iso_codes, has_case)

    # Store routing decision for downstream visibility
    if "query_intent" not in state or state["query_intent"] is None:
        state["query_intent"] = {}
    state["query_intent"]["primary"] = intent_primary
    state["query_intent"]["iso_codes"] = iso_codes
    state["query_intent"]["priority_collections"] = collection_weights
    state["query_intent"]["hard_filtered_collections"] = collections
    state["query_intent"]["logical_collections"] = logical_collections
    if scenario_context:
        state["query_intent"]["scenario_context"] = scenario_context

    local_model_hints: list[str] = []
    if (
        "cross_border_scenario" in intent_primary
        or {"criminal_procedure", "traffic_offences", "immigration_and_mobility", "consular_assistance"} & set(issue_labels)
    ):
        try:
            from src.services.legal_gpt2 import generate_legal_gpt2_query_hints

            local_model_hints = generate_legal_gpt2_query_hints(
                query,
                iso_codes=iso_codes,
                issue_labels=issue_labels,
            )
        except Exception as exc:
            print(f"Warning: Legal GPT-2 query assist failed: {type(exc).__name__}: {exc}")
    state["query_intent"]["legal_gpt2_hints"] = local_model_hints

    # ── FIX 2: Build safe query variants (jurisdiction-aware) ──────────
    query_variants = _build_query_variants(
        query,
        intent_primary,
        iso_codes,
        case_names,
        issue_labels=issue_labels,
        local_model_hints=local_model_hints,
    )

    # ── Key terms + phrases for anchor filtering ──────────────────────
    key_terms = _extract_key_terms(query, iso_codes)
    if case_names:
        key_terms |= _extract_key_terms(" ".join(case_names), iso_codes)
    scenario_terms, scenario_phrases = _scenario_anchor_terms(
        intent_primary=intent_primary,
        issue_labels=issue_labels,
        scenario_context=scenario_context,
    )
    key_terms |= scenario_terms
    query_phrases = _extract_query_phrases(query)
    for phrase in scenario_phrases:
        if phrase not in query_phrases:
            query_phrases.append(phrase)

    results_per_col: dict[str, list] = {}
    queries_used: dict[str, str] = {}

    for col in collections:
        col_hits: list[dict] = []
        weight = collection_weights.get(col, 1.0)

        # Search with each query variant, deduplicate
        for variant in query_variants:
            try:
                hits = hybrid_search(variant, col, k=max(_TOP_K_PER_COLLECTION * 4, 12))
                if hits:
                    existing_prefixes = {h["text"][:80] for h in col_hits}
                    for h in hits:
                        if h["text"][:80] not in existing_prefixes:
                            metadata = h.setdefault("metadata", {})
                            if isinstance(metadata, dict):
                                metadata.setdefault("collection", col)
                            col_hits.append(h)
                            existing_prefixes.add(h["text"][:80])
            except Exception as exc:
                print(f"Warning: retrieval failed for {col} with variant: {exc}")

        if not col_hits:
            continue

        col_hits = _annotate_retrieved_hits(col_hits)
        queries_used[col] = " | ".join(query_variants[:3])

        # ── FIX 4: Hard jurisdiction discard ──────────────────────────
        col_hits = _jurisdiction_discard(col_hits, iso_codes, intent_primary, query=query)

        # ── Hard noise discard ────────────────────────────────────────
        col_hits = _discard_noise(col_hits, query)
        col_hits = _filter_non_merits_hits(col_hits, query)

        col_hits = _case_anchor_filter(col_hits, case_names)

        # ── Keyword anchor + phrase boost + negative filter ────────────
        col_hits = _keyword_anchor_filter(col_hits, key_terms, query_phrases, query)
        col_hits = _apply_scenario_relevance(
            col_hits,
            intent_primary=intent_primary,
            issue_labels=issue_labels,
            scenario_context=scenario_context,
        )

        # ── Strict top-k per collection ───────────────────────────────
        # Sort by: phrase_bonus > term_overlap > score, minus neg_penalty
        col_hits = sorted(
            col_hits,
            key=lambda h: (
                h.get("phrase_bonus", 0.0),
                h.get("term_overlap", 0),
                h.get("scenario_bonus", 0.0),
                h.get("score", 0.0) + h.get("neg_penalty", 0.0),
            ),
            reverse=True,
        )
        col_hits = col_hits[:_TOP_K_PER_COLLECTION]

        # ── FIX 5: Multiplicative weight ──────────────────────────────
        col_hits = _apply_collection_weight(col_hits, weight)

        if col_hits:
            results_per_col[col] = col_hits

    # Second-pass case retrieval for named cases
    if case_names:
        results_per_col = _second_pass_case_retrieval(
            case_names,
            results_per_col,
            iso_codes=iso_codes,
            intent_primary=intent_primary,
            collection_weights=collection_weights,
            query=query,
        )

    merged = _rrf_merge(results_per_col) if results_per_col else []
    top_passages = expand_linked_passages(
        rerank(
            query,
            merged,
            top_n=RERANK_TOP_N,
        ),
        max_results=RERANK_TOP_N,
    )

    # ── Post-rerank enforcement: re-apply ALL filters after rerank ────────
    # The reranker can re-surface passages that were already filtered if they
    # appear in expanded linked passages. Kill them again.
    top_passages = _jurisdiction_discard(top_passages, iso_codes, intent_primary, query=query)
    top_passages = _discard_noise(top_passages, query)
    top_passages = _filter_non_merits_hits(top_passages, query)
    top_passages = _case_anchor_filter(top_passages, case_names)
    top_passages = _keyword_anchor_filter(top_passages, key_terms, query_phrases, query)
    top_passages = _apply_scenario_relevance(
        top_passages,
        intent_primary=intent_primary,
        issue_labels=issue_labels,
        scenario_context=scenario_context,
    )
    top_passages = _limit_reference_dataset_hits(top_passages)
    top_passages = _annotate_retrieved_hits(top_passages)
    top_passages = sorted(
        top_passages,
        key=lambda h: (
            authority_rank(h.get("authority_tier") or infer_authority_tier(h.get("metadata") or {})),
            h.get("scenario_bonus", 0.0),
            h.get("phrase_bonus", 0.0),
            h.get("term_overlap", 0),
            h.get("score", 0.0),
        ),
        reverse=True,
    )
    top_passages = [
        passage
        for passage in top_passages
        if not str(passage.get("text", "")).lstrip().lower().startswith("source catalog entry:")
    ]

    retrieved = [
        {
            "text": p["text"],
            "score": p.get("rerank_score", p.get("score", 0.0)),
            "metadata": p.get("metadata", {}),
            "term_overlap": p.get("term_overlap", 0),
            "phrase_matches": p.get("phrase_matches", []),
            "selection_reason": p.get("selection_reason", ""),  # FIX 7: explainability
            "authority_tier": p.get("authority_tier") or infer_authority_tier(p.get("metadata", {})),
        }
        for p in top_passages
    ]

    # Seed fallback for named cases ONLY — NEVER for conceptual queries.
    # This was leaking CASE_LAW results back into conceptual queries.
    if case_names and "named_case" in intent_primary:
        from src.rag.retriever import seed_case_search
        case_law_count = sum(
            1 for p in retrieved
            if p.get("metadata", {}).get("doc_type") == "case_law"
        )
        if case_law_count < 3:
            for case_name in case_names[:3]:
                seed_hits = seed_case_search(case_name, top_k=4)
                # Apply same anchor filter to seed hits
                seed_hits = _annotate_retrieved_hits(seed_hits)
                seed_hits = _filter_non_merits_hits(seed_hits, query)
                seed_hits = _keyword_anchor_filter(seed_hits, key_terms, query_phrases, query)
                existing_texts = {p["text"][:80] for p in retrieved}
                for hit in seed_hits:
                    if hit["text"][:80] not in existing_texts:
                        retrieved.append(hit)
                        existing_texts.add(hit["text"][:80])

    # ── FIX 4: Diversity enforcement for conceptual queries ───────────
    if (
        ("conceptual" in intent_primary or "jurisdiction_comparison" in intent_primary or iso_codes)
        and "named_case" not in intent_primary
        and len(retrieved) >= 3
    ):
        retrieved = _enforce_source_diversity(retrieved, intent_primary, iso_codes)
    if "cross_border_scenario" in intent_primary:
        retrieved = _enforce_cross_border_coverage(retrieved, scenario_context=scenario_context)
    retrieved = [
        passage
        for passage in retrieved
        if not str(passage.get("text", "")).lstrip().lower().startswith("source catalog entry:")
    ]
    retrieved = _limit_reference_dataset_hits(retrieved)
    retrieved = _annotate_retrieved_hits(retrieved)

    # ── FIX 6: Confidence scoring ─────────────────────────────────────
    confidence = _compute_retrieval_confidence(retrieved, key_terms)
    state["query_intent"]["retrieval_confidence"] = confidence

    _elapsed_ms = int((_time.monotonic() - _retrieval_start) * 1000)
    _partial = _time.monotonic() > _deadline

    authority_gaps = list(state.get("authority_gaps", []) or [])
    if _partial:
        authority_gaps.append("Retrieval deadline reached; returning partial authority coverage.")

    return {
        **state,
        "retrieved": retrieved,
        "queries": queries_used,
        "retrieval_partial": _partial,
        "retrieval_time_ms": _elapsed_ms,
        "authority_gaps": authority_gaps,
    }
