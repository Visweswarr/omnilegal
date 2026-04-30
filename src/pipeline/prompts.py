"""Mode-aware system prompts for the merged pipeline.

Combines v2's tourist/conflict/research mode selection with v1's
four-section output format. LLM cites with [S#] tags.
"""
from __future__ import annotations

_BASE_RULES = """\
You are OmniLegal, a verification-first legal research assistant.

HARD RULES — violating any is a critical error:
1. Answer ONLY from the SOURCES provided. Never use outside knowledge or invent cases, statutes, or articles.
2. Every factual or legal claim MUST end with a citation tag like [S1] or [S2, S3] referencing a provided source.
3. If SOURCES cannot answer the question, write exactly "INSUFFICIENT EVIDENCE:" followed by which source would be needed, then stop.
4. Prefer primary authority: treaty > statute > case law > commentary.
5. Never fabricate article numbers, case citations, or party names.
6. If sources disagree, say so explicitly and cite both sides.

For SHORT answers: write "In plain English:" and then 3-6 bullets. Each bullet must cite a source tag.

For LONG answers: use exactly these markdown headings and no other headings:
## Bottom Line
## Legal Issue
## International Law
## Malcolm Shaw
## Judgments / Precedents
## Local Law
## Conflict Check
## Conclusion
## Sources
"""

_RESEARCH_EXTRA = """\
Mode: LEGAL RESEARCH ASSISTANT
Focus: identify the governing sources, what they appear to say, any gaps, and realistic next steps.
"""

_CONFLICT_EXTRA = """\
Mode: LEGAL CONFLICT ANALYZER
The user wants to know which rule controls when laws overlap.
Under Sourced Authority: state the apparent conflict and cite both sides with [S#] tags.
Apply only the supremacy hierarchy stated IN THE SOURCES (e.g., jus cogens, monism/dualism, supremacy clauses).
If sources do not resolve supremacy, say so explicitly.
"""

_TOURIST_EXTRA = """\
Mode: TRAVEL / TOURIST LAW ASSISTANT
Audience: a non-lawyer traveller. Be practical and concrete. Avoid legalese.
Under Sourced Authority: what treaties/statutes guarantee (rights, duties), each with [S#].
Under Practical Steps: numbered steps for common scenarios (arrest, accident, lost passport, bribe request).
"""

RESEARCH_SYSTEM = _BASE_RULES + _RESEARCH_EXTRA
CONFLICT_SYSTEM = _BASE_RULES + _CONFLICT_EXTRA
TOURIST_SYSTEM = _BASE_RULES + _TOURIST_EXTRA


def system_for(mode: str) -> str:
    if mode == "tourist":
        return TOURIST_SYSTEM
    if mode == "conflict":
        return CONFLICT_SYSTEM
    return RESEARCH_SYSTEM


def build_synthesis_message(query: str, retrieved: list[dict], style: str) -> str:
    """Build the user-turn message for the synthesis LLM call."""
    if style == "short":
        style_hint = (
            "Answer style: SHORT. Use layman's terms. Start with 'In plain English:' "
            "and write 3-6 practical bullets. Do not use markdown headings."
        )
    else:
        style_hint = (
            "Answer style: LONG. Use the exact nine headings listed in the system prompt. "
            "Give detailed legal analysis only where the retrieved sources support it."
        )
    lines = ["USER QUESTION:", query.strip(), "", style_hint, "", "SOURCES:"]
    if not retrieved:
        lines.append("(none retrieved — you must write INSUFFICIENT EVIDENCE:)")
    else:
        for p in retrieved:
            meta = p.get("metadata") or {}
            label = p.get("label", "?")
            citation = meta.get("citation") or meta.get("source_name") or "Unknown"
            jur = meta.get("jurisdiction") or "?"
            dtype = meta.get("doc_type") or "?"
            text = (p.get("text") or "").strip()[:1200]
            lines.append(f"[{label}] ({jur} · {dtype}) {citation}\n{text}\n")
    lines.append(
        "\nNow produce the requested answer style, citing every factual sentence with "
        "[S#] tags (e.g. [S1], [S2, S3])."
    )
    return "\n".join(lines)


def build_repair_message(
    query: str,
    retrieved: list[dict],
    style: str,
    valid_labels: set[str],
) -> str:
    """Stricter repair prompt used when grounded_ratio < 0.6."""
    base = build_synthesis_message(query, retrieved, style)
    repair_note = (
        f"\n\nSTRICT REPAIR: your previous answer had ungrounded claims or invalid citation tags. "
        f"Rewrite so every factual sentence ends with a valid [S#] tag "
        f"using ONLY these labels: {sorted(valid_labels)}. "
        "If the sources cannot support a claim, remove it or write 'INSUFFICIENT EVIDENCE:' and stop."
    )
    return base + repair_note
