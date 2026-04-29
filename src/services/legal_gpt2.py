from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from typing import Any

from src.config import (
    LEGAL_GPT2_CONFIG,
    LEGAL_GPT2_LOCAL_DIR,
    LEGAL_GPT2_TOKENIZER_MODEL,
    LEGAL_GPT2_WEIGHTS,
    OMNILEGAL_ENABLE_LEGAL_GPT2_QUERY_ASSIST,
    OMNILEGAL_LEGAL_GPT2_MAX_NEW_TOKENS,
)

_LOAD_LOCK = threading.Lock()
_MODEL_BUNDLE: "LegalGPT2Bundle | None" = None
_WARNINGS_EMITTED: set[str] = set()

_ALLOWED_HINT_PATTERNS = [
    r"consular(?: notification| access)?",
    r"embassy",
    r"interpreter",
    r"defen[cs]e counsel",
    r"lawyer",
    r"administrative (?:offence|offense|fine)",
    r"traffic (?:offence|offense|law|safety)",
    r"road traffic",
    r"road safety",
    r"driving licen[cs]e",
    r"foreign licen[cs]e",
    r"international driving permit",
    r"motor vehicles?",
    r"detention rights",
    r"police powers",
    r"criminal procedure",
    r"passport",
    r"immigration",
    r"bail",
]


@dataclass(frozen=True)
class LegalGPT2Bundle:
    model: Any | None
    tokenizer: Any | None
    available: bool
    reason: str = ""


def _warn_once(message: str) -> None:
    if message in _WARNINGS_EMITTED:
        return
    _WARNINGS_EMITTED.add(message)
    print(f"Warning: {message}")


def _try_load_tokenizer() -> Any | None:
    from transformers import AutoTokenizer

    candidates = [
        (str(LEGAL_GPT2_LOCAL_DIR), True),
        (LEGAL_GPT2_TOKENIZER_MODEL, True),
        (LEGAL_GPT2_TOKENIZER_MODEL, False),
    ]
    for target, local_only in candidates:
        if not target:
            continue
        try:
            tokenizer = AutoTokenizer.from_pretrained(target, local_files_only=local_only)
            if tokenizer.pad_token is None and tokenizer.eos_token is not None:
                tokenizer.pad_token = tokenizer.eos_token
            return tokenizer
        except Exception:
            continue
    return None


def _load_bundle() -> LegalGPT2Bundle:
    if not OMNILEGAL_ENABLE_LEGAL_GPT2_QUERY_ASSIST:
        return LegalGPT2Bundle(model=None, tokenizer=None, available=False, reason="query assist disabled")
    if not LEGAL_GPT2_WEIGHTS.exists() or not LEGAL_GPT2_CONFIG.exists():
        return LegalGPT2Bundle(model=None, tokenizer=None, available=False, reason="model weights or config missing")

    try:
        import torch
        from transformers import AutoModelForCausalLM, GPT2Config, GPT2LMHeadModel
    except Exception as exc:
        return LegalGPT2Bundle(model=None, tokenizer=None, available=False, reason=f"transformers load failed: {type(exc).__name__}: {exc}")

    tokenizer = _try_load_tokenizer()
    if tokenizer is None:
        return LegalGPT2Bundle(model=None, tokenizer=None, available=False, reason="no compatible tokenizer available")

    try:
        model = AutoModelForCausalLM.from_pretrained(
            str(LEGAL_GPT2_LOCAL_DIR),
            local_files_only=True,
        )
        model.eval()
        if hasattr(torch, "set_grad_enabled"):
            torch.set_grad_enabled(False)
        return LegalGPT2Bundle(model=model, tokenizer=tokenizer, available=True, reason="")
    except Exception as exc:
        try:
            config = GPT2Config.from_json_file(str(LEGAL_GPT2_CONFIG))
            model = GPT2LMHeadModel.from_pretrained(
                str(LEGAL_GPT2_LOCAL_DIR),
                config=config,
                local_files_only=True,
            )
            model.eval()
            if hasattr(torch, "set_grad_enabled"):
                torch.set_grad_enabled(False)
            return LegalGPT2Bundle(model=model, tokenizer=tokenizer, available=True, reason="")
        except Exception as fallback_exc:
            return LegalGPT2Bundle(
                model=None,
                tokenizer=tokenizer,
                available=False,
                reason=f"model load failed: {type(exc).__name__}: {exc}; GPT-2 fallback failed: {type(fallback_exc).__name__}: {fallback_exc}",
            )


def _bundle() -> LegalGPT2Bundle:
    global _MODEL_BUNDLE
    if _MODEL_BUNDLE is not None:
        return _MODEL_BUNDLE
    with _LOAD_LOCK:
        if _MODEL_BUNDLE is None:
            _MODEL_BUNDLE = _load_bundle()
            if not _MODEL_BUNDLE.available and _MODEL_BUNDLE.reason:
                _warn_once(f"Legal GPT-2 query assist unavailable: {_MODEL_BUNDLE.reason}")
    return _MODEL_BUNDLE


def _normalise_hint(phrase: str) -> str:
    cleaned = re.sub(r"\s+", " ", phrase.strip().lower())
    cleaned = re.sub(r"^[,;:\-\.\s]+|[,;:\-\.\s]+$", "", cleaned)
    return cleaned


def _hint_allowed(phrase: str) -> bool:
    lowered = _normalise_hint(phrase)
    if len(lowered) < 6 or len(lowered) > 80:
        return False
    return any(re.search(pattern, lowered) for pattern in _ALLOWED_HINT_PATTERNS)


def _extract_hints(text: str, query: str) -> list[str]:
    lowered_query = query.lower()
    candidates: list[str] = []
    for part in re.split(r"[\n,;|]+", text):
        normalized = _normalise_hint(part)
        if not normalized:
            continue
        if normalized in lowered_query:
            continue
        if _hint_allowed(normalized):
            candidates.append(normalized)
    seen: set[str] = set()
    result: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
    return result[:4]


def generate_legal_gpt2_query_hints(
    query: str,
    *,
    iso_codes: list[str] | None = None,
    issue_labels: list[str] | None = None,
) -> list[str]:
    bundle = _bundle()
    if not bundle.available or bundle.model is None or bundle.tokenizer is None:
        return []

    try:
        import torch
    except Exception:
        return []

    jurisdictions = ", ".join(iso_codes or []) or "unspecified"
    issues = ", ".join(issue_labels or []) or "general legal research"
    prompt = (
        "Search hints for cross-border legal research.\n"
        f"Jurisdictions: {jurisdictions}\n"
        f"Issues: {issues}\n"
        f"Question: {query}\n"
        "Keywords:"
    )
    try:
        encoded = bundle.tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=256,
        )
        with torch.no_grad():
            output = bundle.model.generate(
                **encoded,
                max_new_tokens=max(8, OMNILEGAL_LEGAL_GPT2_MAX_NEW_TOKENS),
                do_sample=False,
                pad_token_id=bundle.tokenizer.pad_token_id,
                eos_token_id=bundle.tokenizer.eos_token_id,
            )
        generated = bundle.tokenizer.decode(output[0], skip_special_tokens=True)
    except Exception as exc:
        _warn_once(f"Legal GPT-2 query assist generation failed: {type(exc).__name__}: {exc}")
        return []

    suffix = generated[len(prompt):] if generated.startswith(prompt) else generated
    return _extract_hints(suffix, query)
