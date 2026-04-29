"""Answer-mode configuration for specialised legal output."""
from __future__ import annotations
import re
from dataclasses import dataclass
from src.schemas import AnswerMode

@dataclass(frozen=True)
class ModeSpec:
    mode: AnswerMode
    display_name: str
    required_sections: list[str]
    system_focus: str
    irac_format: bool = False

MODES: dict[AnswerMode, ModeSpec] = {
    AnswerMode.tourist_practical: ModeSpec(
        mode=AnswerMode.tourist_practical,
        display_name="Tourist / Practical",
        required_sections=["Quick Answer","Key Rights & Protections","Practical Steps","What Not to Do","Disclaimer"],
        system_focus="Write for a traveller who needs clear, actionable guidance. Lead with the bottom line. Explain rights in plain language.",
    ),
    AnswerMode.law_student_case_law: ModeSpec(
        mode=AnswerMode.law_student_case_law,
        display_name="Law Student / Case Law",
        required_sections=["Issue","Rule","Application","Conclusion","Historical Context","Disclaimer"],
        system_focus="Use IRAC format. State the legal issue precisely. Identify the governing rule with citations.",
        irac_format=True,
    ),
    AnswerMode.comparative_research: ModeSpec(
        mode=AnswerMode.comparative_research,
        display_name="Comparative Research",
        required_sections=["Jurisdictions Overview","Comparative Table","Doctrinal Divergences","Disclaimer"],
        system_focus="Compare legal positions across multiple jurisdictions. Use a table where feasible.",
    ),
    AnswerMode.source_discovery: ModeSpec(
        mode=AnswerMode.source_discovery,
        display_name="Source Discovery",
        required_sections=["Sources Found","Authority Tier","Coverage Gaps","Disclaimer"],
        system_focus="Minimal narrative. List every retrieved source with its authority tier and jurisdiction.",
    ),
}

def get_mode_spec(mode: AnswerMode | str) -> ModeSpec:
    if isinstance(mode, str):
        try: mode = AnswerMode(mode)
        except ValueError: mode = AnswerMode.tourist_practical
    return MODES.get(mode, MODES[AnswerMode.tourist_practical])

_CASE_PATTERNS = re.compile(r"(?i)(explain|analyse|analyze|discuss|brief|summarize).*(section|bns|ipc|article|case|v\.\s|arbitration|tinoco|nicaragua|holding|dissent)")
_COMPARE_PATTERNS = re.compile(r"(?i)(compare|comparison|comparative|differ|contrast|versus|across jurisdictions)")
_DISCOVERY_PATTERNS = re.compile(r"(?i)(find\s+(?:all\s+)?sources|list\s+(?:all\s+)?authorities|what\s+sources|cite\s+all|which\s+statutes\s+(?:apply|exist|govern)|list\s+(?:all\s+)?cases|find\s+all\s+(?:sources|authorities|cases))")

def detect_answer_mode(query: str) -> AnswerMode:
    if _COMPARE_PATTERNS.search(query): return AnswerMode.comparative_research
    if _CASE_PATTERNS.search(query): return AnswerMode.law_student_case_law
    if _DISCOVERY_PATTERNS.search(query): return AnswerMode.source_discovery
    return AnswerMode.tourist_practical

def section_headings(mode: AnswerMode | str) -> list[str]:
    return [f"## {s}" for s in get_mode_spec(mode).required_sections]

def build_mode_system_prompt(mode: AnswerMode | str) -> str:
    spec = get_mode_spec(mode)
    headings = "\n".join(f"  - {s}" for s in spec.required_sections)
    return f"{spec.system_focus}\n\nRequired sections:\n{headings}"
