"""Cross-jurisdiction IRAC synthesis.

Given a research question, retrieves the strongest passages per jurisdiction
and asks the LLM to produce a per-jurisdiction IRAC (Issue, Rule,
Application, Conclusion) plus a comparative summary. Also exposes a
``markdown_comparison_table`` helper that the Chainlit UI uses to render the
side-by-side comparison the PDF brief calls for.

Pipeline:
    query → retrieve top-K per jurisdiction (intl + domestic[]) →
    per-jurisdiction IRAC prompt (Claude / Gemini fallback) → cross-jur
    synthesis prompt that flags agreements, disagreements, and gaps.

Designed to be called sequentially per jurisdiction (parallel fan-out can
be added once we move off Emergent's single-session client).
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

log = logging.getLogger("omnilegal.cross_jurisdiction")


_IRAC_SYSTEM = """You are OmniLegal's per-jurisdiction IRAC synthesizer.
Given retrieved passages from one jurisdiction and a research question, write
a tight IRAC analysis. Cite the retrieved sources by their [S#] markers if
they are present in the passages; never invent citations.

Return STRICT JSON only with schema:
{
  "issue": "<one sentence: the precise legal issue this jurisdiction faces>",
  "rule": "<2-4 sentences: the controlling rule(s) drawn from the passages>",
  "application": "<2-5 sentences: how the rule applies to the question>",
  "conclusion": "<one sentence: lawful | unlawful | indeterminate | lawful_if_conditions, plus rationale>",
  "conditions_if_any": "<conditions that would change the conclusion, or empty>",
  "confidence": <float 0..1>,
  "key_authorities": ["<source name 1>", "<source name 2>"]
}
"""


_SYNTH_SYSTEM = """You are OmniLegal's cross-jurisdiction comparator.
You will receive several per-jurisdiction IRAC blocks plus an international
baseline. Produce a comparative synthesis that:
1. States the strongest international rule.
2. For each domestic jurisdiction, says whether it ALIGNS, QUALIFIES,
   CONFLICTS WITH, or is SILENT vs the international rule.
3. Identifies the single sharpest disagreement, if any.
4. Identifies any gap (jurisdictions for which retrieval was thin).
5. Reminds the reader of VCLT Article 27 only if a real conflict exists.

Return STRICT JSON with schema:
{
  "international_rule_summary": "...",
  "agreements": ["..."],
  "disagreements": ["..."],
  "gaps": ["..."],
  "vclt_article_27_warning": "<empty if no real conflict>"
}
"""


def _safe_truncate(text: str, max_chars: int = 4000) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def per_jurisdiction_irac(
    query: str,
    jurisdiction: str,
    passages_text: str,
) -> dict[str, Any]:
    if not passages_text.strip():
        return {
            "jurisdiction": jurisdiction,
            "issue": "No retrieved authority for this jurisdiction.",
            "rule": "",
            "application": "",
            "conclusion": "indeterminate — no source",
            "conditions_if_any": "",
            "confidence": 0.0,
            "key_authorities": [],
        }
    try:
        from src.services.emergent_llm import generate_with_fallback
    except Exception as exc:
        log.warning("Emergent LLM unavailable: %s", exc)
        return {
            "jurisdiction": jurisdiction,
            "issue": query,
            "rule": "",
            "application": "",
            "conclusion": "indeterminate",
            "conditions_if_any": "",
            "confidence": 0.0,
            "key_authorities": [],
            "error": str(exc),
        }

    user_prompt = (
        f"Jurisdiction: {jurisdiction}\n\n"
        f"Research question:\n\"\"\"{query}\"\"\"\n\n"
        f"Retrieved passages:\n\"\"\"{_safe_truncate(passages_text)}\"\"\"\n\n"
        "Return JSON only."
    )
    result = generate_with_fallback(
        system=_IRAC_SYSTEM,
        prompt=user_prompt,
        timeout_seconds=float(os.getenv("OMNILEGAL_IRAC_TIMEOUT_SECONDS", "30")),
    )
    parsed = _parse_json(result.text) if result.text else None
    if not parsed:
        return {
            "jurisdiction": jurisdiction,
            "issue": query,
            "rule": "",
            "application": "",
            "conclusion": "indeterminate",
            "conditions_if_any": "",
            "confidence": 0.0,
            "key_authorities": [],
            "error": result.error or "model returned non-JSON",
            "used_model": f"{result.provider}/{result.model}",
        }
    parsed["jurisdiction"] = jurisdiction
    parsed["used_model"] = f"{result.provider}/{result.model}"
    return parsed


def cross_jurisdiction_synthesis(
    international_summary: str,
    irac_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    if not irac_blocks:
        return {
            "international_rule_summary": international_summary,
            "agreements": [],
            "disagreements": [],
            "gaps": ["No per-jurisdiction IRAC blocks generated."],
            "vclt_article_27_warning": "",
        }
    try:
        from src.services.emergent_llm import generate_with_fallback
    except Exception:
        return {
            "international_rule_summary": international_summary,
            "agreements": [],
            "disagreements": [],
            "gaps": [b.get("jurisdiction", "") for b in irac_blocks if not b.get("rule")],
            "vclt_article_27_warning": "",
        }

    blocks_text = json.dumps(irac_blocks, ensure_ascii=False, indent=2)
    user_prompt = (
        f"International rule summary:\n\"\"\"{_safe_truncate(international_summary, 2000)}\"\"\"\n\n"
        f"Per-jurisdiction IRAC blocks:\n{_safe_truncate(blocks_text, 8000)}\n\n"
        "Return JSON only."
    )
    result = generate_with_fallback(
        system=_SYNTH_SYSTEM,
        prompt=user_prompt,
        timeout_seconds=float(os.getenv("OMNILEGAL_SYNTH_TIMEOUT_SECONDS", "30")),
    )
    parsed = _parse_json(result.text) if result.text else None
    if not parsed:
        return {
            "international_rule_summary": international_summary,
            "agreements": [],
            "disagreements": [],
            "gaps": [b.get("jurisdiction", "") for b in irac_blocks if not b.get("rule")],
            "vclt_article_27_warning": "",
            "error": result.error or "synthesis returned non-JSON",
        }
    parsed.setdefault("international_rule_summary", international_summary)
    parsed["used_model"] = f"{result.provider}/{result.model}"
    return parsed


def markdown_comparison_table(
    irac_blocks: list[dict[str, Any]],
) -> str:
    """Render a Markdown side-by-side IRAC table."""
    if not irac_blocks:
        return ""
    headers = ["Jurisdiction", "Rule (1-line)", "Application", "Conclusion", "Confidence"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for block in irac_blocks:
        rule = (block.get("rule") or "").replace("\n", " ").strip()
        rule = rule[:140] + "…" if len(rule) > 140 else rule
        app = (block.get("application") or "").replace("\n", " ").strip()
        app = app[:140] + "…" if len(app) > 140 else app
        concl = (block.get("conclusion") or "").replace("\n", " ").strip()
        concl = concl[:80] + "…" if len(concl) > 80 else concl
        conf = block.get("confidence", 0.0)
        try:
            conf_str = f"{float(conf):.2f}"
        except (TypeError, ValueError):
            conf_str = "—"
        lines.append(
            "| " + " | ".join([
                str(block.get("jurisdiction", "—")),
                rule or "—",
                app or "—",
                concl or "—",
                conf_str,
            ]) + " |"
        )
    return "\n".join(lines)


def comparison_payload(query: str, domestic_jurisdictions: list[str]) -> dict[str, Any]:
    """Top-level helper: retrieve, run IRAC for each jurisdiction, then synthesize."""
    from src.services.conflict_detection import (
        _retrieve_for_jurisdiction,  # noqa: WPS437
        _retrieve_international,  # noqa: WPS437
    )

    international_passages = _retrieve_international(query)
    international_text = "\n\n".join(
        f"[{i+1}] {p.citation.source_name}: {p.content}"
        for i, p in enumerate(international_passages)
    )[:6000]

    international_irac = per_jurisdiction_irac(
        query, "International (UN Charter / VCLT / treaties)", international_text,
    )

    domestic_blocks: list[dict[str, Any]] = []
    for jur in domestic_jurisdictions:
        passages = _retrieve_for_jurisdiction(query, jur)
        text = "\n\n".join(
            f"[{i+1}] {p.citation.source_name}: {p.content}"
            for i, p in enumerate(passages)
        )[:6000]
        block = per_jurisdiction_irac(query, jur, text)
        block["domestic_passages"] = [
            {
                "source_name": p.citation.source_name,
                "marker": p.citation.marker,
                "page": p.citation.page,
                "excerpt": p.citation.excerpt or p.content[:240],
            }
            for p in passages
        ]
        domestic_blocks.append(block)

    all_blocks = [international_irac, *domestic_blocks]
    synthesis = cross_jurisdiction_synthesis(
        international_summary=international_irac.get("rule") or international_irac.get("issue", ""),
        irac_blocks=all_blocks,
    )
    return {
        "query": query,
        "international_irac": international_irac,
        "domestic_iracs": domestic_blocks,
        "synthesis": synthesis,
        "comparison_table_markdown": markdown_comparison_table(all_blocks),
        "international_passages": [
            {
                "source_name": p.citation.source_name,
                "marker": p.citation.marker,
                "page": p.citation.page,
                "excerpt": p.citation.excerpt or p.content[:240],
            }
            for p in international_passages
        ],
    }
