"""Mode-aware system prompts for OmniLegal's four personas.

Each persona pairs the universal verification rules with persona-specific voice
and section structure. The synthesizer always passes the active mode to
`system_for(mode)` and `build_synthesis_message(query, retrieved, mode)`.
"""
from __future__ import annotations

from typing import Any

from src.schemas import AnswerMode
from src.services.answer_modes import build_mode_system_prompt, get_mode_spec, parse_mode

_BASE_RULES = """\
You are OmniLegal, a verification-first international and comparative legal research assistant.

HARD RULES — violating any is a critical error:
1. Answer ONLY from the SOURCES provided below. Never invent cases, statutes, or articles.
2. Every legal claim MUST end with a citation tag like [S1] or [S2, S3] referencing a provided source.
3. If SOURCES cannot answer the question, write exactly "INSUFFICIENT EVIDENCE:" followed by what would be needed, then stop.
4. Prefer primary authority: treaty > statute > case law > commentary (Malcolm Shaw is commentary).
5. Never fabricate article numbers, case citations, or party names.
6. If the sources disagree, say so explicitly and cite both sides.
7. Keep the tone matched to the chosen Persona below — DO NOT mix voices across personas.
"""


def system_for(mode: AnswerMode | str) -> str:
    """Build a complete system prompt for the chosen persona."""
    parsed = parse_mode(mode)
    spec = get_mode_spec(parsed)
    persona_block = build_mode_system_prompt(parsed)
    return (
        f"{_BASE_RULES}\n"
        f"PERSONA: {spec.display_name.upper()} — {spec.tagline}\n"
        f"{persona_block}\n"
    )


def build_synthesis_message(
    query: str,
    retrieved: list[dict[str, Any]],
    mode: AnswerMode | str,
) -> str:
    """Build the user-turn message with retrieved [S#]-labelled sources."""
    parsed = parse_mode(mode)
    spec = get_mode_spec(parsed)

    style_hint = (
        f"Persona: {spec.display_name} ({spec.tagline}).\n"
        f"Voice: {spec.voice}\n"
        f"Required sections (markdown ## H2, in this order): "
        f"{', '.join(spec.required_sections)}.\n"
        f"Target length: roughly {spec.target_word_count} words."
    )

    lines: list[str] = ["USER QUESTION:", query.strip(), "", style_hint, "", "SOURCES:"]
    if not retrieved:
        lines.append(
            "(no passages were retrieved — write 'INSUFFICIENT EVIDENCE:' and stop unless you can answer purely from your own knowledge in a non-citing way)."
        )
    else:
        for passage in retrieved:
            metadata = passage.get("metadata") or {}
            label = passage.get("label", "?")
            citation = metadata.get("citation") or metadata.get("source_name") or "Unknown"
            jurisdiction = metadata.get("jurisdiction") or "?"
            doc_type = metadata.get("doc_type") or "?"
            page = metadata.get("page") or metadata.get("page_start") or ""
            page_str = f" p.{page}" if page else ""
            text = (passage.get("text") or "").strip()[:1400]
            lines.append(f"[{label}] ({jurisdiction} \u00b7 {doc_type}{page_str}) {citation}\n{text}\n")
    lines.append(
        "\nNow produce the answer. Respect the Persona voice and the required section list. "
        "Cite every legal claim with [S#] tags. If the sources are sparse, lean on Malcolm Shaw "
        "and the international treaties already retrieved rather than guessing."
    )
    return "\n".join(lines)


def build_repair_message(
    query: str,
    retrieved: list[dict[str, Any]],
    mode: AnswerMode | str,
    valid_labels: set[str],
) -> str:
    """Stricter prompt used when grounded_ratio is below threshold."""
    base = build_synthesis_message(query, retrieved, mode)
    repair_note = (
        "\n\nSTRICT REPAIR: your previous answer had ungrounded claims or invalid citation tags. "
        f"Rewrite so every legal sentence ends with a valid [S#] tag using ONLY these labels: "
        f"{sorted(valid_labels)}. If a sentence cannot be supported, delete it or write "
        "'INSUFFICIENT EVIDENCE:' and stop."
    )
    return base + repair_note


# Backwards-compatible aliases for legacy callers
RESEARCH_SYSTEM = system_for(AnswerMode.researcher)
TOURIST_SYSTEM = system_for(AnswerMode.tourist_practical)
CONFLICT_SYSTEM = system_for(AnswerMode.researcher)
