"""
Step 2 — Entity and issue extraction.
Three parallel passes: spaCy NER + GLiNER zero-shot + DeBERTa issue classifier.
"""
from __future__ import annotations

import difflib
import re
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    OMNILEGAL_DIR,
    OMNILEGAL_ENABLE_HEAVY_MODELS,
    OMNILEGAL_ENABLE_GLINER,
    OMNILEGAL_ENABLE_LEGAL_NER,
    OMNILEGAL_ENABLE_ZERO_SHOT,
)
from src.pipeline.state import PipelineStateDict
from src.models.heavy_nlp import get_spacy_model, get_gliner_model, get_zero_shot_classifier

# Alias → canonical name map loaded from landmark_registry.yaml.
# Allows "Great Britain v Costa Rica" or "Tinoco case" to resolve to
# "Tinoco Arbitration" so downstream retrieval uses the correct canonical form.
def _load_alias_map() -> dict[str, str]:
    path = OMNILEGAL_DIR / "configs" / "landmark_registry.yaml"
    alias_map: dict[str, str] = {}
    if not path.exists():
        return alias_map
    try:
        current_canonical: str = ""
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            # Match both "canonical_name: ..." and "- canonical_name: ..."
            # (YAML list items strip the leading "- " after line.strip())
            bare = stripped.lstrip("- ").strip()
            if bare.startswith("canonical_name:"):
                current_canonical = bare.split(":", 1)[1].strip().strip('"\'')
                alias_map[current_canonical.lower()] = current_canonical
            elif bare.startswith("aliases:") and current_canonical:
                # Inline list: aliases: ["a", "b"]
                raw = bare.split(":", 1)[1].strip()
                for alias in re.findall(r'"([^"]+)"|\'([^\']+)\'', raw):
                    name = alias[0] or alias[1]
                    alias_map[name.lower()] = current_canonical
    except Exception:
        pass
    return alias_map

_ALIAS_MAP: dict[str, str] = _load_alias_map()

# Legal suffixes that signal a case reference when paired with a short name.
_CASE_SUFFIXES = (
    "case", "decision", "judgment", "judgement", "award", "ruling",
    "arbitration", "holding", "doctrine", "opinion", "affair",
)

# Compiled patterns: "tinoco decision", "chorzow ruling", etc.
# Built from the first significant word of every canonical name in the alias map.
def _build_short_name_patterns() -> dict[re.Pattern[str], str]:
    stop = {"the", "a", "an", "of", "in", "on", "for", "and", "or", "vs", "v"}
    patterns: dict[re.Pattern[str], str] = {}
    seen_words: set[str] = set()
    for alias, canonical in _ALIAS_MAP.items():
        words = [w for w in alias.split() if w.isalpha() and w not in stop]
        if not words:
            continue
        first = words[0]
        # Only build a pattern for words that uniquely identify a single
        # canonical case (skip generic words like "lotus" that appear in many).
        if first in seen_words:
            continue
        seen_words.add(first)
        suffix_group = "|".join(re.escape(s) for s in _CASE_SUFFIXES)
        pat = re.compile(
            rf"\b{re.escape(first)}\s+(?:{suffix_group})\b",
            re.IGNORECASE,
        )
        patterns[pat] = canonical
    return patterns

_SHORT_NAME_PATTERNS: dict[re.Pattern[str], str] = _build_short_name_patterns()

# International issue labels — used to upgrade "unknown" jurisdiction.
_INTL_ISSUE_LABELS = {
    "use_of_force_jus_ad_bellum", "ihl_jus_in_bello",
    "law_of_the_sea", "treaty_interpretation", "state_responsibility",
    "statehood_and_recognition", "jurisdiction_and_immunity",
    "international_criminal_law", "diplomatic_relations",
    "international_environmental_law", "general_international_law",
    "consular_assistance",
}

# Comparison query patterns: "compare X and Y", "difference between X and Y", "X vs Y".
_COMPARISON_RE = re.compile(
    r"\bcompare\b|\bdifference between\b|\bcontrast\b|\bversus\b|\bvs\.?\b",
    re.IGNORECASE,
)
_CROSS_BORDER_SCENARIO_RE = re.compile(
    r"\b(passport|visa|driving licen[cs]e|driver'?s licen[cs]e|international driving permit|foreign licen[cs]e|arrest|detention|custody|consular|embassy|border|immigration|deport)\b",
    re.IGNORECASE,
)

_spacy_nlp = None
_gliner_model = None
_issue_clf = None

_COUNTRY_TEXT_TO_ISO = {
    "india": "IN",
    "indian": "IN",
    "united states": "US",
    "us": "US",
    "usa": "US",
    "american": "US",
    "united kingdom": "GB",
    "uk": "GB",
    "british": "GB",
    "great britain": "GB",
    "eu": "EU",
    "european union": "EU",
    "european": "EU",
    "russia": "RU",
    "russian federation": "RU",
    "russian": "RU",
    "israel": "IL",
    "israeli": "IL",
    "china": "CN",
    "chinese": "CN",
    "france": "FR",
    "french": "FR",
    "germany": "DE",
    "german": "DE",
    "japan": "JP",
    "japanese": "JP",
    "pakistan": "PK",
    "pakistani": "PK",
    "iran": "IR",
    "iranian": "IR",
    "south africa": "ZA",
    "south african": "ZA",
    "brazil": "BR",
    "brazilian": "BR",
    "canada": "CA",
    "canadian": "CA",
    "australia": "AU",
    "australian": "AU",
    "netherlands": "NL",
    "dutch": "NL",
    "mexico": "MX",
    "mexican": "MX",
    "turkey": "TR",
    "turkish": "TR",
    "egypt": "EG",
    "egyptian": "EG",
    "nigeria": "NG",
    "nigerian": "NG",
}
_COUNTRY_TEXT_PATTERN = "|".join(sorted((re.escape(key) for key in _COUNTRY_TEXT_TO_ISO), key=len, reverse=True))
_SCENARIO_LOCATION_RE = re.compile(
    rf"\b(?:arrest(?:ed)?|detain(?:ed|ment)?|charge[sd]?|stopped?|driving|offen[cs]e|offense|traffic|custody)\b"
    rf"[^.?!]{{0,80}}?\b(?:in|within|inside|under)\s+(?P<country>{_COUNTRY_TEXT_PATTERN})\b",
    re.IGNORECASE,
)
_GENERIC_LOCATION_RE = re.compile(
    rf"\b(?:in|within|inside|under)\s+(?P<country>{_COUNTRY_TEXT_PATTERN})\b",
    re.IGNORECASE,
)
_PASSPORT_COUNTRY_RE = re.compile(
    rf"\b(?P<country>{_COUNTRY_TEXT_PATTERN})\s+passport\b",
    re.IGNORECASE,
)
_LICENCE_COUNTRY_RE = re.compile(
    rf"\b(?P<country>{_COUNTRY_TEXT_PATTERN})\s+"
    rf"(?:(?:driving|driver'?s)\s+licen[cs]e|foreign\s+licen[cs]e|international\s+driving\s+permit)\b",
    re.IGNORECASE,
)
_CONSULAR_RIGHTS_RE = re.compile(r"\b(arrest(?:ed)?|detention|detain(?:ed|ment)?|custody|charged)\b", re.IGNORECASE)

_GLINER_LABELS = [
    "country", "treaty", "UN body", "ICJ case", "treaty article",
    "international organization", "court", "statute",
    "legal case", "arbitration case", "international arbitration",
    "passport", "driving license", "visa", "detention", "arrest",
]

_ISSUE_LABELS = [
    "use_of_force_jus_ad_bellum",
    "ihl_jus_in_bello",
    "human_rights",
    "criminal_procedure",
    "traffic_offences",
    "immigration_and_mobility",
    "consular_assistance",
    "law_of_the_sea",
    "treaty_interpretation",
    "state_responsibility",
    "statehood_and_recognition",
    "jurisdiction_and_immunity",
    "international_criminal_law",
    "diplomatic_relations",
    "international_environmental_law",
    "trade_and_wto",
    "refugee_and_asylum",
    "arms_control_and_disarmament",
    "cyber_and_digital_law",
    "general_international_law",
    "erga_omnes_jus_cogens",
    "territorial_sovereignty",
]


# Removed local _get_spacy, _get_gliner, _get_issue_clf


def _spacy_entities(text: str) -> list[dict[str, Any]]:
    if not OMNILEGAL_ENABLE_HEAVY_MODELS or not OMNILEGAL_ENABLE_LEGAL_NER:
        return []
    try:
        nlp = get_spacy_model()
        if nlp is None:
            return []
        doc = nlp(text[:1024])
        return [
            {"text": ent.text, "label": ent.label_, "start": ent.start_char, "end": ent.end_char, "source": "spacy"}
            for ent in doc.ents
        ]
    except Exception as exc:
        print(f"Warning: spaCy NER failed: {exc}")
        return []


def _gliner_entities(text: str) -> list[dict[str, Any]]:
    if not OMNILEGAL_ENABLE_HEAVY_MODELS or not OMNILEGAL_ENABLE_GLINER:
        return []
    try:
        model = get_gliner_model()
        if model is None:
            raise ValueError("GLiNER model loaded as None")
        entities = model.predict_entities(text[:1024], _GLINER_LABELS, threshold=0.5)
        return [
            {"text": e["text"], "label": e["label"], "start": e.get("start", 0), "end": e.get("end", 0), "source": "gliner"}
            for e in entities
        ]
    except Exception as exc:
        print(f"Warning: main-env GLiNER NER failed: {exc}; trying isolated adapter")
        try:
            from src.pipeline.gliner_adapter import predict_entities_isolated

            entities = predict_entities_isolated(text[:1024], _GLINER_LABELS, threshold=0.5)
            return [
                {
                    "text": e["text"],
                    "label": e["label"],
                    "start": e.get("start", 0),
                    "end": e.get("end", 0),
                    "source": "gliner_isolated",
                }
                for e in entities
            ]
        except Exception as adapter_exc:
            print(f"Warning: isolated GLiNER NER failed: {adapter_exc}")
            return []


def _classify_issues(text: str) -> list[str]:
    heuristic = _heuristic_issues(text)
    if heuristic and (not OMNILEGAL_ENABLE_HEAVY_MODELS or not OMNILEGAL_ENABLE_ZERO_SHOT):
        return heuristic
    try:
        clf = get_zero_shot_classifier(multi_label=True)
        if clf is None:
            return heuristic or ["general_international_law"]
        result = clf(text[:512], candidate_labels=_ISSUE_LABELS, multi_label=True)
        labels = [
            label for label, score in zip(result["labels"], result["scores"])
            if score >= 0.4
        ]
        return labels or heuristic or ["general_international_law"]
    except Exception as exc:
        print(f"Warning: issue classification failed: {exc}")
        return heuristic or ["general_international_law"]


_PATTERN_ENTITIES = {
    "treaty": [
        r"\bUN Charter\b",
        r"\bICCPR\b",
        r"\bICESCR\b",
        r"\bVCLT\b",
        r"\bVienna Convention\b",
        r"\bRome Statute\b",
        r"\bUNCLOS\b",
    ],
    "treaty article": [r"\bArticle\s+\d+[A-Za-z0-9()\-./]*"],
    "ICJ case": [
        r"\bCorfu Channel\b",
        r"\bNicaragua\s+v\.?\s+(?:United States|US|USA)\b",
        r"\bOil Platforms\b",
        r"\bDRC\s+v\.?\s+Uganda\b",
        r"\bCaroline\b",
        r"\bLotus\b",
        r"\bBarcelona Traction\b",
        r"\bNottebohm\b",
        r"\bChorzow Factory\b",
        r"\bReparations\s+(?:for\s+Injuries|Advisory\s+Opinion)\b",
        r"\bNamibia\s+Advisory\s+Opinion\b",
        r"\bNuclear\s+Tests\b",
    ],
    # Named arbitrations and cases not before the ICJ.
    # Specific names only — broad catch-alls are handled by _alias_scan_entities
    # which searches the alias map directly and avoids IGNORECASE false positives.
    "legal_case": [
        r"\bAlabama\s+Claims\b",
        r"\bClipperton\s+Island\b",
        r"\bTrail\s+Smelter\b",
        r"\bICSID\s+Case\b",
        r"\bRainbow\s+Warrior\b",
    ],
    "country": [
        r"\bIndia\b", r"\bUnited States\b", r"\bUS\b", r"\bUSA\b", r"\bAmerican\b",
        r"\bUnited Kingdom\b", r"\bUK\b", r"\bBritish\b", r"\bEU\b", r"\bEuropean Union\b", r"\bEuropean\b",
        r"\bRussia\b", r"\bRussian Federation\b", r"\bRussian\b", r"\bIsrael\b", r"\bIsraeli\b",
        r"\bCosta Rica\b", r"\bGreat Britain\b", r"\bChina\b", r"\bChinese\b", r"\bFrance\b", r"\bFrench\b",
        r"\bGermany\b", r"\bGerman\b", r"\bJapan\b", r"\bJapanese\b", r"\bPakistan\b", r"\bPakistani\b",
        r"\bIran\b", r"\bIranian\b", r"\bSouth Africa\b", r"\bSouth African\b", r"\bBrazil\b", r"\bBrazilian\b",
        r"\bCanada\b", r"\bCanadian\b", r"\bAustralia\b", r"\bAustralian\b", r"\bNetherlands\b", r"\bDutch\b",
        r"\bMexico\b", r"\bMexican\b", r"\bTurkey\b", r"\bTurkish\b", r"\bEgypt\b", r"\bEgyptian\b",
        r"\bNigeria\b", r"\bNigerian\b",
    ],
    "court": [r"\bICJ\b", r"\bInternational Court of Justice\b", r"\bSupreme Court of India\b", r"\bPCIJ\b", r"\bPermanent Court of International Justice\b", r"\bPCA\b"],
    "passport": [r"\bpassport\b"],
    "driving_license": [r"\bdriving licen[cs]e\b", r"\bdriver'?s licen[cs]e\b", r"\binternational driving permit\b"],
    "visa": [r"\bvisa\b", r"\bresidence permit\b"],
    "detention": [r"\barrest(?:ed)?\b", r"\bdetain(?:ed|ment)?\b", r"\bcustody\b", r"\bcharged\b"],
}


def _pattern_entities(text: str) -> list[dict[str, Any]]:
    entities: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for label, patterns in _PATTERN_ENTITIES.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                key = (match.start(), match.end(), label)
                if key in seen:
                    continue
                seen.add(key)
                entities.append({
                    "text": text[match.start():match.end()],
                    "label": label,
                    "start": match.start(),
                    "end": match.end(),
                    "source": "pattern",
                })
    return sorted(entities, key=lambda item: (item["start"], item["end"]))


def _alias_scan_entities(text: str) -> list[dict[str, Any]]:
    """Scan text for every key in _ALIAS_MAP and emit a legal_case entity
    mapped to the canonical case name.  Catches bare mentions like 'tinoco',
    'wall opinion', or 'Great Britain v Costa Rica' that regex patterns miss.
    Sorted longest-key-first so 'tinoco arbitration' wins over 'tinoco'.
    """
    lowered = text.lower()
    entities: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()
    # Sort by key length descending so longer aliases shadow their substrings.
    for alias in sorted(_ALIAS_MAP, key=len, reverse=True):
        pos = lowered.find(alias)
        if pos == -1:
            continue
        end = pos + len(alias)
        # Word-boundary check: don't match mid-word substrings.
        before_ok = pos == 0 or not lowered[pos - 1].isalnum()
        after_ok = end == len(lowered) or not lowered[end].isalnum()
        if not (before_ok and after_ok):
            continue
        # Suppress if this span is already covered by a longer match.
        if any(s <= pos and end <= e for s, e in seen_spans):
            continue
        seen_spans.add((pos, end))
        canonical = _ALIAS_MAP[alias]
        entities.append({
            "text": canonical,
            "label": "legal_case",
            "start": pos,
            "end": end,
            "source": "alias_scan",
        })
    return entities


def _short_name_entities(text: str) -> list[dict[str, Any]]:
    """Catch mentions like 'tinoco decision', 'chorzow ruling', 'lotus judgment'
    that the alias scan misses because the suffix isn't in the alias map.
    """
    entities: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for pat, canonical in _SHORT_NAME_PATTERNS.items():
        for m in pat.finditer(text):
            span = (m.start(), m.end())
            if span in seen:
                continue
            seen.add(span)
            entities.append({
                "text": canonical,
                "label": "legal_case",
                "start": m.start(),
                "end": m.end(),
                "source": "short_name",
            })
    return entities


def _fuzzy_scan_entities(text: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    words = lowered.split()
    entities: list[dict[str, Any]] = []
    seen_spans = set()
    
    # Generate 2-5 word n-grams
    ngrams = []
    for length in range(2, 6):
        for i in range(len(words) - length + 1):
            ngram_text = " ".join(words[i:i + length])
            if sum(1 for c in ngram_text if c.isalpha()) > 5:
                pos = lowered.find(ngram_text)
                ngrams.append((ngram_text, pos, pos + len(ngram_text)))
                
    for ngram, start_pos, end_pos in ngrams:
        best_match = None
        best_ratio = 0.82
        ngram_tokens = {token for token in re.findall(r"[a-z]+", ngram) if len(token) > 3}
        for alias in _ALIAS_MAP:
            alias_tokens = {token for token in re.findall(r"[a-z]+", alias) if len(token) > 3}
            ratio = difflib.SequenceMatcher(None, ngram, alias).ratio()
            if ratio < 0.92 and not (ngram_tokens & alias_tokens):
                continue
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = _ALIAS_MAP[alias]
        
        if best_match:
            if any(s <= start_pos and end_pos <= e for s, e in seen_spans):
                continue
            seen_spans.add((start_pos, end_pos))
            entities.append({
                "text": best_match,
                "label": "legal_case",
                "start": start_pos,
                "end": end_pos,
                "source": "fuzzy_scan"
            })
    return entities


# ── Concept-based case detection (paraphrase grounding) ───────────────────
# Maps keyword combinations to canonical case names. Catches references like
# "belgium shareholders spain" → Barcelona Traction, or "island sovereignty
# dispute" → Island of Palmas.

_CONCEPT_CASE_MAP: list[tuple[set[str], str]] = [
    # Barcelona Traction — "belgium", "shareholders", "spain" in any order
    ({"belgium", "shareholders"}, "Barcelona Traction"),
    ({"belgium", "spain", "share"}, "Barcelona Traction"),
    ({"shareholders", "spain"}, "Barcelona Traction"),
    ({"erga omnes", "barcelona"}, "Barcelona Traction"),
    # Island of Palmas — sovereignty, island, dispute
    ({"island", "palmas"}, "Island of Palmas"),
    ({"island", "sovereignty", "dispute"}, "Island of Palmas"),
    ({"island", "netherlands", "us"}, "Island of Palmas"),
    # Chorzow Factory — reparation, factory, germany, poland
    ({"chorzow"}, "Chorzow Factory"),
    ({"factory", "reparation"}, "Chorzow Factory"),
    ({"factory", "germany", "poland"}, "Chorzow Factory"),
    # Lotus — turkey, france, collision, ship
    ({"lotus"}, "Lotus Case"),
    ({"turkey", "france", "ship"}, "Lotus Case"),
    ({"turkey", "france", "collision"}, "Lotus Case"),
    # Nottebohm — nationality, liechtenstein, guatemala
    ({"nottebohm"}, "Nottebohm Case"),
    ({"nationality", "liechtenstein"}, "Nottebohm Case"),
    ({"genuine", "link", "nationality"}, "Nottebohm Case"),
    # Caroline — self-defense, anticipatory
    ({"caroline"}, "Caroline Case"),
    ({"anticipatory", "self-defense"}, "Caroline Case"),
    ({"anticipatory", "self-defence"}, "Caroline Case"),
    # Trail Smelter — transboundary, pollution, smelter
    ({"trail", "smelter"}, "Trail Smelter"),
    ({"transboundary", "pollution"}, "Trail Smelter"),
    # Rainbow Warrior — france, new zealand, agents
    ({"rainbow", "warrior"}, "Rainbow Warrior"),
    ({"france", "new zealand", "agents"}, "Rainbow Warrior"),
    # Tinoco — costa rica, government recognition
    ({"tinoco"}, "Tinoco Arbitration"),
    ({"costa rica", "government", "recognition"}, "Tinoco Arbitration"),
    # Nicaragua — mining, harbours, contra
    ({"nicaragua", "united states"}, "Nicaragua v. United States"),
    ({"nicaragua", "mining", "harbours"}, "Nicaragua v. United States"),
    # Oil Platforms — platforms, iran
    ({"oil", "platforms"}, "Oil Platforms"),
    ({"oil", "iran"}, "Oil Platforms"),
    # Corfu Channel — albania, mines, channel
    ({"corfu"}, "Corfu Channel"),
    ({"albania", "mines", "channel"}, "Corfu Channel"),
    # Reparations — injuries, UN agents
    ({"reparations", "injuries"}, "Reparations Advisory Opinion"),
    ({"un", "agents", "injuries"}, "Reparations Advisory Opinion"),
    # Nuclear Tests — france, nuclear, testing
    ({"nuclear", "tests"}, "Nuclear Tests"),
    ({"france", "nuclear", "testing"}, "Nuclear Tests"),
]


def _concept_case_entities(text: str) -> list[dict[str, Any]]:
    """Detect cases from conceptual descriptions / paraphrases.

    'belgium shareholders in spain' → Barcelona Traction
    'island sovereignty dispute' → Island of Palmas
    """
    lowered = text.lower()
    entities: list[dict[str, Any]] = []
    seen_cases: set[str] = set()

    for keywords, canonical in _CONCEPT_CASE_MAP:
        if all(kw in lowered for kw in keywords):
            if canonical not in seen_cases:
                seen_cases.add(canonical)
                entities.append({
                    "text": canonical,
                    "label": "legal_case",
                    "start": 0,
                    "end": len(text),
                    "source": "concept_match",
                })

    return entities


def _heuristic_issues(text: str) -> list[str]:
    lowered = text.lower()
    rules = [
        ("use_of_force_jus_ad_bellum", ["use of force", "article 51", "self-defense", "self defence", "armed attack", "anticipatory"]),
        ("ihl_jus_in_bello", ["ihl", "humanitarian", "geneva convention", "combatant", "civilian", "occupation"]),
        ("human_rights", ["human rights", "iccpr", "icescr", "echr", "freedom", "expression", "detention", "death penalty", "capital punishment", "free speech", "fair trial", "torture", "extradition", "right to life"]),
        ("criminal_procedure", ["arrest", "detention", "custody", "bail", "charged", "interrogation", "criminal procedure", "prosecution"]),
        ("traffic_offences", ["traffic", "driving", "driver", "driving licence", "driving license", "road offence", "motor vehicle"]),
        ("immigration_and_mobility", ["passport", "visa", "immigration", "deportation", "entry clearance", "foreign licence", "foreign license", "border control"]),
        ("consular_assistance", ["consular", "consulate", "embassy", "vienna convention on consular relations", "consular notification"]),
        ("law_of_the_sea", ["unclos", "sea", "maritime", "exclusive economic zone", "continental shelf"]),
        ("treaty_interpretation", ["vclt", "treaty interpretation", "article 31", "article 32", "pacta sunt"]),
        ("state_responsibility", ["state responsibility", "attribution", "reparation", "countermeasure", "internationally wrongful act", "ilc articles"]),
        ("statehood_and_recognition", ["statehood", "recognition", "montevideo", "self-determination", "tinoco", "de facto government", "de jure", "government succession", "state succession", "recognition of government"]),
        ("erga_omnes_jus_cogens", ["erga omnes", "jus cogens", "peremptory norm", "obligations owed to international community"]),
        ("territorial_sovereignty", ["territorial sovereignty", "terra nullius", "occupation", "cession", "discovery"]),
        ("jurisdiction_and_immunity", ["jurisdiction", "immunity", "sovereign immunity", "universal jurisdiction"]),
        ("international_criminal_law", ["rome statute", "icc", "war crime", "genocide", "crime against humanity"]),
        ("diplomatic_relations", ["diplomatic", "consular", "vienna convention on diplomatic"]),
        ("international_environmental_law", ["environment", "climate", "pollution", "transboundary harm"]),
        ("trade_and_wto", ["wto", "gatt", "trade", "tariff"]),
        ("refugee_and_asylum", ["refugee", "asylum", "non-refoulement"]),
        ("arms_control_and_disarmament", ["arms", "nuclear", "disarmament", "missile"]),
        ("cyber_and_digital_law", ["cyber", "digital", "data", "internet"]),
    ]
    matches = [label for label, needles in rules if any(needle in lowered for needle in needles)]
    return matches or ["general_international_law"]


def extract_entities(state: PipelineStateDict) -> PipelineStateDict:
    text = state["raw_input"]

    spacy_ents = _spacy_entities(text)
    pattern_ents = _pattern_entities(text)
    gliner_ents = _gliner_entities(text)
    alias_ents = _alias_scan_entities(text)
    short_ents = _short_name_entities(text)
    fuzzy_ents = _fuzzy_scan_entities(text)
    concept_ents = _concept_case_entities(text)  # FIX 5: paraphrase → case grounding

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for ent in pattern_ents + alias_ents + short_ents + concept_ents + fuzzy_ents + spacy_ents + gliner_ents:
        # Resolve aliases to canonical names (e.g. "Great Britain v Costa Rica"
        # → "Tinoco Arbitration") so retrieval uses the right form.
        canonical = _ALIAS_MAP.get(ent["text"].lower())
        if canonical:
            ent = {**ent, "text": canonical, "canonical": True}
        key = (ent["text"].lower(), ent["label"])
        if key not in seen:
            seen.add(key)
            merged.append(ent)

    issue_labels = _classify_issues(text)
    comparison_mode = bool(_COMPARISON_RE.search(text))

    iso_country_codes = _infer_iso_country_codes(merged)
    scenario_context = _infer_scenario_context(text, iso_country_codes, issue_labels)
    jurisdiction = _infer_jurisdiction(merged, issue_labels, iso_country_codes)
    query_intent = _classify_query_intent(text, merged, issue_labels, iso_country_codes)
    if scenario_context.get("cross_border"):
        for label in ["cross_border_scenario", "jurisdiction_comparison", "international_overlay", "country"]:
            if label not in query_intent["labels"]:
                query_intent["labels"].append(label)
        if "cross_border_scenario" not in query_intent["primary"]:
            query_intent["primary"].insert(0, "cross_border_scenario")
        if "jurisdiction_comparison" not in query_intent["primary"]:
            query_intent["primary"].append("jurisdiction_comparison")
        query_intent["primary"] = [item for item in query_intent["primary"] if item != "mixed"]
        query_intent["scenario_context"] = scenario_context

    entities_dict: dict[str, Any] = {
        "original_text": text,
        "entities": merged,
        "jurisdiction": jurisdiction,
        "document_type": state.get("input_class", "unknown"),
        "iso_country_codes": iso_country_codes,
        "temporal_frame": _infer_temporal_frame(text),
        "comparison_mode": comparison_mode,
        "scenario_context": scenario_context,
    }

    issue_profile = {
        "issue_labels": issue_labels,
        "jurisdiction": jurisdiction,
        "iso_country_codes": entities_dict["iso_country_codes"],
        "temporal_frame": entities_dict["temporal_frame"],
        "scenario_context": scenario_context,
    }

    return {
        **state,
        "entities": entities_dict,
        "issue_labels": issue_labels,
        "issue_profile": issue_profile,
        "comparison_mode": comparison_mode,
        "query_intent": query_intent
    }


def _classify_query_intent(query: str, entities: list[dict[str, Any]], issue_labels: list[str], iso_codes: list[str]) -> dict[str, Any]:
    labels = []
    case_names = {e["text"] for e in entities if e["label"].lower() in {"legal_case", "icj case", "arbitration case"}}
    
    if len(case_names) >= 2:
        labels.append("case_comparison")
        labels.append("named_case")
    elif len(case_names) == 1:
        labels.append("named_case")
        
    is_comparative = bool(_COMPARISON_RE.search(query))
    cross_border_scenario = len(iso_codes) >= 2 and bool(_CROSS_BORDER_SCENARIO_RE.search(query))
    if len(iso_codes) >= 2 and is_comparative:
        labels.append("jurisdiction_comparison")
        labels.append("country")
    elif cross_border_scenario:
        labels.append("cross_border_scenario")
        labels.append("jurisdiction_comparison")
        labels.append("country")
    elif iso_codes:
        labels.append("country")
        
    concept_re = re.compile(r"\b(explain|doctrine of|what is|obligations|obligations owed to|principles|principles of|law of|erga omnes)\b", re.IGNORECASE)
    if concept_re.search(query) or (not case_names and not iso_codes):
        labels.append("concept")
        labels.append("conceptual")
        
    if "international_overlay" not in labels and (len(iso_codes) > 0 and (concept_re.search(query) or "general_international_law" in issue_labels)):
        labels.append("international_overlay")
    if cross_border_scenario and "international_overlay" not in labels:
        labels.append("international_overlay")
        
    primary = []
    if "cross_border_scenario" in labels:
        primary.append("cross_border_scenario")
    if "jurisdiction_comparison" in labels:
        primary.append("jurisdiction_comparison")
    if "case_comparison" in labels:
        primary.append("case_comparison")
    if "named_case" in labels and "named_case" not in primary and "case_comparison" not in primary:
        primary.append("named_case")
    if "conceptual" in labels:
        primary.append("conceptual")
        
    if not primary:
        primary.append("mixed")
        
    return {
        "primary": primary,
        "labels": labels,
        "priority_collections": {},
        "iso_codes": iso_codes,
    }


def _infer_jurisdiction(
    entities: list[dict[str, Any]],
    issue_labels: list[str] | None = None,
    iso_codes: list[str] | None = None,
) -> str:
    entity_labels = {e["label"].lower() for e in entities}
    has_intl = bool({
        "treaty", "un body", "icj case", "treaty article",
        "legal_case", "arbitration case", "international arbitration",
    } & entity_labels)
    
    if iso_codes and has_intl:
        return "mixed"
    if iso_codes and len(iso_codes) == 1:
        return iso_codes[0].lower()
    if iso_codes and len(iso_codes) > 1:
        return "mixed"
    if has_intl:
        return "international"
    if issue_labels and _INTL_ISSUE_LABELS & set(issue_labels):
        return "international"
    return "unknown"


def _infer_iso_country_codes(entities: list[dict[str, Any]]) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        value = entity.get("text", "").lower().strip()
        code = _COUNTRY_TEXT_TO_ISO.get(value)
        if code and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _infer_scenario_context(text: str, iso_codes: list[str], issue_labels: list[str]) -> dict[str, Any]:
    lowered = text.lower()

    def first_iso(pattern: re.Pattern[str]) -> str | None:
        match = pattern.search(text)
        if not match:
            return None
        return _COUNTRY_TEXT_TO_ISO.get(match.group("country").strip().lower())

    location_iso = first_iso(_SCENARIO_LOCATION_RE) or first_iso(_GENERIC_LOCATION_RE)
    passport_iso = first_iso(_PASSPORT_COUNTRY_RE)
    licence_issuing_iso = first_iso(_LICENCE_COUNTRY_RE)

    all_isos = [code for code in [location_iso, passport_iso, licence_issuing_iso, *iso_codes] if code]
    deduped_isos: list[str] = []
    seen: set[str] = set()
    for code in all_isos:
        if code not in seen:
            seen.add(code)
            deduped_isos.append(code)

    cross_border = len(deduped_isos) >= 2 and bool(_CROSS_BORDER_SCENARIO_RE.search(text))
    treaty_focus: list[str] = []
    if cross_border and _CONSULAR_RIGHTS_RE.search(lowered):
        treaty_focus.append("consular_notification")
    if cross_border and (
        "traffic_offences" in issue_labels
        or bool(re.search(r"\b(driving|traffic|road|licen[cs]e|permit)\b", lowered))
    ):
        treaty_focus.append("foreign_licence_recognition")

    return {
        "cross_border": cross_border,
        "location_iso": location_iso,
        "passport_iso": passport_iso,
        "licence_issuing_iso": licence_issuing_iso,
        "treaty_focus": treaty_focus,
        "all_relevant_iso_codes": deduped_isos,
    }


def _infer_temporal_frame(text: str) -> str:
    lowered = text.lower()
    if any(token in lowered for token in ["would", "could", "hypothetical", "if a state", "suppose"]):
        return "hypothetical"
    if any(token in lowered for token in ["ongoing", "currently", "continuing"]):
        return "ongoing"
    if any(token in lowered for token in ["was", "were", "in 19", "in 20", "case"]):
        return "past"
    return "present"
