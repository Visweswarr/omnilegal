"""OmniLegal Chainlit UI — verification-first, 3 modes.

  • Legal Research — deep research with citations and interpretations.
  • Conflict Analyzer — international vs domestic law supremacy.
  • Tourist Safety — practical traveller rights & duties.

Every answer is produced by `pipeline_v2.run_query`, which:
  1. Classifies mode + jurisdictions,
  2. Retrieves from the indexed corpus with hard jurisdiction filter,
  3. Generates a grounded answer (Groq → Gemini → OpenRouter fallback),
  4. Verifies every citation maps to an actual retrieved source,
  5. Flags any unsupported claims with ⚠ so the user sees what is not grounded.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Make sure /app is on sys.path so pipeline_v2 resolves
sys.path.insert(0, str(Path(__file__).resolve().parent))

import chainlit as cl  # noqa: E402

from pipeline_v2 import run_query  # noqa: E402
from pipeline_v2.vector_store import collection_count  # noqa: E402

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("omnilegal.chainlit")

_SK_MODE = "mode"
_SK_STYLE = "style"
_SK_PENDING = "pending_query"


# ── Welcome ────────────────────────────────────────────────────────────────

WELCOME = """# ⚖️ OmniLegal — Verification-First Legal Research

Ask a legal question. Every answer is grounded in an indexed source — if the corpus cannot support a claim, the system says so instead of guessing.

**Modes**
- 🔎 **Legal Research** — case law, statutes, interpretations, attack/defence angles
- ⚖️ **Conflict Analyzer** — international vs domestic law, which prevails and why
- 🧳 **Tourist Safety** — your rights, your duties, what to do if something goes wrong

Use the chips below to pick a mode, then type your question."""


def _mode_actions() -> list[cl.Action]:
    return [
        cl.Action(
            name="set_mode",
            payload={"mode": "research"},
            label="🔎 Legal Research",
            description="Deep legal research with citations",
        ),
        cl.Action(
            name="set_mode",
            payload={"mode": "conflict"},
            label="⚖️ Conflict Analyzer",
            description="International vs domestic law supremacy",
        ),
        cl.Action(
            name="set_mode",
            payload={"mode": "tourist"},
            label="🧳 Tourist Safety",
            description="Travel safety law & traveller rights",
        ),
    ]


def _style_actions() -> list[cl.Action]:
    return [
        cl.Action(
            name="set_style",
            payload={"style": "short"},
            label="⚡ SHORT",
            description="Concise plain-English answer",
        ),
        cl.Action(
            name="set_style",
            payload={"style": "long"},
            label="📚 LONG",
            description="Full structured analysis",
        ),
    ]


@cl.on_chat_start
async def on_start() -> None:
    count = collection_count()
    cl.user_session.set(_SK_MODE, "research")
    cl.user_session.set(_SK_STYLE, "long")

    banner = WELCOME
    if count == 0:
        banner += (
            "\n\n> ⚠️ **Corpus is empty.** Seed it before asking a question:\n"
            "> ```bash\n> python -m pipeline_v2.ingest_seed\n> ```"
        )
    else:
        banner += f"\n\n> 📚 Corpus ready — **{count}** indexed passages."

    await cl.Message(content=banner).send()
    await cl.Message(
        content="**Pick a mode to start** (you can change it any time):",
        actions=_mode_actions(),
    ).send()


@cl.action_callback("set_mode")
async def on_set_mode(action: cl.Action) -> None:
    mode = (action.payload or {}).get("mode", "research")
    cl.user_session.set(_SK_MODE, mode)
    label = {
        "research": "🔎 Legal Research",
        "conflict": "⚖️ Conflict Analyzer",
        "tourist": "🧳 Tourist Safety",
    }.get(mode, mode)
    await cl.Message(content=f"Mode set to **{label}**. Ask your question below.").send()


@cl.action_callback("set_style")
async def on_set_style(action: cl.Action) -> None:
    style = (action.payload or {}).get("style", "long")
    cl.user_session.set(_SK_STYLE, style)
    pending = cl.user_session.get(_SK_PENDING)
    cl.user_session.set(_SK_PENDING, None)
    if pending:
        await _answer(str(pending), style)


async def _ask_style(query: str) -> None:
    cl.user_session.set(_SK_PENDING, query)
    await cl.Message(
        content="**Answer length?**", actions=_style_actions()
    ).send()


async def _answer(query: str, style: str) -> None:
    mode = cl.user_session.get(_SK_MODE) or "research"
    status = cl.Message(content=f"⏳ Running verification-first pipeline ({mode}, {style})…")
    await status.send()

    try:
        result = await asyncio.to_thread(run_query, query, mode, style)
    except Exception as e:  # noqa: BLE001
        log.exception("pipeline failed")
        await status.remove()
        await cl.Message(
            content=f"❌ Pipeline error: `{type(e).__name__}: {e}`"
        ).send()
        return

    await status.remove()

    # Header line with stats
    provider = result.get("provider") or "n/a"
    elapsed = result.get("elapsed_ms") or 0
    juris = ", ".join(result.get("jurisdictions") or []) or "unspecified"
    header = (
        f"**Mode:** {result.get('mode')} · **Jurisdictions detected:** {juris} · "
        f"**Provider:** `{provider}` · **Time:** {elapsed} ms"
    )
    await cl.Message(content=header, author="OmniLegal").send()
    await cl.Message(content=result["answer"], author="OmniLegal").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    query = (message.content or "").strip()
    if not query:
        return

    # Inline mode/style prefixes: "research:" / "tourist:" / "conflict:"
    prefixes = {
        "research:": "research",
        "conflict:": "conflict",
        "tourist:": "tourist",
    }
    for prefix, mode in prefixes.items():
        if query.lower().startswith(prefix):
            cl.user_session.set(_SK_MODE, mode)
            query = query[len(prefix):].strip()
            break

    if not query:
        await cl.Message(content="Please include your question after the mode prefix.").send()
        return

    style = cl.user_session.get(_SK_STYLE) or "long"
    # First question of the session → ask style once
    if not cl.user_session.get("style_asked"):
        cl.user_session.set("style_asked", True)
        await _ask_style(query)
        return

    await _answer(query, style)
