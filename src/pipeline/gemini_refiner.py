"""
Step 5.5 — provider-backed draft refinement.

This node only polishes an existing grounded draft. It does not generate legal
answers from model knowledge when retrieval is weak.
"""
from __future__ import annotations

import queue
import re
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    GEMINI_REFINER_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    GROQ_REQUEST_TIMEOUT_SECONDS,
    LEGAL_RESEARCH_SHORT_DISCLAIMER,
)
from src.pipeline.state import PipelineStateDict
from src.services.gemini_client import GeminiGeneration, compact_gemini_error, generate_gemini_content
from src.services.groq_client import generate_groq_chat

_GEMINI_MODEL = GEMINI_REFINER_MODEL
_GEMINI_MAX_TOKENS = 4096
_GEMINI_TEMPERATURE = 0.1
_GEMINI_WARNINGS_EMITTED: set[str] = set()
_GROQ_WARNINGS_EMITTED: set[str] = set()


@dataclass(frozen=True)
class RefinementGeneration:
    text: str
    provider: str
    model: str
    error: str = ""


_REFINE_SYSTEM = """\
You are an exacting legal research editor for OmniLegal Codex.

Your task is to improve structure, phrasing, and clarity without changing the
factual content supported by the retrieved material.

Mandatory rules:
1. Preserve the exact four-section structure:
   - ## Sourced Authority
   - ## General Principles / Common Practice
   - ## Practical Steps
   - ## Disclaimer
2. Preserve every [N] citation marker exactly as-is. Never remove, invent, or renumber markers.
3. Do not add any statute section, treaty article, regulation number, case name,
   court, year, or procedural detail unless it already appears in the draft or the supplied source excerpts.
4. `Sourced Authority` must remain source-grounded and citation-marked.
5. `General Principles / Common Practice` may explain uncertainty, but must stay consistent with the draft.
6. The disclaimer section must remain the supplied disclaimer text verbatim.
7. Do not add memo headers, dates, salutations, placeholders, or boilerplate.
"""

_REFINE_USER_TEMPLATE = """\
ORIGINAL QUERY: {query}
ANSWER STYLE: {answer_style}
DISCLAIMER TEXT: {disclaimer}

ROUGH DRAFT:
{draft}

RETRIEVED SOURCE EXCERPTS:
{source_summary}

Return the refined answer with the same four sections and preserved citation markers.
"""


def _build_source_summary(retrieved: list[dict[str, Any]]) -> str:
    lines = []
    for index, passage in enumerate(retrieved[:12], 1):
        meta = passage.get("metadata", {}) or {}
        source = meta.get("source_name", "Unknown")
        jurisdiction = meta.get("jurisdiction", "")
        doc_type = meta.get("doc_type", "")
        authority_tier = meta.get("authority_tier", "")
        excerpt = " ".join((passage.get("text") or "").split())[:900]
        lines.append(
            f"[{index}] {source} | {doc_type} | {jurisdiction} | tier={authority_tier}\n{excerpt}"
        )
    return "\n".join(lines) if lines else "No retrieved source excerpts available."


def _strip_memo_artifacts(text: str) -> str:
    cleaned: list[str] = []
    forbidden_prefixes = (
        "## memorandum",
        "# memorandum",
        "**to:**",
        "**from:**",
        "**date:**",
        "**subject:**",
        "to:",
        "from:",
        "date:",
        "subject:",
    )
    for line in (text or "").splitlines():
        lowered = line.strip().lower()
        if any(lowered.startswith(prefix) for prefix in forbidden_prefixes):
            continue
        if "[your name" in lowered or "law firm department" in lowered:
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _numeric_markers(text: str) -> set[str]:
    return set(re.findall(r"\[(\d+)\]", text or ""))


def _append_marker_before_terminal_punctuation(line: str, marker: str) -> str:
    stripped = line.rstrip()
    trailing = line[len(stripped):]
    if marker in stripped:
        return line
    if not stripped:
        return line
    if stripped[-1] in ".!?":
        return stripped[:-1].rstrip() + f" {marker}{stripped[-1]}" + trailing
    return stripped + f" {marker}" + trailing


def _preserve_or_restore_markers(refined: str, original: str, retrieved: list[dict[str, Any]]) -> str:
    original_markers = _numeric_markers(original)
    if not original_markers:
        return refined

    refined_markers = _numeric_markers(refined)
    if original_markers <= refined_markers:
        return refined

    if len(original_markers) == 1 and len(retrieved) == 1:
        marker = f"[{next(iter(original_markers))}]"
        restored: list[str] = []
        for line in refined.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("---") or stripped.startswith(">"):
                restored.append(line)
                continue
            restored.append(_append_marker_before_terminal_punctuation(line, marker))
        return "\n".join(restored).strip()

    return original


def _call_gemini(*, system: str, prompt: str, temperature: float = _GEMINI_TEMPERATURE) -> GeminiGeneration:
    results: queue.Queue[GeminiGeneration] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put(
                generate_gemini_content(
                    system=system,
                    prompt=prompt,
                    model=_GEMINI_MODEL,
                    temperature=temperature,
                    max_output_tokens=_GEMINI_MAX_TOKENS,
                )
            )
        except Exception as exc:
            results.put(GeminiGeneration(text="", model=_GEMINI_MODEL, error=f"{type(exc).__name__}: {exc}"))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS)
    if thread.is_alive():
        result = GeminiGeneration(
            text="",
            model=_GEMINI_MODEL,
            error=f"Gemini request timed out after {int(GEMINI_REQUEST_TIMEOUT_SECONDS)}s",
        )
    else:
        try:
            result = results.get_nowait()
        except queue.Empty:
            result = GeminiGeneration(text="", model=_GEMINI_MODEL, error="Gemini returned no usable text")
    if result.error:
        warning = compact_gemini_error(result.error)
        if warning and warning not in _GEMINI_WARNINGS_EMITTED:
            _GEMINI_WARNINGS_EMITTED.add(warning)
            print(f"Warning: Gemini call failed: {warning}")
    return result


def _compact_groq_error(error: str, *, max_chars: int = 220) -> str:
    cleaned = " ".join(str(error or "").split())
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


def _call_groq_refiner(*, system: str, prompt: str, temperature: float = _GEMINI_TEMPERATURE) -> RefinementGeneration:
    if not GROQ_API_KEY:
        return RefinementGeneration(text="", provider="groq", model=GROQ_MODEL, error="GROQ_API_KEY is not set")
    generation = generate_groq_chat(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=_GEMINI_MAX_TOKENS,
        temperature=temperature,
        timeout=GROQ_REQUEST_TIMEOUT_SECONDS,
    )
    if generation.text:
        return RefinementGeneration(text=generation.text, provider="groq", model=generation.model)
    warning = _compact_groq_error(generation.error or "Groq returned no usable text")
    if warning and warning not in _GROQ_WARNINGS_EMITTED:
        _GROQ_WARNINGS_EMITTED.add(warning)
        print(f"Warning: Groq refinement failed: {warning}")
    return RefinementGeneration(text="", provider="groq", model=GROQ_MODEL, error=warning)


def _call_best_refiner(*, system: str, prompt: str, temperature: float = _GEMINI_TEMPERATURE) -> RefinementGeneration:
    errors: list[str] = []

    if GEMINI_API_KEY:
        gemini = _call_gemini(system=system, prompt=prompt, temperature=temperature)
        if gemini.text:
            return RefinementGeneration(text=gemini.text, provider="gemini", model=gemini.model)
        gemini_error = compact_gemini_error(gemini.error) or "Gemini returned no usable text"
        errors.append(gemini_error)
    else:
        errors.append("GEMINI_API_KEY is not set")

    groq = _call_groq_refiner(system=system, prompt=prompt, temperature=temperature)
    if groq.text:
        return groq
    if groq.error:
        errors.append(groq.error)

    deduped = list(dict.fromkeys(error for error in errors if error))
    return RefinementGeneration(text="", provider="", model="", error="; ".join(deduped))


def _is_draft_insufficient(draft: str) -> bool:
    if not draft or not draft.strip():
        return True
    lower = draft.strip().lower()
    markers = [
        "insufficient evidence",
        "no retrieved primary authority",
        "no clearly relevant legal authority",
        "did not produce a verified answer",
        "the pipeline did not produce",
    ]
    return any(marker in lower for marker in markers)


def refine_draft(state: PipelineStateDict) -> PipelineStateDict:
    draft = state.get("draft", "") or ""
    query = state.get("raw_input", "")
    answer_style = str(state.get("answer_style") or "long")
    retrieved = state.get("retrieved", []) or []

    if _is_draft_insufficient(draft) or not retrieved:
        return {
            **state,
            "gemini_refined": False,
            "refinement_error": "Refinement skipped because no grounded draft was available.",
        }

    if not GEMINI_API_KEY and not GROQ_API_KEY:
        message = "No refinement API key configured (GEMINI_API_KEY or GROQ_API_KEY)."
        print(f"Warning: {message}")
        return {
            **state,
            "gemini_refined": False,
            "gemini_error": message,
            "refinement_error": message,
        }

    user_prompt = _REFINE_USER_TEMPLATE.format(
        query=query,
        answer_style=answer_style,
        disclaimer=LEGAL_RESEARCH_SHORT_DISCLAIMER,
        draft=draft,
        source_summary=_build_source_summary(retrieved),
    )

    generation = _call_best_refiner(system=_REFINE_SYSTEM, prompt=user_prompt)
    refined = _strip_memo_artifacts(generation.text)
    refined = _preserve_or_restore_markers(refined, draft, retrieved)

    if refined and len(refined) > 100:
        return {
            **state,
            "draft_before_refinement": draft,
            "draft": refined,
            "gemini_refined": True,
            "gemini_mode": "refinement",
            "gemini_model": generation.model,
            "gemini_error": "",
            "refinement_provider": generation.provider,
            "refinement_model": generation.model,
            "refinement_error": "",
        }

    return {
        **state,
        "gemini_refined": False,
        "gemini_error": generation.error or "Refinement provider returned no usable text",
        "refinement_error": generation.error or "Refinement provider returned no usable text",
    }
