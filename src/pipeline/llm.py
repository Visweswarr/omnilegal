"""Runtime LLM client for verified RAG synthesis.

Provider chain (first that succeeds wins):
  1. Emergent universal key (free for the user) → Claude Sonnet 4.5 by default.
  2. Groq (`GROQ_API_KEY`) → llama-3.3-70b-versatile (fast, free tier).
  3. Local Ollama (`OMNILEGAL_OLLAMA_BASE_URL`) → qwen2.5:7b-instruct.

If all three providers fail, raise ``LLMUnavailable`` so the verifier can fall
back to the Gemini-knowledge fallback or the deterministic extractive answer.
"""
from __future__ import annotations

import asyncio
import logging
import time

import requests

from src.config import (
    EMERGENT_LLM_KEY,
    EMERGENT_LLM_MODEL,
    EMERGENT_LLM_PROVIDER,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_REQUEST_TIMEOUT_SECONDS,
    OMNILEGAL_OLLAMA_BASE_URL,
    OMNILEGAL_OLLAMA_MODEL,
)

log = logging.getLogger("src.pipeline.llm")

_GROQ_MODEL_FALLBACK = "llama-3.1-8b-instant"
_LLM_MAX_TOKENS = 1800
_LLM_TIMEOUT = max(30, int(GROQ_REQUEST_TIMEOUT_SECONDS))


class LLMUnavailable(RuntimeError):
    pass


def _compact_error(error: Exception) -> str:
    return " ".join(f"{type(error).__name__}: {error}".split())[:260]


# ── Emergent universal LLM key (Claude Sonnet 4.5 default) ───────────────


def _call_emergent(system: str, user: str, *, temperature: float) -> str:
    """Run a single-turn completion through emergentintegrations.LlmChat."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage  # noqa: WPS433

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"omnilegal-{int(time.time() * 1000)}",
        system_message=system,
    ).with_model(EMERGENT_LLM_PROVIDER, EMERGENT_LLM_MODEL)
    if hasattr(chat, "with_max_tokens"):
        try:
            chat = chat.with_max_tokens(_LLM_MAX_TOKENS)  # type: ignore[attr-defined]
        except Exception:
            pass
    if hasattr(chat, "with_temperature"):
        try:
            chat = chat.with_temperature(temperature)  # type: ignore[attr-defined]
        except Exception:
            pass

    message = UserMessage(text=user)

    async def _runner() -> str:
        return await chat.send_message(message)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already inside an event loop (e.g. Chainlit). Run in a thread-isolated loop.
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _runner()).result(timeout=_LLM_TIMEOUT)
    except RuntimeError:
        pass
    return asyncio.run(_runner())


def _call_groq(system: str, user: str, *, model: str, temperature: float) -> str:
    from groq import Groq  # noqa: WPS433

    client = Groq(api_key=GROQ_API_KEY, timeout=_LLM_TIMEOUT)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=_LLM_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_ollama(system: str, user: str, *, temperature: float) -> str:
    base_url = OMNILEGAL_OLLAMA_BASE_URL.rstrip("/")
    payload = {
        "model": OMNILEGAL_OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": _LLM_MAX_TOKENS,
        },
    }
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=_LLM_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    return ((data.get("message") or {}).get("content") or "").strip()


def complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.12,
) -> tuple[str, str]:
    """Try Emergent → Groq → Ollama. Returns (text, provider_used)."""
    errors: list[str] = []

    if EMERGENT_LLM_KEY:
        try:
            t0 = time.time()
            out = _call_emergent(system, user, temperature=temperature)
            if out and out.strip():
                log.info(
                    "emergent/%s/%s succeeded in %.2fs",
                    EMERGENT_LLM_PROVIDER,
                    EMERGENT_LLM_MODEL,
                    time.time() - t0,
                )
                return out.strip(), f"emergent/{EMERGENT_LLM_PROVIDER}/{EMERGENT_LLM_MODEL}"
        except Exception as exc:  # noqa: BLE001
            detail = _compact_error(exc)
            errors.append(f"emergent/{EMERGENT_LLM_MODEL}: {detail}")
            log.warning("Emergent provider failed: %s", detail)

    if GROQ_API_KEY:
        for model in (GROQ_MODEL, _GROQ_MODEL_FALLBACK):
            try:
                t0 = time.time()
                out = _call_groq(system, user, model=model, temperature=temperature)
                if out:
                    log.info("groq/%s succeeded in %.2fs", model, time.time() - t0)
                    return out, f"groq/{model}"
            except Exception as exc:  # noqa: BLE001
                detail = _compact_error(exc)
                errors.append(f"groq/{model}: {detail}")
                log.warning("Groq %s failed: %s", model, detail)

    try:
        t0 = time.time()
        out = _call_ollama(system, user, temperature=temperature)
        if out:
            log.info("ollama/%s succeeded in %.2fs", OMNILEGAL_OLLAMA_MODEL, time.time() - t0)
            return out, f"ollama/{OMNILEGAL_OLLAMA_MODEL}"
    except Exception as exc:  # noqa: BLE001
        detail = _compact_error(exc)
        errors.append(f"ollama/{OMNILEGAL_OLLAMA_MODEL}: {detail}")
        log.warning("Ollama failed: %s", detail)

    raise LLMUnavailable(
        "All runtime LLM providers failed:\n  - "
        + "\n  - ".join(errors or ["no runtime provider configured"])
    )
