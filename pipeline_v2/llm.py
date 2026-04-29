"""LLM client with provider fallback: Groq -> Gemini -> OpenRouter free."""
from __future__ import annotations

import logging
import time
from typing import Any

from pipeline_v2.settings import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_MODEL_FALLBACK,
    LLM_MAX_TOKENS,
    LLM_TIMEOUT,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
)

log = logging.getLogger("pipeline_v2.llm")


class LLMUnavailable(RuntimeError):
    pass


def _call_groq(system: str, user: str, *, model: str, temperature: float) -> str:
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY, timeout=LLM_TIMEOUT)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=LLM_MAX_TOKENS,
    )
    return (resp.choices[0].message.content or "").strip()


def _call_gemini(system: str, user: str, *, temperature: float) -> str:
    from google import genai
    from google.genai import types as gtypes

    client = genai.Client(api_key=GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[f"{system}\n\n---\n\n{user}"],
        config=gtypes.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=LLM_MAX_TOKENS,
        ),
    )
    return (getattr(resp, "text", None) or "").strip()


def _call_openrouter(system: str, user: str, *, temperature: float) -> str:
    from openai import OpenAI

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        timeout=LLM_TIMEOUT,
    )
    resp = client.chat.completions.create(
        model=OPENROUTER_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=temperature,
        max_tokens=LLM_MAX_TOKENS,
        extra_headers={
            "HTTP-Referer": "https://omnilegal.local",
            "X-Title": "OmniLegal",
        },
    )
    return (resp.choices[0].message.content or "").strip()


def complete(
    system: str,
    user: str,
    *,
    temperature: float = 0.15,
) -> tuple[str, str]:
    """Call the LLM with fallback. Returns (text, provider_used)."""
    errors: list[str] = []

    # 1) Groq llama-3.3-70b
    if GROQ_API_KEY:
        try:
            t0 = time.time()
            out = _call_groq(system, user, model=GROQ_MODEL, temperature=temperature)
            if out:
                log.info("groq/%s succeeded in %.2fs", GROQ_MODEL, time.time() - t0)
                return out, f"groq/{GROQ_MODEL}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"groq/{GROQ_MODEL}: {type(e).__name__}: {e}")
            log.warning("Groq primary failed: %s", e)

        # 1b) Groq smaller fallback
        try:
            out = _call_groq(
                system, user, model=GROQ_MODEL_FALLBACK, temperature=temperature
            )
            if out:
                return out, f"groq/{GROQ_MODEL_FALLBACK}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"groq/{GROQ_MODEL_FALLBACK}: {type(e).__name__}: {e}")

    # 2) Gemini
    if GEMINI_API_KEY:
        try:
            out = _call_gemini(system, user, temperature=temperature)
            if out:
                return out, f"gemini/{GEMINI_MODEL}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"gemini/{GEMINI_MODEL}: {type(e).__name__}: {e}")
            log.warning("Gemini failed: %s", e)

    # 3) OpenRouter free
    if OPENROUTER_API_KEY:
        try:
            out = _call_openrouter(system, user, temperature=temperature)
            if out:
                return out, f"openrouter/{OPENROUTER_MODEL}"
        except Exception as e:  # noqa: BLE001
            errors.append(f"openrouter: {type(e).__name__}: {e}")
            log.warning("OpenRouter failed: %s", e)

    raise LLMUnavailable(
        "All LLM providers failed:\n  - " + "\n  - ".join(errors or ["no keys configured"])
    )
