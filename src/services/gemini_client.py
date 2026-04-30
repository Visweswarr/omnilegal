"""Small Gemini client wrapper with current SDK support and legacy fallback."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

from src.config import GEMINI_API_KEY, GEMINI_FALLBACK_MODELS, GEMINI_REFINER_MODEL

_QUOTA_BACKOFF_SECONDS = 60.0
_QUOTA_BLOCKED_UNTIL: dict[str, float] = {}


@dataclass(frozen=True)
class GeminiGeneration:
    text: str
    model: str
    error: str = ""


def _model_candidates(model: str | None = None, fallback_models: list[str] | None = None) -> list[str]:
    ordered = [model or GEMINI_REFINER_MODEL, *(fallback_models if fallback_models is not None else GEMINI_FALLBACK_MODELS)]
    result: list[str] = []
    seen: set[str] = set()
    for item in ordered:
        clean = str(item or "").strip()
        if clean and clean not in seen:
            seen.add(clean)
            result.append(clean)
    return result


def _response_text(response: Any) -> str:
    text = getattr(response, "text", None)
    if text:
        return str(text).strip()
    try:
        candidates = getattr(response, "candidates", []) or []
        parts = candidates[0].content.parts if candidates else []
        return "".join(str(getattr(part, "text", "") or "") for part in parts).strip()
    except Exception:
        return ""


def _is_quota_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "resource_exhausted" in message or "quota exceeded" in message or "429" in message


def _retry_delay_seconds(exc: Exception) -> float:
    message = str(exc)
    for pattern in (r"retryDelay['\"]?\s*:\s*['\"]?(\d+)s", r"retry in (\d+(?:\.\d+)?)s"):
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            try:
                return max(1.0, float(match.group(1)))
            except ValueError:
                break
    return _QUOTA_BACKOFF_SECONDS


def _compact_exception(exc: Exception) -> str:
    if _is_quota_error(exc):
        return f"Gemini free-tier quota or rate limit exhausted; retry after about {int(_retry_delay_seconds(exc))}s"
    message = re.sub(r"\s+", " ", str(exc)).strip()
    compact = compact_gemini_error(message)
    return compact or type(exc).__name__


def compact_gemini_error(error: str, *, max_chars: int = 280) -> str:
    """Return a short, UI-safe Gemini error string."""
    cleaned = re.sub(r"\s+", " ", str(error or "")).strip()
    if not cleaned:
        return ""
    lower = cleaned.lower()
    if (
        "api key expired" in lower
        or "api_key_invalid" in lower
        or "api key not valid" in lower
        or "invalid api key" in lower
        or ("invalid_argument" in lower and "api key" in lower)
    ):
        return "Gemini API key is invalid or expired."
    if "permission_denied" in lower or ("403" in cleaned and "api" in lower):
        return "Gemini API key is not authorized for this request."
    if "quota" in lower or "resource_exhausted" in lower or "429" in cleaned:
        models = re.findall(r"(gemini-[\w.\-]+):", cleaned)
        model_note = f" ({', '.join(dict.fromkeys(models))})" if models else ""
        return f"Gemini free-tier quota or rate limit exhausted{model_note}."
    scrubbed = re.sub(r"(AIza[0-9A-Za-z_\-]{20,}|gsk_[0-9A-Za-z_\-]{20,})", "[redacted]", cleaned)
    return scrubbed[:max_chars]


def _generate_with_google_genai(
    *,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        ),
    )
    return _response_text(response)


def _generate_with_legacy_sdk(
    *,
    model: str,
    system: str,
    prompt: str,
    temperature: float,
    max_output_tokens: int,
) -> str:
    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    legacy_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system,
    )
    response = legacy_model.generate_content(
        prompt,
        generation_config={
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        },
    )
    return _response_text(response)


def generate_gemini_content(
    *,
    system: str,
    prompt: str,
    model: str | None = None,
    fallback_models: list[str] | None = None,
    temperature: float = 0.15,
    max_output_tokens: int = 4096,
) -> GeminiGeneration:
    """Generate text using Gemini.

    The official Gemini migration docs now recommend the unified
    ``google-genai`` SDK. The old ``google-generativeai`` path is retained as a
    fallback for older local environments.
    """
    if not GEMINI_API_KEY:
        return GeminiGeneration(text="", model=model or GEMINI_REFINER_MODEL, error="GEMINI_API_KEY is not set")

    errors: list[str] = []
    for candidate in _model_candidates(model, fallback_models):
        blocked_until = _QUOTA_BLOCKED_UNTIL.get(candidate, 0.0)
        now = time.monotonic()
        if blocked_until > now:
            wait = max(1, int(blocked_until - now))
            errors.append(f"{candidate}: skipped after recent quota/rate limit; retry in about {wait}s")
            continue
        should_try_legacy = False
        try:
            text = _generate_with_google_genai(
                model=candidate,
                system=system,
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            if text:
                return GeminiGeneration(text=text, model=candidate)
            errors.append(f"{candidate}: empty response from google-genai")
            continue
        except ImportError as exc:
            errors.append(f"{candidate}: google-genai unavailable ({exc})")
            should_try_legacy = True
        except Exception as exc:
            if _is_quota_error(exc):
                delay = _retry_delay_seconds(exc)
                _QUOTA_BLOCKED_UNTIL[candidate] = time.monotonic() + delay
                errors.append(f"{candidate}: {_compact_exception(exc)}")
            else:
                errors.append(f"{candidate}: google-genai failed ({type(exc).__name__}: {_compact_exception(exc)})")
            continue

        if not should_try_legacy:
            continue
        try:
            text = _generate_with_legacy_sdk(
                model=candidate,
                system=system,
                prompt=prompt,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )
            if text:
                return GeminiGeneration(text=text, model=candidate)
            errors.append(f"{candidate}: empty response from legacy SDK")
        except ModuleNotFoundError as exc:
            errors.append(f"{candidate}: legacy SDK unavailable ({exc})")
        except Exception as exc:
            if _is_quota_error(exc):
                delay = _retry_delay_seconds(exc)
                _QUOTA_BLOCKED_UNTIL[candidate] = time.monotonic() + delay
                errors.append(f"{candidate}: {_compact_exception(exc)}")
            else:
                errors.append(f"{candidate}: legacy SDK failed ({type(exc).__name__}: {_compact_exception(exc)})")

    return GeminiGeneration(text="", model=model or GEMINI_REFINER_MODEL, error="; ".join(errors))
