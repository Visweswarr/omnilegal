"""Small Groq chat client using the OpenAI-compatible REST endpoint."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.config import GROQ_API_KEY, GROQ_MODEL, GROQ_REQUEST_TIMEOUT_SECONDS

_GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


@dataclass(frozen=True)
class GroqChatGeneration:
    text: str
    model: str
    error: str = ""


def compact_groq_error(error: str, *, max_chars: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", str(error or "")).strip()
    if not cleaned:
        return ""
    lower = cleaned.lower()
    if "invalid_api_key" in lower or "invalid api key" in lower or "401" in cleaned:
        return "Groq API key is invalid or expired."
    if "rate_limit" in lower or "rate limit" in lower or "429" in cleaned:
        return "Groq rate limit reached."
    if "insufficient_quota" in lower or "quota" in lower:
        return "Groq quota is exhausted."
    scrubbed = re.sub(r"(gsk_[0-9A-Za-z_\-]{20,}|AIza[0-9A-Za-z_\-]{20,})", "[redacted]", cleaned)
    return scrubbed[:max_chars]


def generate_groq_chat(
    *,
    messages: list[dict[str, str]],
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.1,
    response_format: dict[str, str] | None = None,
    timeout: float | None = None,
) -> GroqChatGeneration:
    if not GROQ_API_KEY:
        return GroqChatGeneration(text="", model=model or GROQ_MODEL, error="GROQ_API_KEY is not set")

    payload: dict[str, Any] = {
        "model": model or GROQ_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if response_format is not None:
        payload["response_format"] = response_format

    try:
        import requests

        response = requests.post(
            _GROQ_CHAT_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout if timeout is not None else GROQ_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code >= 400:
            return GroqChatGeneration(
                text="",
                model=str(payload["model"]),
                error=compact_groq_error(f"{response.status_code}: {response.text[:500]}"),
            )
        data = response.json()
        text = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        text = str(text).strip()
        if not text:
            return GroqChatGeneration(text="", model=str(payload["model"]), error="Groq returned no usable text")
        return GroqChatGeneration(text=text, model=str(data.get("model") or payload["model"]))
    except Exception as exc:
        return GroqChatGeneration(
            text="",
            model=str(payload["model"]),
            error=compact_groq_error(f"{type(exc).__name__}: {exc}"),
        )
