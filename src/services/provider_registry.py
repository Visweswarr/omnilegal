"""Unified LLM provider registry for the OmniLegal multi-model council.

Every cloud and local LLM is abstracted behind a common ``ProviderMeta``
interface.  The ``ProviderRegistry`` singleton discovers available
providers at startup and routes ``generate()``, ``critique()``, and
``judge()`` calls to the best available backend.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

import requests as http_requests

from src.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_REFINER_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_REQUEST_TIMEOUT_SECONDS,
    HF_INFERENCE_BASE_URL,
    HF_INFERENCE_MODEL,
    HF_TOKEN,
    OMNILEGAL_ENABLE_HF_PROVIDER,
    OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
    OMNILEGAL_OLLAMA_BASE_URL,
    OMNILEGAL_OLLAMA_MODEL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    OPENAI_COMPAT_MAX_MODELS,
    OPENAI_MODEL,
    OPENAI_MODEL_CANDIDATES,
    OPENROUTER_FREE_MODEL_CANDIDATES,
    OPENROUTER_PREFER_FREE_MODELS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

RoleKind = Literal["drafter", "critic", "judge"]


@dataclass
class ProviderMeta:
    """One registered LLM provider."""

    name: str
    model_id: str = ""
    timeout: float = 30.0
    cost_tier: Literal["free", "free_tier", "paid"] = "free_tier"
    privacy_tier: Literal["local", "zero_retention_api", "external_api"] = "external_api"
    quality_score: int = 50
    roles: tuple[RoleKind, ...] = ("drafter", "critic", "judge")
    is_local: bool = False
    supports_json: bool = False
    supports_streaming: bool = False
    _generate_fn: Callable[..., str] | None = field(default=None, repr=False)
    _available: bool = True

    # ── public interface ──────────────────────────────────────────────

    def generate(self, *, system: str, prompt: str, **kwargs: Any) -> str:
        """Call the LLM for general-purpose generation (drafting)."""
        if self._generate_fn is None:
            raise RuntimeError(f"Provider {self.name} has no generate function")
        return self._generate_fn(system=system, prompt=prompt, **kwargs)

    def critique(self, *, draft: str, context: str, **kwargs: Any) -> str:
        """Produce a structured critique of *draft* given *context*."""
        system = (
            "You are a rigorous legal source critic. "
            "Evaluate the draft for factual accuracy, citation correctness, "
            "jurisdictional consistency, and authority gaps. "
            "Return a structured critique with: ACCURATE claims, "
            "UNSUPPORTED claims, MISSING authority, and RISK flags."
        )
        prompt = f"DRAFT:\n{draft}\n\nRETRIEVED CONTEXT:\n{context}"
        return self.generate(system=system, prompt=prompt, **kwargs)

    def judge(self, *, drafts: str, critiques: str, query: str, **kwargs: Any) -> str:
        """Synthesise the best final answer from drafts + critiques."""
        system = (
            "You are a senior legal research editor. Given multiple anonymised "
            "drafts and their critiques, synthesise one source-grounded answer. "
            "Preserve citation markers that map to supplied sources, remove "
            "unsupported claims, and do not mention model or deliberation details."
        )
        prompt = (
            f"QUERY: {query}\n\n"
            f"ANONYMISED DRAFTS:\n{drafts}\n\n"
            f"CRITIQUES:\n{critiques}"
        )
        return self.generate(system=system, prompt=prompt, **kwargs)

    @property
    def available(self) -> bool:
        return self._available


# ---------------------------------------------------------------------------
# Concrete provider factories
# ---------------------------------------------------------------------------


def _build_gemini_generate() -> Callable[..., str]:
    """Closure over the existing Gemini client."""

    def _gen(*, system: str, prompt: str, **kwargs: Any) -> str:
        from src.services.gemini_client import generate_gemini_content

        temperature = kwargs.get("temperature", 0.15)
        max_tokens = kwargs.get("max_output_tokens", 4096)
        result = generate_gemini_content(
            system=system,
            prompt=prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if result.error:
            logger.warning("Gemini error: %s", result.error)
        return result.text

    return _gen


def _build_groq_generate() -> Callable[..., str]:
    """Closure over the existing Groq client."""

    def _gen(*, system: str, prompt: str, **kwargs: Any) -> str:
        from src.services.groq_client import generate_groq_chat

        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_output_tokens", 4096)
        result = generate_groq_chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=kwargs.get("timeout", GROQ_REQUEST_TIMEOUT_SECONDS),
        )
        if result.error:
            logger.warning("Groq error: %s", result.error)
        return result.text

    return _gen


def _build_openai_compatible_generate(
    *,
    base_url: str,
    api_key: str,
    model: str,
    provider_label: str,
) -> Callable[..., str]:
    """OpenAI-compatible /v1/chat/completions provider."""
    chat_url = f"{base_url.rstrip('/')}/chat/completions"

    def _gen(*, system: str, prompt: str, **kwargs: Any) -> str:
        temperature = kwargs.get("temperature", 0.1)
        max_tokens = kwargs.get("max_output_tokens", 4096)
        timeout = kwargs.get("timeout", OMNILEGAL_COUNCIL_TIMEOUT_SECONDS)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        if "openrouter.ai" in base_url:
            headers.setdefault("HTTP-Referer", "http://localhost")
            headers.setdefault("X-Title", "OmniLegal")
        try:
            resp = http_requests.post(chat_url, headers=headers, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            choices = data.get("choices") or []
            if choices:
                message = choices[0].get("message") or {}
                content = message.get("content")
                if isinstance(content, list):
                    return "\n".join(
                        str(part.get("text") or part.get("content") or "")
                        for part in content
                        if isinstance(part, dict)
                    ).strip()
                return str(content or choices[0].get("text") or "").strip()
            if data.get("error"):
                logger.warning("%s error: %s", provider_label, data.get("error"))
            return ""
        except Exception as exc:
            logger.warning("%s error (%s): %s", provider_label, model, exc)
            return ""

    return _gen


def _build_anthropic_generate(model: str) -> Callable[..., str]:
    """Anthropic Messages API provider."""
    url = "https://api.anthropic.com/v1/messages"

    def _gen(*, system: str, prompt: str, **kwargs: Any) -> str:
        payload = {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_output_tokens", 4096),
            "temperature": kwargs.get("temperature", 0.1),
        }
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        try:
            resp = http_requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=kwargs.get("timeout", OMNILEGAL_COUNCIL_TIMEOUT_SECONDS),
            )
            resp.raise_for_status()
            data = resp.json()
            blocks = data.get("content") or []
            return "\n".join(
                str(block.get("text") or "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            ).strip()
        except Exception as exc:
            logger.warning("Anthropic error (%s): %s", model, exc)
            return ""

    return _gen


def _fetch_openai_compatible_model_records(base_url: str, api_key: str) -> list[dict[str, Any]]:
    """Best-effort model discovery for OpenAI-compatible gateways."""
    try:
        resp = http_requests.get(
            f"{base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        models = data.get("data") if isinstance(data, dict) else data
        result: list[dict[str, Any]] = []
        for item in models or []:
            if isinstance(item, dict) and item.get("id"):
                result.append(item)
            elif isinstance(item, str):
                result.append({"id": item})
        return result
    except Exception as exc:
        logger.info("OpenAI-compatible model discovery skipped: %s", exc)
        return []


def _fetch_openai_compatible_models(base_url: str, api_key: str) -> list[str]:
    """Return discovered model IDs for tests and diagnostics."""
    return [str(item.get("id")) for item in _fetch_openai_compatible_model_records(base_url, api_key)]


def _is_free_model_record(record: dict[str, Any]) -> bool:
    pricing = record.get("pricing") or {}
    return str(pricing.get("prompt")) == "0" and str(pricing.get("completion")) == "0"


def _free_model_score(record: dict[str, Any]) -> tuple[int, int]:
    model_id = str(record.get("id") or "").lower()
    name = str(record.get("name") or "").lower()
    haystack = f"{model_id} {name}"
    priority = 0
    for idx, keyword in enumerate(("nvidia", "gemma", "minimax", "qwen", "gpt-oss", "openrouter/free")):
        if keyword in haystack:
            priority = max(priority, 100 - idx)
    context = int(record.get("context_length") or 0)
    return priority, context


def _select_openai_models(
    available: list[str],
    records: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Select strongest configured models present in the gateway catalog."""
    if OPENAI_MODEL:
        return [OPENAI_MODEL]
    available_map = {m.lower(): m for m in available}
    selected: list[str] = []
    if OPENROUTER_PREFER_FREE_MODELS and "openrouter.ai" in OPENAI_BASE_URL:
        for preferred in OPENROUTER_FREE_MODEL_CANDIDATES:
            match = available_map.get(preferred.lower())
            if match and match not in selected:
                selected.append(match)
            if len(selected) >= OPENAI_COMPAT_MAX_MODELS:
                return selected
        free_records = [
            record for record in (records or [])
            if _is_free_model_record(record)
        ]
        for record in sorted(free_records, key=_free_model_score, reverse=True):
            model_id = str(record.get("id") or "")
            if model_id and model_id not in selected:
                selected.append(model_id)
            if len(selected) >= OPENAI_COMPAT_MAX_MODELS:
                return selected
        if selected:
            return selected
    for preferred in OPENAI_MODEL_CANDIDATES:
        match = available_map.get(preferred.lower())
        if match and match not in selected:
            selected.append(match)
        if len(selected) >= OPENAI_COMPAT_MAX_MODELS:
            break
    return selected


def _build_ollama_generate(base_url: str, model: str) -> Callable[..., str]:
    """REST-based Ollama provider."""

    def _gen(*, system: str, prompt: str, **kwargs: Any) -> str:
        temperature = kwargs.get("temperature", 0.15)
        timeout = kwargs.get("timeout", OMNILEGAL_COUNCIL_TIMEOUT_SECONDS)
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": kwargs.get("max_output_tokens", 4096),
            },
        }
        try:
            resp = http_requests.post(
                f"{base_url}/api/chat",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return (data.get("message") or {}).get("content", "").strip()
        except Exception as exc:
            logger.warning("Ollama error (%s): %s", model, exc)
            return ""

    return _gen


def _ollama_available(base_url: str) -> bool:
    """Quick connectivity check."""
    try:
        resp = http_requests.get(f"{base_url}/api/tags", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


def _ollama_has_model(base_url: str, model: str) -> bool:
    """Check whether the requested model is pulled."""
    try:
        resp = http_requests.get(f"{base_url}/api/tags", timeout=3)
        if resp.status_code != 200:
            return False
        for m in resp.json().get("models", []):
            name = m.get("name", "")
            # Ollama returns "qwen3:8b" or "qwen3:8b-q4_K_M" etc.
            if name == model or name.startswith(f"{model}:") or model.startswith(name.split(":")[0]):
                return True
        return False
    except Exception:
        return False


def _provider_family(name: str) -> str:
    """Group providers so drafting prefers backend diversity."""
    if name.startswith("openai_compatible"):
        return "openai_compatible"
    if name.startswith("huggingface"):
        return "huggingface"
    return name.split("_", 1)[0]


# ---------------------------------------------------------------------------
# Registry singleton
# ---------------------------------------------------------------------------


class ProviderRegistry:
    """Thread-safe singleton registry of LLM providers."""

    _instance: ProviderRegistry | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._providers: dict[str, ProviderMeta] = {}
        self._role_preferences: dict[RoleKind, list[str]] = {
            "drafter": ["openai_compatible", "anthropic", "gemini", "groq", "ollama"],
            "critic": ["openai_compatible", "anthropic", "gemini", "groq", "ollama"],
            "judge": ["openai_compatible", "anthropic", "gemini", "groq", "ollama"],
        }

    @classmethod
    def get_instance(cls) -> ProviderRegistry:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    registry = cls()
                    registry._auto_discover()
                    cls._instance = registry
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (primarily for tests)."""
        with cls._lock:
            cls._instance = None

    # ── Registration ──────────────────────────────────────────────────

    def register(self, provider: ProviderMeta) -> None:
        self._providers[provider.name] = provider
        logger.info("Registered provider: %s (available=%s)", provider.name, provider.available)

    def _auto_discover(self) -> None:
        """Probe each provider and register those that respond."""
        # OpenAI-compatible gateways: OpenAI, OpenRouter, local TGI/vLLM, LiteLLM, etc.
        if OPENAI_API_KEY:
            discovered_records = _fetch_openai_compatible_model_records(OPENAI_BASE_URL, OPENAI_API_KEY)
            discovered = [str(item.get("id")) for item in discovered_records if item.get("id")]
            for idx, model in enumerate(_select_openai_models(discovered, discovered_records)):
                name = "openai_compatible" if idx == 0 else f"openai_compatible_{idx + 1}"
                self.register(
                    ProviderMeta(
                        name=name,
                        model_id=model,
                        timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                        cost_tier="free_tier" if model.endswith(":free") or model == "openrouter/free" else "paid",
                        privacy_tier="zero_retention_api",
                        quality_score=96 - (idx * 3),
                        supports_json=True,
                        supports_streaming=True,
                        _generate_fn=_build_openai_compatible_generate(
                            base_url=OPENAI_BASE_URL,
                            api_key=OPENAI_API_KEY,
                            model=model,
                            provider_label=name,
                        ),
                        _available=True,
                    )
                )
            if not self.get("openai_compatible") and OPENAI_MODEL:
                self.register(
                    ProviderMeta(
                        name="openai_compatible",
                        model_id=OPENAI_MODEL,
                        timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                        cost_tier="paid",
                        privacy_tier="zero_retention_api",
                        quality_score=95,
                        supports_json=True,
                        supports_streaming=True,
                        _generate_fn=_build_openai_compatible_generate(
                            base_url=OPENAI_BASE_URL,
                            api_key=OPENAI_API_KEY,
                            model=OPENAI_MODEL,
                            provider_label="openai_compatible",
                        ),
                        _available=True,
                    )
                )

        # Anthropic
        if ANTHROPIC_API_KEY:
            self.register(
                ProviderMeta(
                    name="anthropic",
                    model_id=ANTHROPIC_MODEL,
                    timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                    cost_tier="paid",
                    privacy_tier="zero_retention_api",
                    quality_score=93,
                    supports_streaming=True,
                    _generate_fn=_build_anthropic_generate(ANTHROPIC_MODEL),
                    _available=True,
                )
            )

        # Gemini
        if GEMINI_API_KEY:
            self.register(
                ProviderMeta(
                    name="gemini",
                    model_id=GEMINI_REFINER_MODEL,
                    timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                    cost_tier="free_tier",
                    privacy_tier="external_api",
                    quality_score=88,
                    supports_streaming=True,
                    _generate_fn=_build_gemini_generate(),
                    _available=True,
                )
            )

        # Hugging Face Inference Providers router
        if OMNILEGAL_ENABLE_HF_PROVIDER and HF_TOKEN and HF_INFERENCE_MODEL:
            self.register(
                ProviderMeta(
                    name="huggingface",
                    model_id=HF_INFERENCE_MODEL,
                    timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                    cost_tier="free_tier",
                    privacy_tier="external_api",
                    quality_score=84,
                    supports_streaming=True,
                    _generate_fn=_build_openai_compatible_generate(
                        base_url=HF_INFERENCE_BASE_URL,
                        api_key=HF_TOKEN,
                        model=HF_INFERENCE_MODEL,
                        provider_label="huggingface",
                    ),
                    _available=True,
                )
            )

        # Groq
        if GROQ_API_KEY:
            self.register(
                ProviderMeta(
                    name="groq",
                    model_id=GROQ_MODEL,
                    timeout=GROQ_REQUEST_TIMEOUT_SECONDS,
                    cost_tier="free_tier",
                    privacy_tier="external_api",
                    quality_score=78,
                    supports_streaming=True,
                    _generate_fn=_build_groq_generate(),
                    _available=True,
                )
            )

        # Ollama (local)
        if _ollama_available(OMNILEGAL_OLLAMA_BASE_URL):
            model = OMNILEGAL_OLLAMA_MODEL
            has_model = _ollama_has_model(OMNILEGAL_OLLAMA_BASE_URL, model)
            self.register(
                ProviderMeta(
                    name="ollama",
                    model_id=model,
                    timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS + 30,  # local inference may be slower
                    cost_tier="free",
                    privacy_tier="local",
                    quality_score=70,
                    is_local=True,
                    _generate_fn=_build_ollama_generate(OMNILEGAL_OLLAMA_BASE_URL, model),
                    _available=has_model,
                )
            )
            if not has_model:
                logger.warning(
                    "Ollama is running but model %s is not pulled. "
                    "Run: ollama pull %s",
                    model,
                    model,
                )

    # ── Lookup ────────────────────────────────────────────────────────

    def get(self, name: str) -> ProviderMeta | None:
        return self._providers.get(name)

    def _preference_rank(self, provider: ProviderMeta, role: RoleKind) -> int:
        family = _provider_family(provider.name)
        for idx, preferred in enumerate(self._role_preferences.get(role, [])):
            if provider.name == preferred or family == preferred:
                return idx
        return 999

    def _available_for_role(self, role: RoleKind) -> list[ProviderMeta]:
        providers = [
            p for p in self._providers.values()
            if p.available and role in p.roles
        ]
        return sorted(
            providers,
            key=lambda p: (
                self._preference_rank(p, role),
                -p.quality_score,
                p.timeout,
                p.name,
            ),
        )

    def get_best_for(self, role: RoleKind) -> ProviderMeta | None:
        """Return the strongest available provider for *role*."""
        providers = self._available_for_role(role)
        return providers[0] if providers else None

    def get_drafters(self, count: int = 3) -> list[ProviderMeta]:
        """Return up to *count* available providers, preferring backend diversity."""
        result: list[ProviderMeta] = []
        seen_families: set[str] = set()
        candidates = self._available_for_role("drafter")
        if OPENROUTER_PREFER_FREE_MODELS:
            openai_family = [
                p for p in candidates
                if p.name.startswith("openai_compatible") and (p.model_id.endswith(":free") or p.model_id == "openrouter/free")
            ]
            for provider in openai_family[: min(2, count)]:
                if provider not in result:
                    result.append(provider)
                    seen_families.add(_provider_family(provider.name))
        for provider in candidates:
            if len(result) >= count:
                break
            family = _provider_family(provider.name)
            if family not in seen_families:
                result.append(provider)
                seen_families.add(family)
        for provider in candidates:
            if len(result) >= count:
                break
            if provider not in result:
                result.append(provider)
        return result

    def all_available(self) -> list[ProviderMeta]:
        return [p for p in self._providers.values() if p.available]

    def summary(self) -> dict[str, Any]:
        """Return a diagnostic summary for health checks."""
        return {
            p.name: {
                "available": p.available,
                "model_id": p.model_id,
                "cost_tier": p.cost_tier,
                "privacy_tier": p.privacy_tier,
                "quality_score": p.quality_score,
                "roles": list(p.roles),
                "is_local": p.is_local,
                "timeout": p.timeout,
            }
            for p in self._providers.values()
        }
