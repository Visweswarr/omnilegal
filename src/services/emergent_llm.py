"""Lightweight Emergent universal-LLM client wrapper.

We use this primarily for the conflict detector, multi-jurisdiction IRAC
synthesis, and citation verification — places where we want a powerful model
(Claude Sonnet 4.5 by default) without rebuilding a Groq/Anthropic SDK
ladder. The Emergent LLM key works across providers; if it fails (quota,
network), callers fall back to ``generate_gemini_content``.

This client is sync-friendly: ``generate_text`` runs the underlying async
``LlmChat`` call inside ``asyncio.run`` and serializes per session_id so it
plays nicely with our LangGraph nodes.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from dataclasses import dataclass

from src.config import EMERGENT_LLM_KEY, EMERGENT_LLM_MODEL, EMERGENT_LLM_PROVIDER

log = logging.getLogger("omnilegal.emergent_llm")

_LOCK = threading.Lock()


@dataclass(frozen=True)
class EmergentGeneration:
    text: str
    model: str
    provider: str
    elapsed_seconds: float
    error: str = ""


def _have_key() -> bool:
    return bool(EMERGENT_LLM_KEY)


async def _async_call(
    *,
    system: str,
    prompt: str,
    provider: str,
    model: str,
    session_id: str,
) -> str:
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # type: ignore[import-not-found]

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=system,
    ).with_model(provider, model)
    response = await chat.send_message(UserMessage(text=prompt))
    return str(response or "").strip()


def _groq_last_resort(
    *,
    system: str,
    prompt: str,
    timeout_seconds: float,
    primary_provider: str,
    primary_model: str,
    elapsed_seconds: float,
    primary_error: str,
) -> "EmergentGeneration":
    """Final Groq fallback used when the primary path returns empty text."""
    try:
        from src.services.groq_client import generate_groq_chat

        groq = generate_groq_chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=4096,
            temperature=0.15,
            timeout=timeout_seconds,
        )
        if groq.text:
            return EmergentGeneration(
                text=groq.text, model=groq.model, provider="groq",
                elapsed_seconds=elapsed_seconds, error=primary_error,
            )
        combined = "; ".join(e for e in [primary_error, groq.error] if e)
    except Exception as exc:
        combined = f"{primary_error}; groq_fallback raised: {type(exc).__name__}: {exc}"
    return EmergentGeneration(
        text="", model=primary_model, provider=primary_provider,
        elapsed_seconds=elapsed_seconds, error=combined or primary_error,
    )


def generate_text(
    *,
    system: str,
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    timeout_seconds: float = 30.0,
) -> EmergentGeneration:
    """Generate text via Emergent's universal LLM gateway.

    Safe to call from sync code or from inside an existing asyncio event
    loop — we always run the async LlmChat call inside a fresh thread so we
    never touch the caller's event loop.

    On any failure (no key, transport error, timeout) we automatically try
    Groq as a last-resort fallback before returning an empty result.
    """
    target_provider = (provider or EMERGENT_LLM_PROVIDER or "anthropic").strip().lower()
    target_model = (model or EMERGENT_LLM_MODEL or "claude-sonnet-4-5-20250929").strip()
    sid = session_id or f"omnilegal-{uuid.uuid4().hex[:8]}"

    if not _have_key():
        return _groq_last_resort(
            system=system, prompt=prompt, timeout_seconds=timeout_seconds,
            primary_provider=target_provider, primary_model=target_model,
            elapsed_seconds=0.0, primary_error="EMERGENT_LLM_KEY is not set",
        )

    started = time.time()

    def _runner() -> str:
        # Each thread gets its own event loop so we never collide with
        # the caller's loop (FastAPI / Chainlit run inside one already).
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(
                asyncio.wait_for(
                    _async_call(
                        system=system,
                        prompt=prompt,
                        provider=target_provider,
                        model=target_model,
                        session_id=sid,
                    ),
                    timeout=timeout_seconds,
                )
            )
        finally:
            try:
                loop.close()
            except Exception:
                pass

    import concurrent.futures

    primary_error = ""
    text = ""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_runner)
            text = future.result(timeout=timeout_seconds + 5.0)
    except concurrent.futures.TimeoutError:
        primary_error = f"Emergent LLM timed out after {timeout_seconds}s"
    except asyncio.TimeoutError:
        primary_error = f"Emergent LLM async timed out after {timeout_seconds}s"
    except Exception as exc:  # noqa: BLE001
        log.warning("Emergent LLM call failed: %s: %s", type(exc).__name__, exc)
        primary_error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.time() - started, 2)
    if text:
        return EmergentGeneration(
            text=text, model=target_model, provider=target_provider,
            elapsed_seconds=elapsed,
        )
    return _groq_last_resort(
        system=system, prompt=prompt, timeout_seconds=timeout_seconds,
        primary_provider=target_provider, primary_model=target_model,
        elapsed_seconds=elapsed, primary_error=primary_error,
    )


def generate_with_fallback(
    *,
    system: str,
    prompt: str,
    provider: str | None = None,
    model: str | None = None,
    session_id: str | None = None,
    timeout_seconds: float = 30.0,
    gemini_fallback: bool = True,
) -> EmergentGeneration:
    """Try Emergent first; on empty/error, optionally fall back to Gemini."""
    primary = generate_text(
        system=system,
        prompt=prompt,
        provider=provider,
        model=model,
        session_id=session_id,
        timeout_seconds=timeout_seconds,
    )
    if primary.text or not gemini_fallback:
        return primary

    gem_error = ""
    gem_model = ""
    try:
        from src.services.gemini_client import generate_gemini_content

        gem = generate_gemini_content(
            system=system,
            prompt=prompt,
            temperature=0.15,
            max_output_tokens=4096,
        )
        gem_model = gem.model
        gem_error = gem.error
        if gem.text:
            return EmergentGeneration(
                text=gem.text,
                model=gem.model,
                provider="gemini",
                elapsed_seconds=primary.elapsed_seconds,
                error=primary.error,
            )
    except Exception as exc:  # noqa: BLE001
        gem_error = f"gemini_fallback raised: {type(exc).__name__}: {exc}"

    groq_error = ""
    try:
        from src.services.groq_client import generate_groq_chat

        for attempt in range(2):
            groq = generate_groq_chat(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=4096,
                temperature=0.15,
                timeout=timeout_seconds,
            )
            if groq.text:
                return EmergentGeneration(
                    text=groq.text,
                    model=groq.model,
                    provider="groq",
                    elapsed_seconds=primary.elapsed_seconds,
                    error=primary.error or gem_error,
                )
            groq_error = groq.error or "groq returned empty text"
            if attempt == 0 and "rate limit" in groq_error.lower():
                time.sleep(2.0)
                continue
            break
    except Exception as exc:  # noqa: BLE001
        groq_error = f"groq_fallback raised: {type(exc).__name__}: {exc}"

    combined = "; ".join(
        e for e in [primary.error, gem_error, groq_error] if e
    ) or "all providers returned empty text"
    return EmergentGeneration(
        text="",
        model=gem_model or primary.model,
        provider="groq",
        elapsed_seconds=primary.elapsed_seconds,
        error=combined,
    )
