"""OmniLegal — premium Chainlit research console.

Persona-driven legal RAG (Tourist / Law Student / Researcher / Layman).
Question → persona → LangGraph evidence pipeline → grounded answer with
[S#] citations and an expandable Sources panel. Gemini is the always-on
fallback when retrieval is sparse.
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
from src.pipeline.graph import compiled_graph  # noqa: E402
from src.schemas import AnswerMode  # noqa: E402
from src.services.answer_modes import all_mode_specs, get_mode_spec, parse_mode  # noqa: E402
from src.services.production_controls import check_rate_limit, write_trace  # noqa: E402
from src.services.ui_sanitizer import clean_answer_text  # noqa: E402

log = logging.getLogger("omnilegal.chainlit")

_ACTIVE_MODE_KEY = "active_mode"
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
    """Rewrite plain numeric citations (e.g. [3], [2,4]) into [S3], [S2, S4]
    so the body matches the Sources panel labels."""
    import re

    def fix_group(match: "re.Match[str]") -> str:
        inside = match.group(1)
        # Skip if already prefixed with S
        if "S" in inside.upper():
            return match.group(0)
        labels = [piece.strip() for piece in inside.split(",") if piece.strip().isdigit()]
        if not labels:
            return match.group(0)
        return "[" + ", ".join(f"S{label}" for label in labels) + "]"

    return re.sub(r"\[([0-9]+(?:\s*,\s*[0-9]+)*)\]", fix_group, text)


def _run_graph(query: str, mode: AnswerMode) -> dict[str, Any]:
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


# ── Chainlit entrypoints ───────────────────────────────────────────────────


@cl.on_chat_start
async def on_start() -> None:
    mode = _selected_mode()
    spec = get_mode_spec(mode)
    count = _collection_count()
    corpus_line = (
        f"\u25C6 Indexed source passages: **{count:,}**." if count else
        "\u25C6 Corpus is empty. Run `python scripts/bootstrap_corpus.py` to ingest the bundled PDFs and case-law catalog."
    )
    welcome = (
        f"### OmniLegal \u2014 Legal Research Console\n\n"
        f"You're talking to the **{spec.display_name}** persona. {spec.tagline}.\n\n"
        f"_Voice_: {spec.voice}\n\n"
        f"{corpus_line}\n\n"
        "Ask any international, comparative, or jurisdiction-specific question. The console will:\n"
        "1. Search the indexed corpus (Malcolm Shaw, UN Charter, ICCPR, Indian Constitution, case law catalog).\n"
        "2. Synthesize an answer in the chosen persona's voice with `[S#]` citations.\n"
        "3. Fall back to Gemini knowledge if retrieval is sparse \u2014 always tagged transparently.\n\n"
        "_Switch persona_ at any time via the panel on the left.\n\n"
        f"{LEGAL_RESEARCH_DISCLAIMER}"
    )
    await cl.Message(content=welcome, author="OmniLegal").send()


@cl.on_settings_update
async def on_settings_update(settings: dict[str, Any]) -> None:  # pragma: no cover - UI hook
    profile = settings.get("chat_profile") if isinstance(settings, dict) else None
    if profile:
        cl.user_session.set(_ACTIVE_MODE_KEY, parse_mode(profile))


@cl.on_message
async def on_message(message: cl.Message) -> None:
    query = (message.content or "").strip()
    if not query:
        return

    if getattr(message, "elements", None):
        await cl.Message(
            content=(
                "_File uploads aren't enabled in this build. Drop PDFs into `data/pdfs/` and run "
                "`python scripts/bootstrap_corpus.py` to index them._"
            ),
            author="OmniLegal",
        ).send()
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

    spec = get_mode_spec(mode)
    status = cl.Message(
        content=(
            f"\u2728 Searching the indexed corpus and drafting a **{spec.display_name}** answer\u2026"
        ),
        author="OmniLegal",
    )
    await status.send()

    try:
        result = await asyncio.to_thread(_run_graph, query, mode)
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
    await status.remove()
    await cl.Message(content=_format_diagnostics(mode, result), author="OmniLegal").send()
    await cl.Message(content=answer, author="OmniLegal").send()

    sources_text = _build_sources_text(result.get("retrieved") or [])
    await cl.Message(
        content=f"#### Sources used\n\n{sources_text}",
        author="OmniLegal",
    ).send()

    asyncio.create_task(
        asyncio.to_thread(
            write_trace,
            "query_completed",
            {
                "query_length": len(query),
                "answer_mode": mode.value,
                "insufficient": result.get("insufficient"),
                "retrieved_count": len(result.get("retrieved") or []),
                "provider": result.get("provider"),
                "gemini_fallback_used": result.get("gemini_fallback_used"),
            },
        )
    )
