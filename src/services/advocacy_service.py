"""OmniLegal Advocacy Studio service.

Generates a complete advocacy packet for a (country, topic, position) tuple:

  • Position Paper      — formal 3-paragraph statement
  • Opening Speech      — short, punchy speech with hook + 3 beats + close
  • Rebuttal Cards      — 5 reusable rebuttal cards for the opposite side
  • Leverage Cards      — specific treaty / statute violations to cite
                          against the *opposite* side or the country itself

All outputs are grounded by retrieving from the local corpus first; any
LLM-only inference is clearly marked.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.advocacy")


_PACKET_SYSTEM = """You are OmniLegal's Advocacy Architect.

You will receive:
  • a country (the speaker's perspective)
  • a topic
  • a position (FOR | AGAINST | NEUTRAL)
  • retrieved international authority
  • retrieved domestic authority for the speaker's country
  • retrieved authority that may support the OPPOSITE side
  • per-jurisdiction conflict labels for major countries

Produce a complete advocacy packet. Use the [S#] markers if they appear in
the retrieved passages — never invent citations. Where the country lacks a
local authority, draw on international rules and label clearly.

Return STRICT JSON ONLY (no markdown fences) with this schema:

{
  "position_paper": {
    "title": "...",
    "preamble": "<one paragraph>",
    "argument": "<one paragraph>",
    "conclusion": "<one paragraph>",
    "footnotes": ["<short citation chip>", "..."]
  },
  "opening_speech": {
    "hook": "<one strong opening line>",
    "beats": [
      {"heading": "...", "body": "<2-3 sentences>"},
      {"heading": "...", "body": "<2-3 sentences>"},
      {"heading": "...", "body": "<2-3 sentences>"}
    ],
    "close": "<one strong closing line>"
  },
  "rebuttal_cards": [
    {
      "claim_to_rebut": "<short opposing claim>",
      "rebuttal": "<2-3 sentences>",
      "anchor_citations": ["<source name>", "..."]
    }
  ],
  "leverage_cards": [
    {
      "headline": "<short headline framing the leverage>",
      "rule": "<exact international rule or treaty article>",
      "violation": "<specific factual or doctrinal violation>",
      "anchor_citation": "<source name>",
      "severity": "high|medium|low"
    }
  ]
}

Ensure rebuttal_cards has exactly 5 entries and leverage_cards has at least
3 entries (up to 6).  Keep the tone formal, unemotional, and persuasive.
"""


def _safe_truncate(text: str, max_chars: int = 4000) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= max_chars else text[:max_chars] + "…"


def _parse_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


_REQUIRED_KEYS = ("position_paper", "opening_speech", "rebuttal_cards", "leverage_cards")


def _validate_packet(packet: dict[str, Any] | None) -> bool:
    if not isinstance(packet, dict):
        return False
    if not all(k in packet for k in _REQUIRED_KEYS):
        return False
    pp = packet.get("position_paper")
    if not isinstance(pp, dict) or not pp.get("preamble"):
        return False
    ospeech = packet.get("opening_speech")
    if not isinstance(ospeech, dict) or not (ospeech.get("hook") or ospeech.get("beats")):
        return False
    rebuttals = packet.get("rebuttal_cards")
    if not isinstance(rebuttals, list) or len(rebuttals) == 0:
        return False
    leverage = packet.get("leverage_cards")
    if not isinstance(leverage, list) or len(leverage) == 0:
        return False
    return True


def _passages_to_text(passages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for i, p in enumerate(passages, start=1):
        excerpt = p.get("excerpt") or p.get("content") or ""
        name = p.get("source_name", "Unknown")
        parts.append(f"[S{i}] {name}: {excerpt[:500]}")
    return "\n\n".join(parts)


def _retrieve_for_country(country_key: str, topic: str) -> list[dict[str, Any]]:
    from src.services.conflict_detection import _retrieve_for_jurisdiction  # noqa: WPS437

    passages = _retrieve_for_jurisdiction(topic, country_key)
    return [
        {
            "source_name": p.citation.source_name,
            "marker": p.citation.marker,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:300],
            "content": p.content[:1200],
            "jurisdiction": p.citation.jurisdiction,
        }
        for p in passages[:6]
    ]


def _retrieve_international(topic: str) -> list[dict[str, Any]]:
    from src.services.conflict_detection import _retrieve_international  # noqa: WPS437

    passages = _retrieve_international(topic)
    return [
        {
            "source_name": p.citation.source_name,
            "marker": p.citation.marker,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:300],
            "content": p.content[:1200],
            "jurisdiction": p.citation.jurisdiction,
        }
        for p in passages[:6]
    ]


def _opposite_side_evidence(topic: str, country_key: str, position: str) -> list[dict[str, Any]]:
    """Retrieve the strongest authority the opposing side might use."""
    from src.services.retrieval_qa import retrieve_passages

    rev_position = {
        "FOR": "AGAINST",
        "AGAINST": "FOR",
        "NEUTRAL": "AGAINST",
    }.get(position.upper(), "AGAINST")
    twist = {
        "FOR":     "arguments against",
        "AGAINST": "arguments in favour of",
        "NEUTRAL": "limits, exceptions, or counterarguments to",
    }[rev_position]
    query = f"{twist} {topic}"
    try:
        passages = retrieve_passages(query, k=4, comparative=True)
    except Exception:
        return []
    return [
        {
            "source_name": p.citation.source_name,
            "marker": p.citation.marker,
            "page": p.citation.page,
            "excerpt": p.citation.excerpt or p.content[:300],
            "content": p.content[:900],
            "jurisdiction": p.citation.jurisdiction,
        }
        for p in passages[:4]
    ]


def _build_user_prompt(
    country_name: str,
    country_key: str,
    topic: str,
    position: str,
    international: list[dict[str, Any]],
    domestic: list[dict[str, Any]],
    opposite: list[dict[str, Any]],
    conflict_summary: dict[str, Any] | None,
) -> str:
    parts = [
        f"COUNTRY (speaker perspective): {country_name}",
        f"TOPIC: {topic}",
        f"POSITION: {position.upper()}",
        "",
        "INTERNATIONAL AUTHORITY:",
        _passages_to_text(international) or "(no international passages retrieved)",
        "",
        f"DOMESTIC AUTHORITY ({country_name}):",
        _passages_to_text(domestic) or "(no domestic passages retrieved)",
        "",
        "OPPOSING-SIDE AUTHORITY (use for rebuttal_cards & leverage_cards):",
        _passages_to_text(opposite) or "(no opposing passages retrieved)",
        "",
    ]
    if conflict_summary and conflict_summary.get("per_jurisdiction"):
        parts.append("CROSS-JURISDICTION CONFLICT SUMMARY:")
        for entry in conflict_summary["per_jurisdiction"]:
            parts.append(
                f"  • {entry.get('jurisdiction')}: {entry.get('label')} "
                f"({entry.get('confidence', 0):.2f}) — {entry.get('status', '')}"
            )
        parts.append("")
    parts.append("Output STRICT JSON only.")
    return _safe_truncate("\n".join(parts), 12000)


def generate_advocacy_packet(
    country_key: str,
    country_name: str,
    topic: str,
    position: str,
    *,
    include_conflict: bool = True,
) -> dict[str, Any]:
    """Generate the full Advocacy Studio packet."""
    international = _retrieve_international(topic)
    domestic = _retrieve_for_country(country_key, topic)
    opposite = _opposite_side_evidence(topic, country_key, position)
    conflict_summary = None
    if include_conflict:
        try:
            from src.services.conflict_detection import analyze_multi_jurisdiction_conflict
            conflict_summary = analyze_multi_jurisdiction_conflict(topic)
        except Exception as exc:
            log.warning("conflict snapshot failed: %s", exc)
            conflict_summary = None

    prompt = _build_user_prompt(
        country_name, country_key, topic, position,
        international, domestic, opposite, conflict_summary,
    )

    # Try multiple providers; validate the schema; and as final fallback use
    # Gemini's direct API (separate key, bypasses any Emergent universal-key
    # budget cap).
    attempts: list[tuple[str, str]] = []  # (provider, model_id_used)
    parsed: dict[str, Any] | None = None
    last_error: str | None = None
    last_text: str = ""

    def _try_emergent(provider: str, model: str) -> tuple[str, str | None, str | None]:
        from src.services.emergent_llm import generate_text

        res = generate_text(
            system=_PACKET_SYSTEM, prompt=prompt,
            provider=provider, model=model, timeout_seconds=70.0,
        )
        return res.text or "", res.error, res.model or model

    def _try_gemini_direct() -> tuple[str, str | None, str]:
        from src.services.gemini_client import generate_gemini_content

        res = generate_gemini_content(
            system=_PACKET_SYSTEM, prompt=prompt,
            temperature=0.25, max_output_tokens=4500,
        )
        return res.text or "", res.error, res.model or "gemini-2.5-flash"

    plan = [
        ("emergent_anthropic", "claude-sonnet-4-5-20250929"),
        ("emergent_google",    "gemini-2.5-flash"),
        ("gemini_direct",      "gemini-2.5-flash"),
        ("gemini_direct_lite", "gemini-2.5-flash-lite"),
        ("groq_llama",         "llama-3.3-70b-versatile"),
    ]
    for provider_tag, model in plan:
        try:
            if provider_tag == "emergent_anthropic":
                text, err, used = _try_emergent("anthropic", model)
            elif provider_tag == "emergent_google":
                text, err, used = _try_emergent("google", model)
            elif provider_tag == "gemini_direct_lite":
                from src.services.gemini_client import generate_gemini_content as _g
                res = _g(system=_PACKET_SYSTEM, prompt=prompt,
                         model="gemini-2.5-flash-lite",
                         temperature=0.2, max_output_tokens=4500)
                text, err, used = res.text or "", res.error, "gemini-2.5-flash-lite"
            elif provider_tag == "groq_llama":
                from src.services.groq_client import generate_groq_chat
                res = generate_groq_chat(
                    messages=[
                        {"role": "system", "content": _PACKET_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4000,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )
                text, err, used = res.text or "", res.error, res.model or model
            else:
                text, err, used = _try_gemini_direct()
        except Exception as exc:  # noqa: BLE001
            text, err, used = "", f"{type(exc).__name__}: {exc}", model
        attempts.append((provider_tag, used))
        last_text = text
        last_error = err
        candidate = _parse_json(text)
        if _validate_packet(candidate):
            parsed = candidate
            break

    if not parsed:
        return {
            "country": country_name,
            "country_key": country_key,
            "topic": topic,
            "position": position,
            "error": (
                "Advocacy generator could not produce a valid 4-section packet "
                f"after {len(attempts)} attempts. Last error: {last_error or 'malformed JSON output'}."
            ),
            "international_sources": international,
            "domestic_sources": domestic,
            "opposite_sources": opposite,
            "conflict_summary": conflict_summary,
            "used_model": "/".join(attempts[-1]) if attempts else "unknown",
            "attempts": [f"{p}/{m}" for (p, m) in attempts],
            "raw_excerpt": last_text[:600],
        }

    # Normalize / safety bound the cards
    rebuttals = parsed.get("rebuttal_cards") or []
    if isinstance(rebuttals, list):
        parsed["rebuttal_cards"] = rebuttals[:5]
    leverage = parsed.get("leverage_cards") or []
    if isinstance(leverage, list):
        parsed["leverage_cards"] = leverage[:6]

    return {
        "country": country_name,
        "country_key": country_key,
        "topic": topic,
        "position": position,
        "packet": parsed,
        "international_sources": international,
        "domestic_sources": domestic,
        "opposite_sources": opposite,
        "conflict_summary": conflict_summary,
        "used_model": "/".join(attempts[-1]) if attempts else "unknown",
        "attempts": [f"{p}/{m}" for (p, m) in attempts],
    }
