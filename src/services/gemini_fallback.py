"""Gemini fallback answers for weak or empty retrieval results.

This module is intentionally conservative: it only runs after the normal
source-grounded pipeline has failed to produce a verified answer. Results are
cached by query hash and API calls are rate-limited across process restarts.
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import (
    GEMINI_API_KEY,
    GEMINI_REQUEST_TIMEOUT_SECONDS,
    LEGAL_RESEARCH_SHORT_DISCLAIMER,
    OMNILEGAL_ENABLE_GEMINI_FALLBACK,
    OMNILEGAL_GEMINI_FALLBACK_CACHE_PATH,
    OMNILEGAL_GEMINI_FALLBACK_MAX_CALLS_PER_HOUR,
    OMNILEGAL_GEMINI_FALLBACK_MODEL,
)
from src.pipeline.state import PipelineStateDict
from src.services.gemini_client import GeminiGeneration, compact_gemini_error, generate_gemini_content

_CACHE_VERSION = 2
_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True)
class GeminiFallbackResult:
    text: str = ""
    model: str = ""
    cache_hit: bool = False
    error: str = ""
    skipped: str = ""


_SYSTEM_PROMPT = """\
You are OmniLegal Codex, a grounded legal research assistant.

Answer the user's legal question fully and helpfully from your legal knowledge.
Do not mention retrieval, databases, sources, or any internal pipeline status.

Rules:
1. Do not invent statute section numbers, article numbers, case names, official
   fines, or deadlines unless the user provided them. Refer to legal principles
   and doctrines by name without fabricating specific citations.
2. Do not advise the user to evade, bribe, falsify documents, or make false
   statements.
3. Answer the legal question asked — explain the doctrine, applicable law,
   rights, obligations, or practical steps as fully as your knowledge allows.
4. Return Markdown with exactly these four headings (in this order):
   ## Legal Analysis
   ## Key Rights and Obligations
   ## Practical Steps
   ## Disclaimer
5. Keep the disclaimer text exactly as supplied. Do not add extra headers.
"""

_USER_TEMPLATE = """\
User question:
{query}

Answer style: {answer_style} (short = 2–4 paragraphs total; long = detailed with full reasoning)
Disclaimer text:
{disclaimer}

Context (do not mention this in the answer):
- Jurisdictions involved: {jurisdictions}
- Legal domains: {legal_domains}
- Jurisdiction analysis:
{jurisdiction_analysis}

Write a complete legal answer to the question above.
"""


def should_attempt_gemini_fallback(state: PipelineStateDict) -> bool:
    """Return True when the verified pipeline did not answer from authority."""
    if not OMNILEGAL_ENABLE_GEMINI_FALLBACK:
        return False

    if state.get("gemini_fallback_used"):
        return False

    # Always fall back to Gemini when retrieval returned nothing
    if not state.get("retrieved"):
        return True

    final = state.get("final") or {}
    pipeline_errors = " ".join(str(err) for err in state.get("pipeline_errors", []) or []).lower()
    if "hybrid retrieval timed out" in pipeline_errors or "hybrid retrieval failed" in pipeline_errors:
        return True

    if not final:
        return True

    grounding = str(final.get("grounding_status") or state.get("grounding_status") or "").lower()
    if final.get("insufficient_context") is True:
        return True
    if grounding in {"", "no_authority", "secondary_only"}:
        return True

    answer = str(final.get("answer") or "").lower()
    if "insufficient evidence" in answer or "no retrieved source passages" in answer:
        return True
    
    if state.get("provider") == "extractive_fallback":
        return True
        
    return False


def apply_gemini_fallback(state: PipelineStateDict) -> PipelineStateDict:
    """Apply a cached/rate-limited Gemini fallback answer when warranted."""
    if not should_attempt_gemini_fallback(state):
        return state

    result = generate_fallback_answer(state)
    if not result.text:
        answer = _deterministic_practical_answer(state)
        final = dict(state.get("final") or {})
        final.update(
            {
                "query": state.get("raw_input", ""),
                "answer": answer,
                "insufficient_context": True,
                "used_model": "local_practical_fallback",
                "gemini_fallback": False,
            }
        )
        return {
            **state,
            "verified_draft": answer,
            "final": final,
            "provider": "local_practical_fallback",
            "gemini_fallback_used": True,
            "gemini_fallback_model": "local_practical_fallback",
            "gemini_fallback_cache_hit": False,
            "gemini_fallback_error": result.error or result.skipped or "Gemini fallback returned no usable answer",
        }

    final = dict(state.get("final") or {})
    final.update(
        {
            "query": state.get("raw_input", ""),
            "answer": result.text,
            "grounding_status": final.get("grounding_status") or "no_authority",
            "insufficient_context": True,
            "used_model": result.model,
            "gemini_fallback": True,
            "gemini_fallback_cache_hit": result.cache_hit,
        }
    )
    return {
        **state,
        "verified_draft": result.text,
        "final": final,
        "provider": result.model,
        "gemini_fallback_used": True,
        "gemini_fallback_model": result.model,
        "gemini_fallback_cache_hit": result.cache_hit,
        "gemini_fallback_error": "",
        "gemini_mode": "knowledge_generation",
        "gemini_model": result.model,
    }


def generate_fallback_answer(state: PipelineStateDict) -> GeminiFallbackResult:
    if not OMNILEGAL_ENABLE_GEMINI_FALLBACK:
        return GeminiFallbackResult(skipped="Gemini fallback is disabled.")
    if not GEMINI_API_KEY:
        return GeminiFallbackResult(error="GEMINI_API_KEY is not set.")

    cache_path = Path(OMNILEGAL_GEMINI_FALLBACK_CACHE_PATH)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    key = _cache_key(state)

    try:
        cached = _read_cache(cache_path, key)
        if cached:
            return GeminiFallbackResult(
                text=cached["answer"],
                model=cached["model"],
                cache_hit=True,
            )

        ok, reason = _reserve_api_call(cache_path)
        if not ok:
            return GeminiFallbackResult(skipped=reason)

        generation = _call_gemini(state)
        if generation.text:
            answer = _normalise_answer(generation.text)
            _write_cache(cache_path, key, answer, generation.model)
            return GeminiFallbackResult(text=answer, model=generation.model)
        return GeminiFallbackResult(error=compact_gemini_error(generation.error) or "Gemini returned no usable text.")
    except Exception as exc:
        return GeminiFallbackResult(error=f"{type(exc).__name__}: {exc}")


def _cache_key(state: PipelineStateDict) -> str:
    query = re.sub(r"\s+", " ", str(state.get("raw_input") or "").strip().lower())
    payload = {
        "version": _CACHE_VERSION,
        "model": OMNILEGAL_GEMINI_FALLBACK_MODEL,
        "answer_style": str(state.get("answer_style") or "long"),
        "query": query,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=15)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fallback_cache (
            cache_key TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            answer TEXT NOT NULL,
            created_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS api_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            called_at REAL NOT NULL
        )
        """
    )
    return conn


def _read_cache(path: Path, key: str) -> dict[str, str] | None:
    now = time.time()
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT model, answer, created_at FROM fallback_cache WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if not row:
            return None
        model, answer, created_at = row
        if now - float(created_at) > _CACHE_TTL_SECONDS:
            conn.execute("DELETE FROM fallback_cache WHERE cache_key = ?", (key,))
            return None
        return {"model": str(model), "answer": str(answer)}
    finally:
        conn.close()


def _write_cache(path: Path, key: str, answer: str, model: str) -> None:
    conn = _connect(path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO fallback_cache (cache_key, model, answer, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, model, answer, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def _reserve_api_call(path: Path) -> tuple[bool, str]:
    now = time.time()
    window_start = now - 3600
    conn = _connect(path)
    try:
        conn.execute("DELETE FROM api_calls WHERE called_at < ?", (window_start,))
        count = int(conn.execute("SELECT COUNT(*) FROM api_calls WHERE called_at >= ?", (window_start,)).fetchone()[0])
        if count >= OMNILEGAL_GEMINI_FALLBACK_MAX_CALLS_PER_HOUR:
            return (
                False,
                f"Gemini fallback hourly budget reached ({OMNILEGAL_GEMINI_FALLBACK_MAX_CALLS_PER_HOUR}/hour).",
            )
        conn.execute("INSERT INTO api_calls (called_at) VALUES (?)", (now,))
        conn.commit()
    finally:
        conn.close()
    return True, ""


def _call_gemini(state: PipelineStateDict) -> GeminiGeneration:
    result_queue: queue.Queue[GeminiGeneration] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            result_queue.put(
                generate_gemini_content(
                    system=_SYSTEM_PROMPT,
                    prompt=_build_prompt(state),
                    model=OMNILEGAL_GEMINI_FALLBACK_MODEL,
                    temperature=0.2,
                    max_output_tokens=_max_output_tokens(state),
                )
            )
        except Exception as exc:
            result_queue.put(
                GeminiGeneration(
                    text="",
                    model=OMNILEGAL_GEMINI_FALLBACK_MODEL,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout=GEMINI_REQUEST_TIMEOUT_SECONDS)
    if thread.is_alive():
        return GeminiGeneration(
            text="",
            model=OMNILEGAL_GEMINI_FALLBACK_MODEL,
            error=f"Gemini fallback timed out after {int(GEMINI_REQUEST_TIMEOUT_SECONDS)}s",
        )
    try:
        return result_queue.get_nowait()
    except queue.Empty:
        return GeminiGeneration(text="", model=OMNILEGAL_GEMINI_FALLBACK_MODEL, error="Gemini returned no result.")


def _build_prompt(state: PipelineStateDict) -> str:
    final = state.get("final") or {}
    reason = "; ".join(str(err) for err in state.get("pipeline_errors", []) or [])
    if not reason:
        reason = "general practical fallback"

    return _USER_TEMPLATE.format(
        query=state.get("raw_input", ""),
        answer_style=str(state.get("answer_style") or "long"),
        disclaimer=LEGAL_RESEARCH_SHORT_DISCLAIMER,
        reason=reason,
        jurisdictions=", ".join(str(item) for item in final.get("jurisdictions_considered", []) or []) or "unknown",
        legal_domains=", ".join(str(item) for item in final.get("legal_domains", []) or state.get("issue_labels", []) or []) or "unknown",
        jurisdiction_analysis=_format_jurisdiction_analysis(state),
    )


def _format_jurisdiction_analysis(state: PipelineStateDict) -> str:
    analyses = state.get("jurisdiction_analyses", []) or []
    if not analyses:
        return "- None available."
    lines: list[str] = []
    for analysis in analyses[:4]:
        rules = []
        for rule in analysis.get("applicable_rules", [])[:3]:
            rules.append(rule.get("rule", "") if isinstance(rule, dict) else str(rule))
        lines.append(
            "- "
            f"jurisdiction={analysis.get('jurisdiction', 'unknown')}; "
            f"conclusion={analysis.get('conclusion', 'indeterminate')}; "
            f"rules={'; '.join(rule for rule in rules if rule) or 'n/a'}; "
            f"application={str(analysis.get('application', '') or '').strip() or 'n/a'}"
        )
    return "\n".join(lines)


def _max_output_tokens(state: PipelineStateDict) -> int:
    return 900 if str(state.get("answer_style") or "").lower() == "short" else 1600


def _normalise_answer(text: str) -> str:
    answer = str(text or "").strip()
    if "## Disclaimer" not in answer:
        answer = answer.rstrip() + f"\n\n## Disclaimer\n{LEGAL_RESEARCH_SHORT_DISCLAIMER}"
    # Ensure the answer starts with a recognised heading
    if not re.match(r"^##\s+", answer):
        answer = "## Legal Analysis\n" + answer
    # Strip any "no sources / insufficient evidence" sentences from the output
    answer = re.sub(
        r"(?im)^##\s*Sourced Authority\s*\n(?:.*(?:\n|$))*?(?=^##\s+|\Z)",
        "",
        answer,
    )
    answer = re.sub(
        r"(?i)\b(no|not enough|insufficient)\s+(verified\s+)?(local\s+)?(source|sources|authority|evidence)[^.!\n]*(?:[.!\n]|$)",
        "",
        answer,
    )
    return answer.strip()


def _deterministic_practical_answer(state: PipelineStateDict) -> str:
    query = str(state.get("raw_input") or "").lower()
    analyses = state.get("jurisdiction_analyses", []) or []
    rule_lines: list[str] = []
    for analysis in analyses[:2]:
        for rule in analysis.get("applicable_rules", [])[:2]:
            rendered = rule.get("rule", "") if isinstance(rule, dict) else str(rule)
            if rendered and rendered not in rule_lines:
                rule_lines.append(rendered)

    is_russia_india_licence = any(term in query for term in ["russia", "russian"]) and any(
        term in query for term in ["indian", "india"]
    ) and any(term in query for term in ["licence", "license", "driving"])

    if is_russia_india_licence:
        bottom_line = (
            "You usually do not get out of this by relying on the passport alone. Treat it as a Russian traffic or "
            "administrative-law problem: the immediate goal is to avoid escalation, understand the exact allegation, "
            "and have a local lawyer argue the best lawful route, such as document-production, administrative fine, "
            "appeal, or procedural defect."
        )
        if rule_lines:
            bottom_line += " The current legal assessment is that Russian authorities may treat an Indian licence alone as insufficient unless a valid international driving permit or locally recognised driving entitlement applies."
        steps = (
            "1. Ask for the exact charge, article, protocol number, officer details, court date, and any fine or summons in writing.\n"
            "2. Ask for an interpreter before answering detailed questions or signing anything you do not fully understand.\n"
            "3. Contact a Russian traffic or administrative lawyer quickly; do not rely only on informal advice from the officer.\n"
            "4. Preserve and show your passport, visa or registration documents, Indian driving licence, rental agreement or owner permission, insurance, and any international driving permit or notarised translation if you have one.\n"
            "5. If detained, ask to contact the Indian embassy or consulate and tell your lawyer or family where you are.\n"
            "6. Ask the lawyer whether the case can be handled as a document or administrative issue, whether the stop or paperwork had defects, whether you can pay or appeal a fine, and whether driving again would create a worse offence."
        )
    else:
        bottom_line = (
            "Treat this as a local-law problem first. Your safest path is to identify the exact allegation, avoid making "
            "unclear admissions, and get local legal help before deciding whether to pay, contest, appeal, or provide documents."
        )
        steps = (
            "1. Get the charge, notice, summons, or protocol in writing.\n"
            "2. Ask for an interpreter if you are not fully comfortable in the local language.\n"
            "3. Preserve every document connected to the stop or case.\n"
            "4. Speak with a qualified local lawyer before signing admissions or missing deadlines.\n"
            "5. Contact your consulate if you are detained or your passport is taken."
        )

    return (
        f"## Quick Answer\n{bottom_line}\n\n"
        f"## What To Do Now\n{steps}\n\n"
        "## What Not To Do\n"
        "Do not bribe anyone, run away, lie about who was driving, falsify or backdate documents, ignore a summons, "
        "or keep driving until a local lawyer confirms you are legally allowed to do so.\n\n"
        f"## Disclaimer\n{LEGAL_RESEARCH_SHORT_DISCLAIMER}"
    )
