"""OmniLegal Statute Diff Engine (Pillar 09).

Side-by-side or cross-jurisdiction diff of two pieces of legal text.
Diff is deterministic (difflib SequenceMatcher); the LLM is only used for
the short "what changed legally" impact summary.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.diff")


_IMPACT_SYSTEM = (
    "You are OmniLegal's Statute Diff analyst. Given a deterministic diff "
    "of two legal texts (LEFT and RIGHT), explain in plain English what "
    "actually changed legally — scope changes, who is bound, what conduct "
    "is criminalised or permitted, what defences appear or vanish, what "
    "penalties shift. Be concrete; cite the changed clauses by short quote. "
    "Output STRICT JSON with keys: "
    "{summary: str, scope_change: str, obligation_change: str, "
    "penalty_change: str, defences_change: str, "
    "authority_changes: [{quote_left:str, quote_right:str, note:str}]}. "
    "Use empty string when a section does not apply. NEVER invent text "
    "that is not present in LEFT or RIGHT."
)


def _normalize(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    return [p.strip() for p in parts if p.strip()]


_AUTHORITY_RE = re.compile(
    r"(?:Article|Art\.?|Section|Sec\.?|§|s\.|Clause)\s*\d+[A-Za-z\-]*",
    re.IGNORECASE,
)


def _detect_authority_refs(text: str) -> set[str]:
    return {m.group(0).strip() for m in _AUTHORITY_RE.finditer(text or "")}


def _build_chunks(left: str, right: str) -> list[dict[str, Any]]:
    left_sents = _split_sentences(left)
    right_sents = _split_sentences(right)
    matcher = difflib.SequenceMatcher(a=left_sents, b=right_sents, autojunk=False)
    chunks: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        l = " ".join(left_sents[i1:i2]).strip()
        r = " ".join(right_sents[j1:j2]).strip()
        if tag == "equal":
            chunks.append({"kind": "unchanged", "left": l, "right": r})
        elif tag == "delete":
            chunks.append({"kind": "removed", "left": l, "right": ""})
        elif tag == "insert":
            chunks.append({"kind": "added", "left": "", "right": r})
        elif tag == "replace":
            chunks.append({"kind": "reworded", "left": l, "right": r})
    return chunks


def _line_diff(left: str, right: str) -> dict[str, Any]:
    """Token-level similarity scores."""
    sm = difflib.SequenceMatcher(a=left, b=right)
    return {
        "ratio": round(sm.ratio(), 3),
        "left_chars": len(left),
        "right_chars": len(right),
    }


def _impact_summary(left: str, right: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Multi-provider waterfall, deterministic fallback if all fail."""
    deltas = [c for c in chunks if c["kind"] != "unchanged"]
    if not deltas:
        return {
            "summary": "No textual differences detected between the two inputs.",
            "scope_change": "", "obligation_change": "",
            "penalty_change": "", "defences_change": "",
            "authority_changes": [], "used_model": "deterministic",
        }

    snippet = "\n\n".join(
        f"[{c['kind'].upper()}]\nLEFT: {c['left'][:400]}\nRIGHT: {c['right'][:400]}"
        for c in deltas[:18]
    )
    prompt = (
        f"LEFT text length={len(left)} chars. RIGHT text length={len(right)} chars.\n\n"
        f"DIFF CHUNKS (deltas only):\n{snippet}\n\nReturn STRICT JSON only."
    )

    from src.services.llm_waterfall import generate_json, attempts_as_dicts

    def _validate(d: dict[str, Any]) -> bool:
        return isinstance(d, dict) and bool(d.get("summary"))

    parsed, used, attempts = generate_json(
        system=_IMPACT_SYSTEM, prompt=prompt,
        validate=_validate, max_tokens=1400, temperature=0.15,
    )
    if parsed is not None:
        parsed.setdefault("authority_changes", [])
        for k in ("scope_change", "obligation_change", "penalty_change", "defences_change"):
            parsed.setdefault(k, "")
        parsed["used_model"] = used
        parsed["provider_attempts"] = attempts_as_dicts(attempts)
        return parsed

    log.warning("diff impact: all providers failed: %s", attempts_as_dicts(attempts))
    # Deterministic fallback
    added    = sum(1 for c in chunks if c["kind"] == "added")
    removed  = sum(1 for c in chunks if c["kind"] == "removed")
    reworded = sum(1 for c in chunks if c["kind"] == "reworded")
    auth_left  = _detect_authority_refs(left)
    auth_right = _detect_authority_refs(right)
    notes: list[dict[str, Any]] = []
    for a in sorted(auth_right - auth_left)[:5]:
        notes.append({"quote_left": "", "quote_right": a, "note": "Reference added"})
    for a in sorted(auth_left - auth_right)[:5]:
        notes.append({"quote_left": a, "quote_right": "", "note": "Reference removed"})
    return {
        "summary": (
            f"Deterministic fallback: {added} additions, {removed} deletions, "
            f"{reworded} rewordings. LLM impact analysis unavailable."
        ),
        "scope_change": "", "obligation_change": "",
        "penalty_change": "", "defences_change": "",
        "authority_changes": notes,
        "used_model": "deterministic",
        "provider_attempts": attempts_as_dicts(attempts),
    }


def diff_statutes(
    left: str,
    right: str,
    *,
    left_label: str = "Left",
    right_label: str = "Right",
) -> dict[str, Any]:
    left_n = _normalize(left)
    right_n = _normalize(right)
    if not left_n or not right_n:
        return {
            "error": "Both LEFT and RIGHT text are required.",
            "left_label": left_label, "right_label": right_label,
        }
    chunks = _build_chunks(left_n, right_n)
    metrics = _line_diff(left_n, right_n)
    impact = _impact_summary(left_n, right_n, chunks)
    return {
        "left_label": left_label,
        "right_label": right_label,
        "left_text": left_n,
        "right_text": right_n,
        "diff_chunks": chunks,
        "metrics": metrics,
        "impact": impact,
        "counts": {
            "unchanged": sum(1 for c in chunks if c["kind"] == "unchanged"),
            "added":     sum(1 for c in chunks if c["kind"] == "added"),
            "removed":   sum(1 for c in chunks if c["kind"] == "removed"),
            "reworded":  sum(1 for c in chunks if c["kind"] == "reworded"),
        },
    }
