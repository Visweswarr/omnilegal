"""OmniLegal — premium Chainlit research console (v2).

Persona-driven legal RAG (Tourist / Law Student / Researcher / Layman /
**Conflict Detector**). Question → persona → LangGraph evidence pipeline →
grounded answer with [S#] citations, an expandable Sources panel, and (in
Conflict mode) a side-by-side cross-jurisdiction comparison.

Quick triggers:
    /conflict <question>     → run cross-jurisdiction conflict analyzer
    /compare <question>      → alias of /conflict
    /irac <question>         → run per-jurisdiction IRAC + comparison table
    /verify                  → re-run citation audit on the last answer
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chainlit as cl  # noqa: E402

from src.config import LEGAL_RESEARCH_DISCLAIMER  # noqa: E402
from src.schemas import AnswerMode  # noqa: E402
from src.services.answer_modes import all_mode_specs, get_mode_spec, parse_mode  # noqa: E402
from src.services.citation_verification import (  # noqa: E402
    render_verification_markdown,
    verify_answer_citations,
)
from src.services.production_controls import check_rate_limit, write_trace  # noqa: E402
from src.services.ui_sanitizer import clean_answer_text  # noqa: E402

log = logging.getLogger("omnilegal.chainlit")

_ACTIVE_MODE_KEY = "active_mode"
_LAST_ANSWER_KEY = "last_answer"
_LAST_RETRIEVED_KEY = "last_retrieved"
_DEFAULT_MODE = AnswerMode(
    os.environ.get("OMNILEGAL_DEFAULT_ANSWER_MODE", AnswerMode.tourist_practical.value)
)


# ── Persona / mode selection (Chainlit 2.x ChatProfiles) ────────────────────


@cl.set_chat_profiles
async def chat_profiles(_user=None) -> list[cl.ChatProfile]:
    profiles: list[cl.ChatProfile] = []
    for spec in all_mode_specs():
        profiles.append(
            cl.ChatProfile(
                name=spec.display_name,
                markdown_description=(
                    f"**{spec.display_name}** \u00b7 {spec.tagline}\n\n"
                    f"_Audience_: {spec.audience}\n\n"
                    f"_Voice_: {spec.voice}"
                ),
                icon=f"https://api.iconify.design/lucide/{_icon_for(spec.mode)}.svg",
                default=(spec.mode == _DEFAULT_MODE),
            )
        )
    return profiles


def _icon_for(mode: AnswerMode) -> str:
    return {
        AnswerMode.tourist_practical: "compass",
        AnswerMode.law_student_case_law: "graduation-cap",
        AnswerMode.researcher: "microscope",
        AnswerMode.layman: "message-circle",
        AnswerMode.conflict_detector: "scale",
    }.get(mode, "scale")


# ── Helpers ────────────────────────────────────────────────────────────────


def _selected_mode() -> AnswerMode:
    cached = cl.user_session.get(_ACTIVE_MODE_KEY)
    if isinstance(cached, AnswerMode):
        return cached
    name = cl.user_session.get("chat_profile") or ""
    parsed = parse_mode(name)
    cl.user_session.set(_ACTIVE_MODE_KEY, parsed)
    return parsed


def _collection_count() -> int:
    try:
        from src.rag.vector_store import get_store

        store = get_store()
        return sum(store.collection_point_count(col) for col in store.available_collections())
    except Exception:
        return 0


def _normalise_inline_citations(text: str) -> str:
    import re

    def fix_group(match: "re.Match[str]") -> str:
        inside = match.group(1)
        if "S" in inside.upper():
            return match.group(0)
        labels = [piece.strip() for piece in inside.split(",") if piece.strip().isdigit()]
        if not labels:
            return match.group(0)
        return "[" + ", ".join(f"S{label}" for label in labels) + "]"

    return re.sub(r"\[([0-9]+(?:\s*,\s*[0-9]+)*)\]", fix_group, text)


def _run_graph(query: str, mode: AnswerMode) -> dict[str, Any]:
    from src.pipeline.graph import compiled_graph

    state = compiled_graph.invoke(
        {
            "raw_input": query,
            "answer_style": "long",
            "answer_mode": mode.value,
            "mode": mode.value,
        }
    )
    final = state.get("final") or {}
    answer = final.get("answer") or state.get("verified_draft") or state.get("draft") or ""
    retrieved = state.get("retrieved") or []
    return {
        "answer": _normalise_inline_citations(clean_answer_text(str(answer))),
        "insufficient": bool(final.get("insufficient_context") or state.get("insufficient_context")),
        "provider": state.get("provider") or final.get("used_model") or "unknown",
        "retrieved": retrieved,
        "gemini_fallback_used": bool(state.get("gemini_fallback_used")),
        "gemini_fallback_model": state.get("gemini_fallback_model") or "",
        "source_plan": state.get("source_plan") or {},
        "authority_gaps": final.get("authority_gaps") or state.get("authority_gaps") or [],
    }


def _format_diagnostics(mode: AnswerMode, result: dict[str, Any]) -> str:
    spec = get_mode_spec(mode)
    provider = str(result.get("provider") or "unknown")
    used_gemini = result.get("gemini_fallback_used")
    badge_provider = provider.split("/")[0] if "/" in provider else provider
    if used_gemini:
        badge_provider = "gemini-fallback"
    retrieved = len(result.get("retrieved") or [])
    return (
        f"**Persona**: {spec.display_name} \u00b7 **Sources retrieved**: {retrieved}"
        f" \u00b7 **Engine**: `{badge_provider}`"
    )


def _build_sources_text(retrieved: list[dict[str, Any]]) -> str:
    if not retrieved:
        return "_No grounded source passages were retrieved for this query._"
    lines: list[str] = []
    for index, passage in enumerate(retrieved[:8], start=1):
        meta = passage.get("metadata") or {}
        source = meta.get("source_name") or meta.get("citation") or "Unknown source"
        citation = meta.get("citation") or ""
        jurisdiction = meta.get("jurisdiction") or ""
        doc_type = meta.get("doc_type") or ""
        page = meta.get("page") or meta.get("page_start") or ""
        page_str = f", p.{page}" if page else ""
        excerpt = " ".join((passage.get("text") or "").split())
        if len(excerpt) > 380:
            excerpt = excerpt[:380].rsplit(" ", 1)[0] + "\u2026"
        header = f"**[S{index}]** {source}{page_str}"
        meta_bits = [bit for bit in [jurisdiction, doc_type, citation] if bit and bit != source]
        if meta_bits:
            sep = " \u00b7 "
            header += "  \u00b7 _" + sep.join(meta_bits) + "_"
        lines.append(f"{header}\n\n> {excerpt}")
    return "\n\n---\n\n".join(lines)


# ── Conflict detector renderer ─────────────────────────────────────────────


_CONFLICT_LABEL_BADGE = {
    "alignment": "🟢 Alignment",
    "qualified_alignment": "🟠 Qualified alignment",
    "conflict": "🔴 Conflict",
    "neutral": "🟡 Neutral / silent",
}


def _render_conflict_payload(payload: dict[str, Any]) -> str:
    verdict = payload.get("verdict", "—")
    verdict_human = payload.get("verdict_human", "")
    counts = payload.get("label_counts") or {}
    intl_summary = payload.get("international_position") or "_(no international position retrieved)_"

    lines = [
        f"## Cross-Jurisdiction Conflict Report",
        f"**Verdict**: `{verdict.replace('_', ' ').title()}` — {verdict_human}",
        "",
        f"**Label tally** · 🟢 alignment {counts.get('alignment', 0)} "
        f"· 🟠 qualified {counts.get('qualified_alignment', 0)} "
        f"· 🔴 conflict {counts.get('conflict', 0)} "
        f"· 🟡 neutral {counts.get('neutral', 0)}",
        "",
        f"### International baseline",
        intl_summary,
        "",
        "### Per-jurisdiction comparison",
    ]

    table = [
        "| Jurisdiction | Verdict | Confidence | International position | Domestic position | VCLT Art. 27 |",
        "|---|---|---|---|---|---|",
    ]
    for entry in payload.get("per_jurisdiction") or []:
        label = entry.get("label", "neutral")
        badge = _CONFLICT_LABEL_BADGE.get(label, label)
        intl_pos = (entry.get("international_position") or "—").replace("\n", " ")[:160]
        dom_pos = (entry.get("domestic_position") or "—").replace("\n", " ")[:160]
        vclt = "⚠ yes" if entry.get("vclt_article_27_implicated") else "no"
        try:
            conf = f"{float(entry.get('confidence', 0)):.2f}"
        except (TypeError, ValueError):
            conf = "—"
        table.append(
            f"| **{entry.get('jurisdiction', '—')}** | {badge} | {conf} | "
            f"{intl_pos or '—'} | {dom_pos or '—'} | {vclt} |"
        )
    lines.extend(table)
    lines.append("")

    # Per-jurisdiction details with rationale spans
    for entry in payload.get("per_jurisdiction") or []:
        label = entry.get("label", "neutral")
        badge = _CONFLICT_LABEL_BADGE.get(label, label)
        lines.append(f"#### {entry.get('jurisdiction', '—')} — {badge}")
        if entry.get("explanation"):
            lines.append(entry["explanation"])
        spans = entry.get("rationale_spans") or []
        if spans:
            lines.append("")
            lines.append("_Supporting spans (international text):_")
            for span in spans[:3]:
                clipped = (span or "").strip()
                if len(clipped) > 280:
                    clipped = clipped[:280] + "…"
                lines.append(f"> {clipped}")
        lines.append("")

    if any(
        entry.get("vclt_article_27_implicated") for entry in payload.get("per_jurisdiction") or []
    ):
        lines.append("> ⚠ **VCLT Article 27 reminder**: a State may not invoke its internal law as justification for failing to perform an international obligation.")
        lines.append("")

    return "\n".join(lines)


# ── Slash command parsing ──────────────────────────────────────────────────


def _parse_slash_command(text: str) -> tuple[str | None, str]:
    text = text.strip()
    if not text.startswith("/"):
        return None, text
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower().lstrip("/")
    rest = parts[1].strip() if len(parts) > 1 else ""
    return cmd, rest


# ── Chainlit entrypoints ───────────────────────────────────────────────────


@cl.on_chat_start
async def on_start() -> None:
    mode = _selected_mode()
    spec = get_mode_spec(mode)
    count = _collection_count()
    corpus_line = (
        f"\u25C6 Indexed source passages: **{count:,}**." if count else
        "\u25C6 Corpus is empty. Run `python scripts/bootstrap_corpus.py` or hit `POST /api/ingestion/run` to index."
    )
    quick = (
        "**Quick triggers:**\n"
        "- `/conflict <your question>` — cross-jurisdiction conflict report (US ↔ UK ↔ India ↔ Russia ↔ Israel ↔ International)\n"
        "- `/irac <your question>` — per-jurisdiction IRAC + comparison table\n"
        "- `/verify` — re-run the citation audit on the last answer\n"
    )
    welcome = (
        f"### OmniLegal — Multi-Jurisdiction Legal Research Console\n\n"
        f"You're talking to the **{spec.display_name}** persona. _{spec.tagline}_.\n\n"
        f"_Voice_: {spec.voice}\n\n"
        f"{corpus_line}\n\n"
        "Ask any international, comparative, or jurisdiction-specific question. "
        "Switch persona at any time via the panel on the left.\n\n"
        f"{quick}\n"
        f"{LEGAL_RESEARCH_DISCLAIMER}"
    )
    await cl.Message(content=welcome, author="OmniLegal").send()


@cl.on_settings_update
async def on_settings_update(settings: dict[str, Any]) -> None:  # pragma: no cover - UI hook
    profile = settings.get("chat_profile") if isinstance(settings, dict) else None
    if profile:
        cl.user_session.set(_ACTIVE_MODE_KEY, parse_mode(profile))


async def _handle_conflict_command(rest: str) -> None:
    if not rest:
        await cl.Message(
            content="Usage: `/conflict <your question>` — e.g. `/conflict can a state torture detainees during war?`",
            author="OmniLegal",
        ).send()
        return
    status = cl.Message(
        content=(
            "🔍 Running cross-jurisdiction conflict analyzer "
            "(retrieving + LLM entailment across India, US, UK, Russia, Israel, International)…"
        ),
        author="OmniLegal",
    )
    await status.send()
    try:
        from src.services.conflict_detection import analyze_multi_jurisdiction_conflict

        payload = await asyncio.to_thread(
            analyze_multi_jurisdiction_conflict, rest, ["india", "us", "uk", "russia", "israel"],
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("conflict analysis failed")
        await status.remove()
        await cl.Message(
            content=f"Conflict analysis failed: `{type(exc).__name__}: {exc}`",
            author="OmniLegal",
        ).send()
        return
    await status.remove()
    await cl.Message(
        content=_render_conflict_payload(payload),
        author="OmniLegal",
    ).send()


async def _handle_irac_command(rest: str) -> None:
    if not rest:
        await cl.Message(
            content="Usage: `/irac <your question>` — produces a per-jurisdiction IRAC + comparison table.",
            author="OmniLegal",
        ).send()
        return
    status = cl.Message(
        content="🧠 Running per-jurisdiction IRAC synthesis…",
        author="OmniLegal",
    )
    await status.send()
    try:
        from src.services.cross_jurisdiction import comparison_payload

        payload = await asyncio.to_thread(
            comparison_payload, rest, ["india", "us", "uk", "russia", "israel"],
        )
    except Exception as exc:  # noqa: BLE001
        log.exception("irac analysis failed")
        await status.remove()
        await cl.Message(
            content=f"IRAC analysis failed: `{type(exc).__name__}: {exc}`",
            author="OmniLegal",
        ).send()
        return
    await status.remove()
    await cl.Message(
        content=f"## Cross-jurisdiction IRAC\n\n{payload.get('comparison_table_markdown', '')}",
        author="OmniLegal",
    ).send()
    intl = payload.get("international_irac") or {}
    intl_block = (
        f"### International (UN Charter / VCLT / treaties)\n"
        f"**Issue**: {intl.get('issue', '—')}\n\n"
        f"**Rule**: {intl.get('rule', '—')}\n\n"
        f"**Application**: {intl.get('application', '—')}\n\n"
        f"**Conclusion**: {intl.get('conclusion', '—')}\n"
    )
    await cl.Message(content=intl_block, author="OmniLegal").send()
    for block in payload.get("domestic_iracs") or []:
        text = (
            f"### {block.get('jurisdiction', '—')}\n"
            f"**Issue**: {block.get('issue', '—')}\n\n"
            f"**Rule**: {block.get('rule', '—')}\n\n"
            f"**Application**: {block.get('application', '—')}\n\n"
            f"**Conclusion**: {block.get('conclusion', '—')}\n"
        )
        await cl.Message(content=text, author="OmniLegal").send()
    synth = payload.get("synthesis") or {}
    synth_lines = [
        "### Comparative synthesis",
        f"**International rule summary**: {synth.get('international_rule_summary', '—')}",
        "",
    ]
    if synth.get("agreements"):
        synth_lines.append("**Agreements**:")
        for a in synth["agreements"]:
            synth_lines.append(f"- {a}")
        synth_lines.append("")
    if synth.get("disagreements"):
        synth_lines.append("**Disagreements**:")
        for a in synth["disagreements"]:
            synth_lines.append(f"- {a}")
        synth_lines.append("")
    if synth.get("gaps"):
        synth_lines.append("**Gaps**:")
        for a in synth["gaps"]:
            synth_lines.append(f"- {a}")
        synth_lines.append("")
    if synth.get("vclt_article_27_warning"):
        synth_lines.append(f"> ⚠ **VCLT Art. 27**: {synth['vclt_article_27_warning']}")
    await cl.Message(content="\n".join(synth_lines), author="OmniLegal").send()


async def _handle_verify_command() -> None:
    last_answer = cl.user_session.get(_LAST_ANSWER_KEY) or ""
    last_retrieved = cl.user_session.get(_LAST_RETRIEVED_KEY) or []
    if not last_answer:
        await cl.Message(
            content="No previous answer to verify. Ask a question first, then run `/verify`.",
            author="OmniLegal",
        ).send()
        return
    audit = await asyncio.to_thread(verify_answer_citations, last_answer, last_retrieved)
    await cl.Message(
        content=render_verification_markdown(audit),
        author="OmniLegal",
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    raw_query = (message.content or "").strip()
    if not raw_query:
        return

    if getattr(message, "elements", None):
        await cl.Message(
            content=(
                "_File uploads aren't enabled in this build. Drop new .txt or PDF files into "
                "`Law Text Files/` or `data/pdfs/` and call `POST /api/ingestion/run`._"
            ),
            author="OmniLegal",
        ).send()
        return

    cmd, rest = _parse_slash_command(raw_query)
    if cmd in {"conflict", "compare"}:
        await _handle_conflict_command(rest)
        return
    if cmd == "irac":
        await _handle_irac_command(rest)
        return
    if cmd == "verify":
        await _handle_verify_command()
        return

    mode = _selected_mode()
    user_id = str(cl.user_session.get("id") or "anonymous")
    allowed, wait_seconds = check_rate_limit(user_id)
    if not allowed:
        await cl.Message(
            content=f"Rate limit reached. Please try again in about {wait_seconds} seconds.",
            author="OmniLegal",
        ).send()
        return

    # Conflict-Detector persona auto-routes plain questions through the
    # cross-jurisdiction analyzer, even without the slash prefix.
    if mode == AnswerMode.conflict_detector and cmd is None:
        await _handle_conflict_command(raw_query)
        return

    spec = get_mode_spec(mode)
    status = cl.Message(
        content=f"\u2728 Searching the indexed corpus and drafting a **{spec.display_name}** answer…",
        author="OmniLegal",
    )
    await status.send()

    try:
        result = await asyncio.to_thread(_run_graph, raw_query, mode)
    except Exception as exc:  # noqa: BLE001
        log.exception("verified graph failed")
        await status.remove()
        await cl.Message(
            content=(
                "I could not complete the verified legal-source pipeline. "
                "Try a narrower question with a specific country, statute, treaty, or case name."
            ),
            author="OmniLegal",
        ).send()
        asyncio.create_task(
            asyncio.to_thread(
                write_trace,
                "query_failed",
                {"error_type": type(exc).__name__, "mode": mode.value},
            )
        )
        return

    answer = result.get("answer") or "_I could not generate an answer from the indexed sources._"
    retrieved = result.get("retrieved") or []
    await status.remove()
    await cl.Message(content=_format_diagnostics(mode, result), author="OmniLegal").send()
    await cl.Message(content=answer, author="OmniLegal").send()

    sources_text = _build_sources_text(retrieved)
    await cl.Message(
        content=f"#### Sources used\n\n{sources_text}",
        author="OmniLegal",
    ).send()

    # CRAG-style citation audit (free, runs locally)
    if os.environ.get("OMNILEGAL_ENABLE_CITATION_VERIFICATION", "1").lower() in {"1", "true", "yes"}:
        try:
            audit = await asyncio.to_thread(verify_answer_citations, answer, retrieved)
            await cl.Message(
                content=render_verification_markdown(audit),
                author="OmniLegal",
            ).send()
        except Exception as exc:  # noqa: BLE001
            log.warning("citation audit failed: %s", exc)

    # Stash for /verify reruns
    cl.user_session.set(_LAST_ANSWER_KEY, answer)
    cl.user_session.set(_LAST_RETRIEVED_KEY, retrieved)

    asyncio.create_task(
        asyncio.to_thread(
            write_trace,
            "query_completed",
            {
                "query_length": len(raw_query),
                "answer_mode": mode.value,
                "insufficient": result.get("insufficient"),
                "retrieved_count": len(retrieved),
                "provider": result.get("provider"),
                "gemini_fallback_used": result.get("gemini_fallback_used"),
            },
        )
    )
