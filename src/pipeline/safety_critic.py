"""Legal-Risk Safety Critic for the OmniLegal council pipeline.

Intercepts queries and drafts containing:
- Evasion attempts (bribery, forged documents, false statements)
- UPL overclaiming (legal advice vs legal information)
- Privilege/confidentiality warnings

Returns helpful refusals with statutory context and lawful alternatives.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.config import LEGAL_RESEARCH_SHORT_DISCLAIMER

# ── Refusal pattern definitions ───────────────────────────────────────────

@dataclass(frozen=True)
class RefusalPattern:
    category: str
    patterns: list[str]
    severity: str  # CRITICAL, HIGH, MEDIUM
    statutory_note: str
    refusal_text: str
    lawful_alternative: str

REFUSAL_PATTERNS: list[RefusalPattern] = [
    RefusalPattern(
        category="bribery",
        patterns=["bribe", "unofficial payment", "grease payment", "pay the officer", "pay off", "how much to pay police"],
        severity="CRITICAL",
        statutory_note="Bribery of a public official is a criminal offence in virtually every jurisdiction.",
        refusal_text="I cannot provide guidance on bribing officials. This is a criminal offence that can result in imprisonment.",
        lawful_alternative="If you believe an official is soliciting a bribe, document the interaction, contact your embassy/consulate, and seek legal representation.",
    ),
    RefusalPattern(
        category="document_forgery",
        patterns=["fake licence", "fake license", "forge document", "template for licence", "fake certificate", "alter document", "falsify", "backdate"],
        severity="CRITICAL",
        statutory_note="Document forgery is a serious criminal offence carrying custodial sentences in most jurisdictions.",
        refusal_text="I cannot assist with forging, altering, or backdating documents.",
        lawful_alternative="If you need a replacement document, contact the issuing authority. If you need a translation, use a certified translator.",
    ),
    RefusalPattern(
        category="evasion",
        patterns=["avoid detection", "escape jurisdiction", "hide from authorities", "flee the country", "evade police", "run from"],
        severity="CRITICAL",
        statutory_note="Evading law enforcement can constitute obstruction of justice or additional criminal charges.",
        refusal_text="I cannot advise on evading law enforcement or fleeing jurisdiction.",
        lawful_alternative="If you are facing legal proceedings, hire a lawyer to represent you. You may have rights to bail, appeal, or other legal remedies.",
    ),
    RefusalPattern(
        category="false_statements",
        patterns=["lie to police", "false report", "fabricate alibi", "false statement", "lie under oath", "perjury"],
        severity="CRITICAL",
        statutory_note="Making false statements to authorities or under oath is a criminal offence (perjury, obstruction).",
        refusal_text="I cannot help with making false statements to authorities.",
        lawful_alternative="You generally have the right to remain silent. Consult a lawyer before making any statement.",
    ),
    RefusalPattern(
        category="upl_overclaim",
        patterns=["guarantee outcome", "you will win", "certain to succeed", "definitely legal", "i promise"],
        severity="HIGH",
        statutory_note="Providing guarantees about legal outcomes constitutes unauthorized practice of law.",
        refusal_text="Legal outcomes depend on specific facts and circumstances. No AI system can guarantee results.",
        lawful_alternative="Consult a licensed attorney for case-specific advice and outcome assessment.",
    ),
]


def check_query_safety(query: str) -> tuple[bool, str]:
    """Check if a query triggers safety refusals.
    
    Returns (is_safe, refusal_message). If is_safe is False,
    refusal_message contains the helpful refusal text.
    """
    query_lower = query.lower()
    for pattern in REFUSAL_PATTERNS:
        for trigger in pattern.patterns:
            if trigger in query_lower:
                refusal = (
                    f"## Safety Notice\n\n"
                    f"**{pattern.refusal_text}**\n\n"
                    f"**Legal context:** {pattern.statutory_note}\n\n"
                    f"**Lawful alternative:** {pattern.lawful_alternative}\n\n"
                    f"## Disclaimer\n{LEGAL_RESEARCH_SHORT_DISCLAIMER}"
                )
                return False, refusal
    return True, ""


def check_draft_safety(draft: str) -> list[dict[str, str]]:
    """Scan a draft for safety issues. Returns list of flagged items."""
    flags: list[dict[str, str]] = []
    draft_lower = draft.lower()
    for pattern in REFUSAL_PATTERNS:
        for trigger in pattern.patterns:
            if trigger in draft_lower:
                flags.append({
                    "category": pattern.category,
                    "severity": pattern.severity,
                    "trigger": trigger,
                    "note": pattern.statutory_note,
                })
    return flags
