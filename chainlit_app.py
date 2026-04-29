"""OmniLegal Chainlit frontend — evidence-first pipeline.

Routes every query through the LangGraph ``compiled_graph``:
  classify → extract_entities → source_gate → retrieve
  → analyze_jurisdictions → synthesize → gemini_refine
  → verify_citations → answer

No direct ``search_documents()`` + ``generate()`` calls.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent))

try:
    from engineio.payload import Payload

    Payload.max_decode_packets = int(os.getenv("ENGINEIO_MAX_DECODE_PACKETS", "128"))
except Exception:
    pass

import chainlit as cl

from src.config import LEGAL_RESEARCH_DISCLAIMER
from src.pipeline.graph import compiled_graph
from src.services.production_controls import check_rate_limit, write_trace
from src.services.ui_sanitizer import clean_answer_text

logger = logging.getLogger(__name__)

_PENDING_QUERY_KEY = "pending_query"
_STYLE_PROMPT = "Choose the answer style."

_WELCOME = (
    "**OmniLegal — Evidence-First Legal Research**\n\n"
    "Ask a legal question and choose either **SHORT** for plain-English practical meaning "
    "or **LONG** for structured legal analysis with verified sources.\n\n"
    "Every answer is built from retrieved evidence. If required sources are "
    "not indexed, the system will tell you exactly what is missing.\n\n"
    f"{LEGAL_RESEARCH_DISCLAIMER}"
)


def _style_only_choice(text: str) -> str | None:
    lowered = " ".join((text or "").strip().lower().split())
    if lowered in {"short", "brief", "summary", "plain english", "layman"}:
        return "short"
    if lowered in {"long", "detailed", "detail", "analysis", "legal analysis"}:
        return "long"
    return None


def _extract_inline_style(query: str) -> tuple[str, str | None]:
    stripped = (query or "").strip()
    lowered = stripped.lower()
    prefixes = {
        "short:": "short",
        "short answer:": "short",
        "brief:": "short",
        "long:": "long",
        "long answer:": "long",
        "detailed:": "long",
        "detailed answer:": "long",
    }
    for prefix, style in prefixes.items():
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip(), style
    if lowered.startswith("short answer "):
        return stripped[len("short answer "):].strip(), "short"
    if lowered.startswith("long answer "):
        return stripped[len("long answer "):].strip(), "long"
    return stripped, None


async def _prompt_for_style(query: str) -> None:
    cl.user_session.set(_PENDING_QUERY_KEY, query)
    response = await cl.AskActionMessage(
        content=_STYLE_PROMPT,
        actions=[
            cl.Action(name="set_answer_style", payload={"answer_style": "short"}, label="SHORT"),
            cl.Action(name="set_answer_style", payload={"answer_style": "long"}, label="LONG"),
        ],
        timeout=300,
        raise_on_timeout=False,
    ).send()
    if not response:
        return
    pending_query = cl.user_session.get(_PENDING_QUERY_KEY)
    style = _style_only_choice(str((response.get("payload") or {}).get("answer_style", "")))
    if pending_query and style:
        cl.user_session.set(_PENDING_QUERY_KEY, None)
        await _run_query(str(pending_query), style)


def _extract_answer(result: dict[str, Any]) -> str:
    """Pull the verified answer text from pipeline result."""
    final = result.get("final") or {}
    if isinstance(final, dict):
        answer = final.get("answer", "")
        if answer:
            return str(answer)

    # Fallback: try verified_draft, then draft
    for key in ("verified_draft", "draft"):
        text = result.get(key, "")
        if text and str(text).strip():
            return str(text)

    return ""


def _extract_error(result: dict[str, Any]) -> str | None:
    """Extract the first pipeline error or missing-source message."""
    errors = result.get("pipeline_errors") or []
    if errors:
        return str(errors[0])
    source_avail = result.get("source_availability") or {}
    missing = source_avail.get("missing") or []
    if missing:
        lines = ["Required sources are not indexed:"]
        lines.extend(f"  • {m}" for m in missing)
        return "\n".join(lines)
    return None


async def _run_query(query: str, answer_style: str) -> None:
    style = "short" if answer_style == "short" else "long"

    status = cl.Message(content="Running evidence-first pipeline…")
    await status.send()

    try:
        # Build initial pipeline state
        initial_state = {
            "raw_input": query,
            "answer_style": style,
        }

        # Run the full LangGraph pipeline in a thread
        result = await asyncio.to_thread(compiled_graph.invoke, initial_state)

        # Check for pipeline failures
        error_msg = _extract_error(result)
        if result.get("insufficient_context") and error_msg:
            await status.remove()
            await cl.Message(content=error_msg).send()
            asyncio.create_task(
                asyncio.to_thread(
                    write_trace,
                    "query_insufficient",
                    {
                        "query_length": len(query),
                        "answer_style": style,
                        "missing_sources": (result.get("source_availability") or {}).get("missing", []),
                    },
                )
            )
            return

        # Extract and clean the answer
        answer = _extract_answer(result)
        if not answer.strip():
            await status.remove()
            await cl.Message(
                content=(
                    "The pipeline did not produce a verified answer for this query.\n\n"
                    "Try including a specific country, statute, treaty, or case citation. "
                    "If the corpus has not been ingested yet, run:\n"
                    "```\npython scripts/seed_qdrant.py\n```"
                )
            ).send()
            return

        answer = clean_answer_text(answer)

        # Add fallback note for unsupported jurisdictions
        source_plan = result.get("source_plan") or {}
        fallback_note = source_plan.get("fallback_note", "")
        if fallback_note:
            answer = f"> ⚠️ {fallback_note}\n\n{answer}"

        await status.remove()
        await cl.Message(content=answer).send()

        asyncio.create_task(
            asyncio.to_thread(
                write_trace,
                "query_completed",
                {
                    "query_length": len(query),
                    "answer_style": style,
                    "source_count": len(result.get("retrieved") or []),
                    "grounding_status": result.get("grounding_status", ""),
                    "insufficient_context": result.get("insufficient_context", False),
                },
            )
        )
    except Exception as exc:
        logger.exception("RAG pipeline failed")
        await status.remove()
        await cl.Message(
            content=(
                "The evidence-first pipeline encountered an error. "
                "Please try a narrower question with a country, statute, treaty, or case name.\n\n"
                f"Error: {type(exc).__name__}"
            )
        ).send()
        asyncio.create_task(
            asyncio.to_thread(
                write_trace,
                "query_failed",
                {"query_length": len(query), "answer_style": style, "error_type": type(exc).__name__},
            )
        )


@cl.on_chat_start
async def on_start() -> None:
    await cl.Message(content=_WELCOME).send()


@cl.action_callback("set_answer_style")
async def on_set_answer_style(action: cl.Action) -> None:
    pending_query = cl.user_session.get(_PENDING_QUERY_KEY)
    if not pending_query:
        return
    style = _style_only_choice(str((action.payload or {}).get("answer_style", "")))
    if not style:
        return
    cl.user_session.set(_PENDING_QUERY_KEY, None)
    await _run_query(str(pending_query), style)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    query = (message.content or "").strip()
    if not query:
        return

    if getattr(message, "elements", None):
        await cl.Message(
            content=(
                "Document uploads are not supported in the chat UI. "
                "To add documents to the corpus, run: `python scripts/seed_qdrant.py`"
            )
        ).send()
        return

    pending_query = cl.user_session.get(_PENDING_QUERY_KEY)
    style_reply = _style_only_choice(query)
    if style_reply and pending_query:
        cl.user_session.set(_PENDING_QUERY_KEY, None)
        await _run_query(str(pending_query), style_reply)
        return

    query, inline_style = _extract_inline_style(query)
    if not query:
        return

    user_key = (
        getattr(message, "author", None)
        or cl.user_session.get("id")
        or cl.user_session.get("user")
        or "anonymous"
    )
    allowed, reason = check_rate_limit(str(user_key), max_requests=30, window_seconds=3600)
    if not allowed:
        await cl.Message(content=reason).send()
        return

    if not inline_style:
        await _prompt_for_style(query)
        return

    await _run_query(query, inline_style)
