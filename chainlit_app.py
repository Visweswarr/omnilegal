"""OmniLegal Chainlit frontend.

User-facing runtime has one path:
question -> style -> LangGraph evidence pipeline -> verified answer/fail early.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chainlit as cl  # noqa: E402

from src.config import LEGAL_RESEARCH_DISCLAIMER  # noqa: E402
from src.pipeline.graph import compiled_graph  # noqa: E402
from src.services.production_controls import check_rate_limit, write_trace  # noqa: E402
from src.services.ui_sanitizer import clean_answer_text  # noqa: E402

log = logging.getLogger("omnilegal.chainlit")

_PENDING_QUERY_KEY = "pending_query"
_STYLE_ASKED_KEY = "style_asked"

WELCOME = (
    "**OmniLegal**\n\n"
    "Ask a legal question and choose either **SHORT** for plain-English practical meaning "
    "or **LONG** for structured legal analysis with verified sources and conflict checks.\n\n"
    f"{LEGAL_RESEARCH_DISCLAIMER}"
)


def _style_actions() -> list[cl.Action]:
    return [
        cl.Action(name="set_answer_style", payload={"style": "short"}, label="SHORT"),
        cl.Action(name="set_answer_style", payload={"style": "long"}, label="LONG"),
    ]


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


def _collection_count() -> int:
    try:
        from src.rag.vector_store import get_store

        store = get_store()
        return sum(store.collection_point_count(col) for col in store.available_collections())
    except Exception:
        return 0


def _run_graph(query: str, style: str) -> dict[str, Any]:
    state = compiled_graph.invoke({"raw_input": query, "answer_style": style})
    final = state.get("final") or {}
    answer = final.get("answer") or state.get("verified_draft") or state.get("draft") or ""
    return {
        "answer": clean_answer_text(str(answer)),
        "insufficient": bool(final.get("insufficient_context") or state.get("insufficient_context")),
        "source_plan": state.get("source_plan") or {},
        "availability": state.get("source_availability") or {},
        "authority_gaps": final.get("authority_gaps") or state.get("authority_gaps") or [],
        "provider": state.get("provider") or final.get("used_model") or "n/a",
        "grounded_ratio": state.get("grounded_ratio"),
        "retrieved_count": len(state.get("retrieved") or []),
    }


async def _ask_style(query: str) -> None:
    cl.user_session.set(_PENDING_QUERY_KEY, query)
    await cl.Message(content="Choose the answer style.", actions=_style_actions()).send()


async def _answer(query: str, style: str) -> None:
    user_id = str(cl.user_session.get("id") or "anonymous")
    allowed, wait_seconds = check_rate_limit(user_id)
    if not allowed:
        await cl.Message(
            content=f"Rate limit reached. Please try again in about {wait_seconds} seconds."
        ).send()
        return

    status = cl.Message(content=f"Checking indexed sources and verified citations ({style.upper()})...")
    await status.send()
    try:
        result = await asyncio.to_thread(_run_graph, query, style)
    except Exception as exc:  # noqa: BLE001
        log.exception("verified graph failed")
        await status.remove()
        await cl.Message(
            content=(
                "I could not complete the verified legal-source pipeline. "
                "Please try a narrower question with a specific country, statute, treaty, or case."
            )
        ).send()
        asyncio.create_task(
            asyncio.to_thread(write_trace, "query_failed", {"error_type": type(exc).__name__, "style": style})
        )
        return

    await status.remove()
    answer = result.get("answer") or "I could not generate an answer from verified indexed sources."
    diagnostics = (
        f"**Style:** {style.upper()} · **Retrieved passages:** {result.get('retrieved_count', 0)} · "
        f"**Provider:** `{result.get('provider')}`"
    )
    await cl.Message(content=diagnostics, author="OmniLegal").send()
    await cl.Message(content=answer, author="OmniLegal").send()
    asyncio.create_task(
        asyncio.to_thread(
            write_trace,
            "query_completed",
            {
                "query_length": len(query),
                "answer_style": style,
                "insufficient": result.get("insufficient"),
                "retrieved_count": result.get("retrieved_count"),
                "source_topics": (result.get("source_plan") or {}).get("topics", []),
            },
        )
    )


@cl.on_chat_start
async def on_start() -> None:
    count = _collection_count()
    banner = WELCOME
    if count == 0:
        banner += (
            "\n\n> Corpus is empty. Seed source documents before asking legal questions:\n"
            "> ```bash\n> python scripts/seed_qdrant.py --verify\n> ```"
        )
    else:
        banner += f"\n\n> Indexed source passages available: **{count}**."
    await cl.Message(content=banner).send()


@cl.action_callback("set_answer_style")
async def on_set_answer_style(action: cl.Action) -> None:
    pending = cl.user_session.get(_PENDING_QUERY_KEY)
    if not pending:
        return
    style = _style_only_choice(str((action.payload or {}).get("style", "")))
    if not style:
        return
    cl.user_session.set(_PENDING_QUERY_KEY, None)
    await _answer(str(pending), style)


@cl.on_message
async def on_message(message: cl.Message) -> None:
    query = (message.content or "").strip()
    if not query:
        return

    if getattr(message, "elements", None):
        await cl.Message(
            content="Document uploads are not supported in chat. Add documents through the ingestion pipeline, then run `python scripts/seed_qdrant.py --verify`."
        ).send()
        return

    pending_query = cl.user_session.get(_PENDING_QUERY_KEY)
    style_reply = _style_only_choice(query)
    if style_reply and pending_query:
        cl.user_session.set(_PENDING_QUERY_KEY, None)
        await _answer(str(pending_query), style_reply)
        return

    query, inline_style = _extract_inline_style(query)
    if not query:
        return
    if inline_style:
        await _answer(query, inline_style)
        return

    if not cl.user_session.get(_STYLE_ASKED_KEY):
        cl.user_session.set(_STYLE_ASKED_KEY, True)
        await _ask_style(query)
        return

    await _ask_style(query)
