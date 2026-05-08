"""Four-persona answer-mode configuration for OmniLegal.

Each persona has its own prompt focus, voice, and required output sections.
The chainlit UI exposes these explicitly so users pick HOW the legal answer is framed
rather than the system guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from src.schemas import AnswerMode

_LEGACY_VALUES = {
    "comparative_research": AnswerMode.researcher,
    "source_discovery": AnswerMode.researcher,
    "research": AnswerMode.researcher,
    "student": AnswerMode.law_student_case_law,
    "law_student": AnswerMode.law_student_case_law,
    "tourist": AnswerMode.tourist_practical,
    "practical": AnswerMode.tourist_practical,
    "layman_plain_english": AnswerMode.layman,
    "plain_english": AnswerMode.layman,
}


@dataclass(frozen=True)
class ModeSpec:
    mode: AnswerMode
    display_name: str
    short_label: str
    icon: str
    tagline: str
    audience: str
    voice: str
    required_sections: list[str]
    system_focus: str
    target_word_count: int = 500
    irac_format: bool = False


MODES: dict[AnswerMode, ModeSpec] = {
    AnswerMode.tourist_practical: ModeSpec(
        mode=AnswerMode.tourist_practical,
        display_name="Tourist",
        short_label="TOURIST",
        icon="\U0001F9F3",  # compass
        tagline="Practical rights, do's and don'ts for travellers",
        audience="A non-lawyer traveller in a foreign jurisdiction.",
        voice="Direct, plain English, action-oriented. No legalese, no Latin, no IRAC.",
        required_sections=[
            "Quick Answer",
            "Your Rights On The Ground",
            "What To Do Next",
            "What NOT To Do",
            "When To Get A Local Lawyer",
            "Disclaimer",
        ],
        system_focus=(
            "Write for a person who is travelling or living abroad and needs to know what to do "
            "in the next 24 hours. Lead with one sentence telling them whether they are likely "
            "OK or in trouble. Translate any law into a clear instruction. Mention treaty/consular "
            "rights only when they actually help on the ground."
        ),
        target_word_count=420,
    ),
    AnswerMode.law_student_case_law: ModeSpec(
        mode=AnswerMode.law_student_case_law,
        display_name="Law Student",
        short_label="STUDENT",
        icon="\U0001F4DA",  # books
        tagline="IRAC analysis with citations and case law",
        audience="A law student or junior associate preparing a memo or moot.",
        voice="Structured, doctrinal, IRAC. Cite with [S#] tags grounded in the retrieved sources.",
        required_sections=[
            "Issue",
            "Rule",
            "Application",
            "Conclusion",
            "Authorities Cited",
            "Disclaimer",
        ],
        system_focus=(
            "Use strict IRAC. Identify the precise legal issue, articulate the controlling rule "
            "from statute, treaty or case law, apply it to the facts in the question, and conclude. "
            "Treat Malcolm Shaw's commentary as secondary authority. Always cite primary sources "
            "first. If a case is named in the query, give its facts, holding, and ratio decidendi."
        ),
        irac_format=True,
        target_word_count=750,
    ),
    AnswerMode.researcher: ModeSpec(
        mode=AnswerMode.researcher,
        display_name="Researcher",
        short_label="RESEARCH",
        icon="\U0001F50D",  # magnifier
        tagline="Comparative, doctrinal, deep analysis",
        audience="A legal academic, policy researcher, or comparative-law specialist.",
        voice="Analytical, comparative, doctrinally precise. Surface tensions, debates and gaps.",
        required_sections=[
            "Doctrinal Framing",
            "Primary Authority Map",
            "Comparative Position",
            "Scholarly Debate",
            "Open Questions",
            "Disclaimer",
        ],
        system_focus=(
            "Treat the question as a research brief. Map the doctrine, contrast leading positions "
            "across jurisdictions where retrieved sources allow, surface scholarly disagreement "
            "(Shaw vs Brownlie / Crawford / Cassese where retrieved), and identify open or "
            "contested questions. Never paper over a conflict — flag it with [S#] tags on both sides."
        ),
        target_word_count=900,
    ),
    AnswerMode.layman: ModeSpec(
        mode=AnswerMode.layman,
        display_name="Layman",
        short_label="LAYMAN",
        icon="\U0001F4AC",  # speech bubble
        tagline="Plain English, no jargon — explain it like I'm five",
        audience="An ordinary person with no legal background who just wants the gist.",
        voice=(
            "Conversational, friendly, jargon-free. Replace every legal term with everyday "
            "language. Use short sentences. Use analogies where helpful."
        ),
        required_sections=[
            "In Plain English",
            "Why It Matters",
            "Quick Example",
            "Where To Read More",
            "Disclaimer",
        ],
        system_focus=(
            "Pretend the reader has zero legal background. Replace every Latin term, statutory "
            "section number and case citation with a one-line everyday paraphrase. Keep paragraphs "
            "short. If you must mention a law, say what it does in human terms, not just its name."
        ),
        target_word_count=350,
    ),
    AnswerMode.conflict_detector: ModeSpec(
        mode=AnswerMode.conflict_detector,
        display_name="Conflict Detector",
        short_label="CONFLICT",
        icon="\u2696",  # scales
        tagline="Compare jurisdictions, surface conflicts, apply VCLT Art. 27",
        audience="A researcher or counsel asking whether domestic and international law agree.",
        voice=(
            "Clinical, comparative, jurisdiction-by-jurisdiction. Lead with a verdict "
            "(alignment / qualified alignment / conflict / silent), then justify with cited spans. "
            "Always reference VCLT Article 27 when an actual conflict is detected."
        ),
        required_sections=[
            "Verdict",
            "International Rule",
            "Per-Jurisdiction Comparison",
            "Sharpest Disagreement",
            "VCLT Article 27 Note",
            "Disclaimer",
        ],
        system_focus=(
            "Treat the question as a cross-jurisdiction conflict question. Retrieve and weigh the "
            "international position (treaties, ICJ, customary international law), then for each "
            "domestic jurisdiction in scope (India, US, UK, Russia, Israel) decide whether it "
            "ALIGNS, QUALIFIES, CONFLICTS WITH, or is SILENT relative to the international rule. "
            "Surface the single sharpest disagreement, name it, and cite [S#] markers for both sides. "
            "Refuse to collapse genuine disagreement into agreement; under VCLT Article 27 a state "
            "cannot invoke its internal law to escape an international obligation."
        ),
        target_word_count=850,
    ),
}


def get_mode_spec(mode: AnswerMode | str) -> ModeSpec:
    if isinstance(mode, AnswerMode):
        return MODES[mode]
    raw = str(mode or "").strip().lower()
    if raw in _LEGACY_VALUES:
        return MODES[_LEGACY_VALUES[raw]]
    try:
        return MODES[AnswerMode(raw)]
    except (ValueError, KeyError):
        return MODES[AnswerMode.tourist_practical]


def parse_mode(value: AnswerMode | str | None) -> AnswerMode:
    """Loose parser that accepts canonical, legacy, or display-name strings."""
    if isinstance(value, AnswerMode):
        return value
    raw = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not raw:
        return AnswerMode.tourist_practical
    if raw in _LEGACY_VALUES:
        return _LEGACY_VALUES[raw]
    try:
        return AnswerMode(raw)
    except ValueError:
        for mode, spec in MODES.items():
            if raw == spec.display_name.lower():
                return mode
            if raw == spec.short_label.lower():
                return mode
        return AnswerMode.tourist_practical


def all_mode_specs() -> list[ModeSpec]:
    return list(MODES.values())


def section_headings(mode: AnswerMode | str) -> list[str]:
    return [f"## {section}" for section in get_mode_spec(mode).required_sections]


def build_mode_system_prompt(mode: AnswerMode | str) -> str:
    spec = get_mode_spec(mode)
    headings = "\n".join(f"  - {section}" for section in spec.required_sections)
    return (
        f"Audience: {spec.audience}\n"
        f"Voice: {spec.voice}\n"
        f"Focus: {spec.system_focus}\n"
        f"Target length: ~{spec.target_word_count} words.\n\n"
        f"Required sections (use ## H2 markdown headings, in order):\n{headings}"
    )


_TOURIST_PATTERNS = re.compile(
    r"(?i)\b(tourist|travell?er|visa|consulate|embassy|airport|police stop|driving licen[cs]e|"
    r"i am [a-z]+ in|stopped by|abroad|holiday|vacation|backpack)\b"
)
_STUDENT_PATTERNS = re.compile(
    r"(?i)\b(irac|moot|law school|exam|memorandum|brief the case|holding|ratio|dictum|stare decisis|"
    r"section \d|article \d|bns|ipc|case brief)\b"
)
_RESEARCH_PATTERNS = re.compile(
    r"(?i)\b(compare|comparative|across jurisdictions|doctrinal|debate|scholarship|literature|"
    r"customary international law|jus cogens|erga omnes|treaty interpretation|opinio juris)\b"
)
_LAYMAN_PATTERNS = re.compile(
    r"(?i)\b(explain like|eli5|plain english|in simple words|in layman|i don'?t understand law|"
    r"i'?m not a lawyer)\b"
)


def detect_answer_mode(query: str) -> AnswerMode:
    if _LAYMAN_PATTERNS.search(query):
        return AnswerMode.layman
    if _STUDENT_PATTERNS.search(query):
        return AnswerMode.law_student_case_law
    if _RESEARCH_PATTERNS.search(query):
        return AnswerMode.researcher
    if _TOURIST_PATTERNS.search(query):
        return AnswerMode.tourist_practical
    return AnswerMode.tourist_practical
