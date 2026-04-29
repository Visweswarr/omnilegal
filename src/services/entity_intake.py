from __future__ import annotations

import html
import re

import spacy

from src.schemas import DocumentTypeLabel, EntityIntakeResult, EntityTag, JurisdictionLabel


_NLP = None
_CUSTOM_PATTERNS = {
    "TREATY": [
        r"\bUN Charter\b",
        r"\bICCPR\b",
        r"\bICESCR\b",
        r"\bUniversal Declaration of Human Rights\b",
    ],
    "ARTICLE": [
        r"\bArticle\s+\d+[A-Za-z0-9()\-./]*",
        r"\bArt\.?\s+\d+[A-Za-z0-9()\-./]*",
    ],
    "DOMESTIC_LAW": [
        r"\bIndian Constitution\b",
        r"\bConstitution of India\b",
        r"\bCode of Criminal Procedure\b",
        r"\bIPC\b",
    ],
    "COURT": [
        r"\bSupreme Court of India\b",
        r"\bInternational Court of Justice\b",
        r"\bICJ\b",
        r"\bHigh Court\b",
    ],
    "CASE": [
        r"\b[A-Z][A-Za-z&'.-]+(?:\s+[A-Z][A-Za-z&'.-]+)*\s+(?:v\.|vs\.|versus)\s+[A-Z][A-Za-z&'.-]+(?:\s+[A-Z][A-Za-z&'.-]+)*\b",
        r"\bTinoco arbitration\b",
        r"\bCorfu Channel case\b",
    ],
    "LEGAL_PRINCIPLE": [
        r"\bjus cogens\b",
        r"\bstate responsibility\b",
        r"\bterritorial sovereignty\b",
        r"\beffective control\b",
        r"\buse of force\b",
        r"\bself-defen[cs]e\b",
        r"\bnon-intervention\b",
    ],
    "STATE_ACTOR": [
        r"\bIndia\b",
        r"\bAlbania\b",
        r"\bCosta Rica\b",
        r"\bUnited Nations\b",
        r"\bSecurity Council\b",
    ],
}
_COLORS = {
    "TREATY": "#ffcc80",
    "ARTICLE": "#90caf9",
    "DOMESTIC_LAW": "#80cbc4",
    "COURT": "#ce93d8",
    "STATE_ACTOR": "#f48fb1",
    "CASE": "#a5d6a7",
    "LEGAL_PRINCIPLE": "#ffe082",
}


def _get_nlp():
    global _NLP
    if _NLP is None:
        try:
            _NLP = spacy.load("en_core_web_sm")
        except OSError:
            _NLP = None
    return _NLP


def _add_entity(
    entities: list[EntityTag],
    seen: set[tuple[int, int, str]],
    text: str,
    label: str,
    start: int,
    end: int,
    source: str,
):
    key = (start, end, label)
    if key in seen:
        return
    seen.add(key)
    entities.append(
        EntityTag(text=text[start:end], label=label, start=start, end=end, source=source)
    )


def _detect_entities(text: str) -> list[EntityTag]:
    entities: list[EntityTag] = []
    seen: set[tuple[int, int, str]] = set()

    nlp = _get_nlp()
    if nlp is not None:
        doc = nlp(text)
        for ent in doc.ents:
            if ent.label_ in {"ORG", "GPE", "PERSON", "DATE"}:
                _add_entity(
                    entities,
                    seen,
                    text,
                    ent.label_,
                    ent.start_char,
                    ent.end_char,
                    "spacy",
                )

    for label, patterns in _CUSTOM_PATTERNS.items():
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                _add_entity(entities, seen, text, label, match.start(), match.end(), "pattern")

    entities.sort(key=lambda entity: (entity.start, entity.end))
    return entities


def _classify_jurisdiction(text: str, entities: list[EntityTag]) -> tuple[JurisdictionLabel, float]:
    lowered = text.lower()
    international_hits = sum(
        token in lowered for token in ["un charter", "iccpr", "icescr", "international", "treaty", "icj"]
    ) + sum(entity.label == "TREATY" for entity in entities)
    indian_hits = sum(
        token in lowered for token in ["indian constitution", "constitution of india", "india", "supreme court of india"]
    ) + sum(entity.label == "DOMESTIC_LAW" for entity in entities)

    if international_hits and indian_hits:
        return "mixed", 0.9
    if international_hits:
        return "international", 0.8
    if indian_hits:
        return "indian", 0.8
    return "unknown", 0.4


def _classify_document_type(text: str, entities: list[EntityTag]) -> DocumentTypeLabel:
    lowered = text.lower()
    if any(entity.label == "TREATY" for entity in entities):
        return "treaty"
    if any(entity.label == "CASE" for entity in entities) or " v. " in lowered or " versus " in lowered:
        return "case_law"
    if any(entity.label == "DOMESTIC_LAW" for entity in entities) or "constitution" in lowered:
        return "constitutional_text"
    if "resolution" in lowered or "draft resolution" in lowered:
        return "resolution"
    if "chapter" in lowered or "shaw" in lowered:
        return "commentary"
    return "mixed_legal_text"


def _render_entity_html(text: str, entities: list[EntityTag]) -> str:
    if not entities:
        return (
            "<div style='padding:12px;background:#141822;color:#f5f5f5;border-radius:12px;'>"
            f"{html.escape(text)}</div>"
        )

    parts: list[str] = []
    cursor = 0
    for entity in entities:
        if entity.start < cursor:
            continue
        parts.append(html.escape(text[cursor:entity.start]))
        color = _COLORS.get(entity.label, "#b0bec5")
        parts.append(
            f"<mark style='background:{color};padding:2px 6px;border-radius:8px;'>"
            f"{html.escape(text[entity.start:entity.end])}"
            f" <strong style='font-size:11px'>{html.escape(entity.label)}</strong></mark>"
        )
        cursor = entity.end
    parts.append(html.escape(text[cursor:]))
    return (
        "<div style='padding:16px;line-height:1.8;background:#141822;color:#f5f5f5;"
        "border-radius:12px;font-family:Segoe UI, sans-serif;'>"
        + "".join(parts)
        + "</div>"
    )


def analyze_text(text: str) -> EntityIntakeResult:
    entities = _detect_entities(text)
    jurisdiction, confidence = _classify_jurisdiction(text, entities)
    document_type = _classify_document_type(text, entities)
    return EntityIntakeResult(
        original_text=text,
        entities=entities,
        jurisdiction=jurisdiction,
        document_type=document_type,
        confidence=confidence,
        html=_render_entity_html(text, entities),
    )
