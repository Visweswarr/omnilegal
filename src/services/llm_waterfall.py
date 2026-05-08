"""Shared multi-provider JSON-mode waterfall.

Mirrors the 5-stage pattern in advocacy_service so every Tier-2 pillar
(diff, redteam, doctrine, reading, etc.) can transparently use:

    1. Emergent Anthropic (claude-sonnet-4-5)
    2. Emergent Google    (gemini-2.5-flash)
    3. Direct Gemini      (gemini-2.5-flash)
    4. Direct Gemini Lite (gemini-2.5-flash-lite)
    5. Groq Llama         (llama-3.3-70b-versatile)

The first provider that returns valid JSON satisfying ``validate(parsed)``
wins. Caller gets back ``(parsed_dict, used_model, attempts_log)``.

Designed so:
  • Adding more providers is a one-liner in DEFAULT_PLAN.
  • Validators are caller-supplied — each pillar enforces its own schema.
  • Failures are non-fatal; on full exhaustion we return (None, "none", attempts).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger("omnilegal.llm_waterfall")


@dataclass
class WaterfallAttempt:
    provider: str
    model: str
    ok: bool
    error: str = ""


DEFAULT_PLAN: list[tuple[str, str]] = [
    ("emergent_anthropic", "claude-sonnet-4-5-20250929"),
    ("emergent_google",    "gemini-2.5-flash"),
    ("gemini_direct",      "gemini-2.5-flash"),
    ("gemini_direct_lite", "gemini-2.5-flash-lite"),
    ("groq_llama",         "llama-3.3-70b-versatile"),
]


def parse_json_loose(text: str) -> dict[str, Any] | None:
    """Parse JSON, tolerating ```json fences and surrounding chatter."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _try_emergent(provider_arg: str, model: str, system: str, prompt: str,
                  *, timeout: float) -> tuple[str, str | None]:
    from src.services.emergent_llm import generate_text
    res = generate_text(
        system=system, prompt=prompt,
        provider=provider_arg, model=model, timeout_seconds=timeout,
    )
    return res.text or "", res.error or None


def _try_gemini_direct(model: str, system: str, prompt: str,
                       *, max_tokens: int, temperature: float) -> tuple[str, str | None]:
    from src.services.gemini_client import generate_gemini_content
    res = generate_gemini_content(
        system=system, prompt=prompt,
        model=model, temperature=temperature, max_output_tokens=max_tokens,
    )
    return res.text or "", res.error or None


def _try_groq(model: str, system: str, prompt: str,
              *, max_tokens: int, temperature: float) -> tuple[str, str | None]:
    from src.services.groq_client import generate_groq_chat
    res = generate_groq_chat(
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        model=model, max_tokens=max_tokens, temperature=temperature,
        response_format={"type": "json_object"},
    )
    return res.text or "", res.error or None


def generate_json(
    *,
    system: str,
    prompt: str,
    validate: Callable[[dict[str, Any]], bool] = lambda d: isinstance(d, dict),
    plan: list[tuple[str, str]] | None = None,
    max_tokens: int = 2400,
    temperature: float = 0.2,
    emergent_timeout: float = 70.0,
) -> tuple[dict[str, Any] | None, str, list[WaterfallAttempt]]:
    """Run the provider waterfall until ``validate`` accepts the parsed JSON.

    Returns:
        (parsed_dict_or_None, used_model_label, attempts_log)
    """
    plan = plan or DEFAULT_PLAN
    attempts: list[WaterfallAttempt] = []

    for provider_tag, model in plan:
        text = ""
        err: str | None = None
        try:
            if provider_tag == "emergent_anthropic":
                text, err = _try_emergent("anthropic", model, system, prompt,
                                          timeout=emergent_timeout)
            elif provider_tag == "emergent_google":
                text, err = _try_emergent("google", model, system, prompt,
                                          timeout=emergent_timeout)
            elif provider_tag in ("gemini_direct", "gemini_direct_lite"):
                text, err = _try_gemini_direct(model, system, prompt,
                                               max_tokens=max_tokens, temperature=temperature)
            elif provider_tag == "groq_llama":
                text, err = _try_groq(model, system, prompt,
                                      max_tokens=max_tokens, temperature=temperature)
            else:
                err = f"unknown provider tag: {provider_tag}"
        except Exception as exc:  # noqa: BLE001
            err = f"{type(exc).__name__}: {exc}"

        if err and not text:
            attempts.append(WaterfallAttempt(provider_tag, model, False, err[:240]))
            continue

        parsed = parse_json_loose(text)
        if parsed is None:
            attempts.append(WaterfallAttempt(provider_tag, model, False, "json parse failed"))
            continue

        try:
            ok = validate(parsed)
        except Exception as exc:  # noqa: BLE001
            ok = False
            err = f"validator threw: {type(exc).__name__}: {exc}"

        if ok:
            attempts.append(WaterfallAttempt(provider_tag, model, True))
            return parsed, f"{provider_tag}:{model}", attempts

        attempts.append(WaterfallAttempt(provider_tag, model, False, err or "schema validation failed"))

    return None, "none", attempts


def attempts_as_dicts(attempts: list[WaterfallAttempt]) -> list[dict[str, Any]]:
    return [
        {"provider": a.provider, "model": a.model, "ok": a.ok, "error": a.error}
        for a in attempts
    ]
