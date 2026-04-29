"""Orchestrator — glues classify → retrieve → generate → verify → format."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from pipeline_v2.citation_verifier import verify
from pipeline_v2.classifier import analyze_query
from pipeline_v2.llm import LLMUnavailable, complete
from pipeline_v2.prompts import build_user_message, system_for
from pipeline_v2.retriever import retrieve
from pipeline_v2.settings import DISCLAIMER, TRACE_DIR
from pipeline_v2.vector_store import collection_count

log = logging.getLogger("pipeline_v2.orchestrator")


def _format_sources_block(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return ""
    lines = ["", "---", "**Sources used**"]
    for s in sources:
        meta = s.get("metadata") or {}
        label = s.get("label") or "?"
        name = meta.get("citation") or meta.get("source_name") or "Unknown"
        jur = meta.get("jurisdiction") or "?"
        dtype = meta.get("doc_type") or "?"
        url = meta.get("url") or ""
        link = f" — [link]({url})" if url else ""
        score = s.get("final_score", s.get("score", 0.0))
        lines.append(
            f"- **[{label}]** *{jur} · {dtype}* — {name}{link}  _(score={score:.2f})_"
        )
    return "\n".join(lines)


def _write_trace(payload: dict) -> None:
    try:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = TRACE_DIR / f"trace_{ts}_{id(payload) & 0xFFFF:04x}.json"
        path.write_text(json.dumps(payload, default=str, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def run_query(query: str, mode: str | None = None, style: str = "long") -> dict:
    """Main entrypoint.

    Returns dict:
      - ok: bool
      - answer: str (Markdown)
      - mode: str
      - jurisdictions: list[str]
      - sources: list[{label, citation, jurisdiction, doc_type, url, score}]
      - verification: {cited, uncited, grounded_ratio, invalid, insufficient}
      - provider: str
      - elapsed_ms: int
      - error: str|None
    """
    t0 = time.time()

    # 0. Guardrail: corpus must have documents.
    total = collection_count()
    if total == 0:
        return {
            "ok": False,
            "answer": (
                "⚠️ The legal corpus is empty — no sources are indexed yet.\n\n"
                "Run `python -m pipeline_v2.ingest_seed` to seed the verification "
                "corpus before asking questions."
            ),
            "mode": mode or "research",
            "jurisdictions": [],
            "sources": [],
            "verification": {},
            "provider": "",
            "elapsed_ms": int((time.time() - t0) * 1000),
            "error": "empty_corpus",
        }

    # 1. Classify.
    analysis = analyze_query(query, forced_mode=mode)

    # 2. Retrieve.
    sources = retrieve(analysis)

    # If no sources -> abstain explicitly.
    if not sources:
        answer = (
            "**INSUFFICIENT EVIDENCE:** the indexed corpus does not contain any "
            "document that matches this question. Try rephrasing with a specific "
            "statute, treaty, or case name, or widen the jurisdiction."
        )
        report = verify(answer, [])
        return {
            "ok": True,
            "answer": answer + "\n\n" + DISCLAIMER,
            "mode": analysis.mode,
            "jurisdictions": analysis.jurisdictions,
            "sources": [],
            "verification": {
                "cited": 0,
                "uncited": 0,
                "grounded_ratio": 1.0,
                "invalid": [],
                "insufficient": True,
            },
            "provider": "",
            "elapsed_ms": int((time.time() - t0) * 1000),
            "error": None,
        }

    # 3. Synthesize.
    system = system_for(analysis.mode)
    user = build_user_message(query, sources, style)

    try:
        draft, provider = complete(system, user, temperature=0.12)
    except LLMUnavailable as e:
        return {
            "ok": False,
            "answer": (
                "⚠️ The language model is temporarily unreachable. "
                "Please try again in a moment.\n\n"
                f"`{type(e).__name__}: {e}`"
            ),
            "mode": analysis.mode,
            "jurisdictions": analysis.jurisdictions,
            "sources": [],
            "verification": {},
            "provider": "",
            "elapsed_ms": int((time.time() - t0) * 1000),
            "error": "llm_unavailable",
        }

    # 4. Verify citations.
    report = verify(draft, sources)

    # Detect hallucinated sources: if more than 40% of claims are uncited OR
    # any invalid [S#] is cited, re-ask the model once with a stricter nudge.
    if (
        not report.has_insufficient_flag
        and (report.grounded_ratio < 0.6 or report.invalid_citations)
    ):
        repair_user = user + (
            "\n\nSTRICT REPAIR: your previous answer had ungrounded claims or "
            "invalid citation tags. Rewrite the answer so every factual sentence "
            f"ends with a [S#] tag using ONLY the labels {sorted({s['label'] for s in sources})}. "
            "If the sources cannot support a claim, remove the claim or write "
            "'INSUFFICIENT EVIDENCE:' and stop."
        )
        try:
            draft2, provider2 = complete(system, repair_user, temperature=0.05)
            report2 = verify(draft2, sources)
            if (
                report2.grounded_ratio > report.grounded_ratio
                or (not report2.invalid_citations and report.invalid_citations)
            ):
                draft, provider, report = draft2, provider2, report2
        except Exception as e:  # noqa: BLE001
            log.warning("Repair pass failed: %s", e)

    # 5. Compose final answer.
    final_parts = [report.answer]

    # Add confidence badge
    if report.has_insufficient_flag:
        badge = "⚪ _Verification: abstention (insufficient evidence)_"
    elif report.invalid_citations:
        badge = f"🔴 _Verification: {len(report.invalid_citations)} invalid citation tag(s) — flagged above_"
    elif report.grounded_ratio >= 0.9:
        badge = f"🟢 _Verification: {int(report.grounded_ratio*100)}% of claims grounded_"
    elif report.grounded_ratio >= 0.6:
        badge = f"🟡 _Verification: {int(report.grounded_ratio*100)}% of claims grounded — check flagged lines_"
    else:
        badge = f"🔴 _Verification: only {int(report.grounded_ratio*100)}% of claims grounded — treat with caution_"

    final_parts.append("")
    final_parts.append(badge)
    final_parts.append(_format_sources_block(sources))
    final_parts.append("")
    final_parts.append(DISCLAIMER)

    final = "\n".join(p for p in final_parts if p is not None)

    result = {
        "ok": True,
        "answer": final,
        "mode": analysis.mode,
        "jurisdictions": analysis.jurisdictions,
        "sources": [
            {
                "label": s["label"],
                "citation": (s.get("metadata") or {}).get("citation")
                or (s.get("metadata") or {}).get("source_name")
                or "Unknown",
                "jurisdiction": (s.get("metadata") or {}).get("jurisdiction") or "?",
                "doc_type": (s.get("metadata") or {}).get("doc_type") or "?",
                "url": (s.get("metadata") or {}).get("url") or "",
                "score": float(s.get("final_score", s.get("score", 0.0))),
            }
            for s in sources
        ],
        "verification": {
            "cited": report.cited_sentences,
            "uncited": report.uncited_sentences,
            "grounded_ratio": report.grounded_ratio,
            "invalid": report.invalid_citations,
            "insufficient": report.has_insufficient_flag,
        },
        "provider": provider,
        "elapsed_ms": int((time.time() - t0) * 1000),
        "error": None,
    }

    _write_trace({
        "query": query,
        "mode": analysis.mode,
        "jurisdictions": analysis.jurisdictions,
        "style": style,
        "provider": provider,
        "source_count": len(sources),
        "verification": result["verification"],
        "elapsed_ms": result["elapsed_ms"],
    })

    return result
