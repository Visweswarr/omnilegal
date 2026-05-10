"""Longitudinal Comparative Analysis — Pillar 20.

Given a legal query and a set of jurisdictions, this service runs the full
IRAC + heat-map pipeline for each time period (e.g. Pre-1945, 1945-1970,
1970-2000, 2000-Present) and returns a structured timeline showing how each
jurisdiction's recognition of the concept evolved.

The temporal constraint is injected into the IRAC prompt so the LLM:
  - Only cites cases, statutes, treaties adopted before period.year_end
  - Describes the legal landscape AS IT EXISTED in that period
  - Notes developments that occurred WITHIN the period

Corpus passages with `year` metadata are post-filtered to the period window.
When no period-relevant corpus passages exist, the LLM relies on its general
legal-historical knowledge for that era.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

log = logging.getLogger("omnilegal.longitudinal")

# ── Default period catalogue ───────────────────────────────────────────────

DEFAULT_PERIODS: list[dict[str, Any]] = [
    {"label": "Pre-1945",     "year_start": None, "year_end": 1945},
    {"label": "1945–1970",    "year_start": 1945, "year_end": 1970},
    {"label": "1970–2000",    "year_start": 1970, "year_end": 2000},
    {"label": "2000–Present", "year_start": 2000, "year_end": None},
]

PERIOD_PRESETS: dict[str, list[dict[str, Any]]] = {
    "century": [
        {"label": "Pre-1945",     "year_start": None, "year_end": 1945},
        {"label": "1945–1970",    "year_start": 1945, "year_end": 1970},
        {"label": "1970–2000",    "year_start": 1970, "year_end": 2000},
        {"label": "2000–Present", "year_start": 2000, "year_end": None},
    ],
    "postwar": [
        {"label": "1945–1960",  "year_start": 1945, "year_end": 1960},
        {"label": "1960–1980",  "year_start": 1960, "year_end": 1980},
        {"label": "1980–2000",  "year_start": 1980, "year_end": 2000},
        {"label": "2000–2015",  "year_start": 2000, "year_end": 2015},
        {"label": "2015–Now",   "year_start": 2015, "year_end": None},
    ],
    "modern": [
        {"label": "1990–2000",  "year_start": 1990, "year_end": 2000},
        {"label": "2000–2010",  "year_start": 2000, "year_end": 2010},
        {"label": "2010–2020",  "year_start": 2010, "year_end": 2020},
        {"label": "2020–Now",   "year_start": 2020, "year_end": None},
    ],
}


# ── Year-filtered passage retrieval ───────────────────────────────────────

def _retrieve_period_passages(
    query: str,
    jur_key: str,
    year_start: int | None,
    year_end: int | None,
) -> list[Any]:
    """Retrieve passages for a jurisdiction, post-filtered by year range."""
    try:
        from src.services.conflict_detection import (
            _retrieve_for_jurisdiction,
            _retrieve_international,
        )
        # Get domestic + global passages
        if jur_key in ("international", "intl"):
            raw = _retrieve_international(query)
        else:
            raw = _retrieve_for_jurisdiction(query, jur_key)
            # Also add global passages for abstract concepts
            try:
                intl = _retrieve_international(query)
                seen = {
                    getattr(getattr(p, "citation", None), "source_name", "")
                    for p in raw
                }
                for p in intl:
                    sn = getattr(getattr(p, "citation", None), "source_name", "")
                    if sn not in seen:
                        raw.append(p)
                        seen.add(sn)
            except Exception:
                pass
        return _year_filter(raw, year_start, year_end)
    except Exception as exc:
        log.warning("period retrieval failed for %s: %s", jur_key, exc)
        return []


def _year_filter(passages: list[Any], year_start: int | None, year_end: int | None) -> list[Any]:
    """Keep passages whose year metadata falls within [year_start, year_end]."""
    if year_start is None and year_end is None:
        return passages
    kept, no_year = [], []
    for p in passages:
        # Try to get year from metadata_json stored on the passage
        year = None
        try:
            meta = getattr(p, "_raw_metadata", None) or {}
            year = meta.get("year")
        except Exception:
            pass
        if year is None:
            # Try citation.article as a fallback (some store year in article field)
            try:
                art = getattr(getattr(p, "citation", None), "article", "") or ""
                nums = [int(n) for n in re.findall(r"(1[89]\d{2}|20[012]\d)", art)]
                if nums:
                    year = min(nums)
            except Exception:
                pass
        if year is None:
            no_year.append(p)
            continue
        try:
            y = int(year)
            in_range = (year_start is None or y >= year_start) and \
                       (year_end is None or y <= year_end)
            if in_range:
                kept.append(p)
        except (ValueError, TypeError):
            no_year.append(p)
    # Prefer year-matched passages; append no-year ones as fallback
    return kept + no_year[:2]


# ── Period-constrained IRAC ────────────────────────────────────────────────

def _period_irac_prompt(
    jurisdiction: str,
    query: str,
    period_label: str,
    year_start: int | None,
    year_end: int | None,
    passages_text: str,
) -> str:
    """Build a period-constrained user prompt for IRAC generation."""
    start_str = str(year_start) if year_start else "the earliest records"
    end_str   = str(year_end)   if year_end   else "the present"
    return (
        f"Jurisdiction: {jurisdiction}\n"
        f"Time period: {period_label} ({start_str} – {end_str})\n\n"
        f"TEMPORAL CONSTRAINT: Analyse {jurisdiction}'s position on the following "
        f"query AS IT EXISTED specifically during {period_label}. "
        f"{'Only cite cases, statutes, and treaties adopted or decided BEFORE ' + str(year_end) + '.' if year_end else 'Include the most recent developments up to the present.'} "
        f"Note key legal developments that occurred WITHIN this period.\n\n"
        f"Research question:\n\"\"\"{query}\"\"\"\n\n"
        + (
            f"Retrieved passages from this period:\n\"\"\"{passages_text[:3000]}\"\"\"\n\n"
            if passages_text.strip()
            else
            "No corpus passages retrieved for this period. Use your legal-historical "
            f"knowledge of {jurisdiction}'s position during {period_label}.\n\n"
        )
        + "Return JSON only."
    )


def _run_period_irac(
    query: str,
    jur_key: str,
    period: dict[str, Any],
    cross_citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """IRAC for one jurisdiction × one period (runs in a thread)."""
    from src.services.comparative_service import (
        JURISDICTION_LABELS, _is_relevant,
    )
    from src.services.cross_jurisdiction import (
        _IRAC_SYSTEM,
        _parse_json,
        _safe_truncate,
    )

    jur_label = JURISDICTION_LABELS.get(jur_key.lower(), jur_key.capitalize())
    period_label = period["label"]
    year_start   = period.get("year_start")
    year_end     = period.get("year_end")

    # Retrieve & filter passages
    raw_passages = _retrieve_period_passages(query, jur_key, year_start, year_end)
    relevant = [
        p for p in raw_passages
        if _is_relevant(getattr(p, "content", "") or "", query)
    ]
    if relevant:
        parts = []
        for i, p in enumerate(relevant[:4], 1):
            src = getattr(getattr(p, "citation", None), "source_name", "Unknown")
            jur = getattr(getattr(p, "citation", None), "jurisdiction", "")
            content = getattr(p, "content", "")[:600]
            parts.append(f"[S{i}] {src} [{jur or 'intl'}]:\n{content}")
        passages_text = "\n\n".join(parts)
    else:
        passages_text = ""

    try:
        from src.services.emergent_llm import generate_with_fallback
        user_prompt = _period_irac_prompt(
            jur_label, query, period_label, year_start, year_end, passages_text
        )
        result = generate_with_fallback(
            system=_IRAC_SYSTEM,
            prompt=user_prompt,
            timeout_seconds=35.0,
        )
        parsed = _parse_json(result.text) if result.text else None
        if not parsed:
            raise ValueError(result.error or "non-JSON response")
        parsed["jurisdiction"]  = jur_label
        parsed["period"]        = period_label
        parsed["used_model"]    = f"{result.provider}/{result.model}"
        parsed["has_source_data"] = bool(relevant)
        parsed["passages"] = [
            {
                "source_name": getattr(getattr(p, "citation", None), "source_name", "Unknown"),
                "jurisdiction": getattr(getattr(p, "citation", None), "jurisdiction", ""),
                "excerpt": (getattr(p, "content", "")[:200] if hasattr(p, "content") else ""),
            }
            for p in relevant[:3]
        ]
    except Exception as exc:
        log.warning("period IRAC failed for %s / %s: %s", jur_label, period_label, exc)
        parsed = {
            "jurisdiction": jur_label, "period": period_label,
            "issue": query, "rule": "", "application": "",
            "conclusion": "indeterminate — service error",
            "conditions_if_any": "", "confidence": 0.0,
            "key_authorities": [], "error": str(exc),
            "has_source_data": False, "passages": [],
        }
    return parsed


# ── Top-level entry point ─────────────────────────────────────────────────


def run_longitudinal(
    query: str,
    jurisdictions: list[str] | None = None,
    periods: list[dict[str, Any]] | None = None,
    preset: str | None = None,
) -> dict[str, Any]:
    """Run parallel IRAC + heat-map for every jurisdiction × period combination.

    Returns a timeline of {period_label, irac_blocks, heat_map, trend} dicts.
    """
    from src.services.comparative_service import _DEFAULT_JURISDICTIONS
    from src.services.citation_graph import graph_stats as _gs
    from src.services.cross_jurisdiction import generate_heat_map, markdown_comparison_table

    jur_keys = [j.lower().strip() for j in (jurisdictions or _DEFAULT_JURISDICTIONS)]
    if preset and preset in PERIOD_PRESETS:
        periods_to_use = PERIOD_PRESETS[preset]
    else:
        periods_to_use = periods or DEFAULT_PERIODS

    log.info("longitudinal: %d jurisdictions × %d periods", len(jur_keys), len(periods_to_use))

    # No cross-citation graph context for longitudinal (keep prompts clean)
    cross_citations: list[dict[str, Any]] = []

    # ── Per-period × per-jurisdiction concurrent IRAC ─────────────────────
    timeline: list[dict[str, Any]] = []

    for period in periods_to_use:
        # Fan out IRAC for all jurisdictions in this period
        irac_blocks: list[dict[str, Any]] = [{}] * len(jur_keys)
        with ThreadPoolExecutor(max_workers=min(len(jur_keys), 4)) as pool:
            futures = {
                pool.submit(_run_period_irac, query, jk, period, cross_citations): i
                for i, jk in enumerate(jur_keys)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    irac_blocks[idx] = future.result()
                except Exception as exc:
                    irac_blocks[idx] = {
                        "jurisdiction": jur_keys[idx], "period": period["label"],
                        "conclusion": "indeterminate — error", "error": str(exc),
                        "key_authorities": [], "has_source_data": False, "passages": [],
                    }

        # Heat map for this period
        try:
            heat_map = generate_heat_map(
                f"{query} [period: {period['label']}]", irac_blocks
            )
        except Exception as exc:
            log.error("heat_map generation failed for period %s: %s", period["label"], exc)
            heat_map = {"dimensions": [], "cells": {}, "summary_verdict": ""}

        timeline.append({
            "period":      period["label"],
            "year_start":  period.get("year_start"),
            "year_end":    period.get("year_end"),
            "irac_blocks": irac_blocks,
            "heat_map":    heat_map,
        })

    # ── Compute trend indicators ──────────────────────────────────────────
    _add_trend_deltas(timeline)

    # Graph stats for UI
    graph_stats: dict[str, Any] = {}
    try:
        graph_stats = _gs()
    except Exception:
        pass

    return {
        "query":                   query,
        "jurisdictions_requested": jur_keys,
        "periods_used":            [p["label"] for p in periods_to_use],
        "timeline":                timeline,
        "graph_stats":             graph_stats,
    }


# ── Trend delta computation ────────────────────────────────────────────────

_LEVEL_ORDER = {"full": 3, "partial": 2, "none": 1, "indeterminate": 0}


def _add_trend_deltas(timeline: list[dict[str, Any]]) -> None:
    """Mutate timeline in place: add `trend` dict showing change per jurisdiction."""
    for i, period in enumerate(timeline):
        if i == 0:
            period["trend"] = {}
            continue
        prev = timeline[i - 1]
        deltas: dict[str, dict[str, str]] = {}
        for jur_block in period.get("irac_blocks", []):
            jur = jur_block.get("jurisdiction", "")
            curr_cell = _get_cells(period, jur)
            prev_cell = _get_cells(prev, jur)
            if not curr_cell and not prev_cell:
                continue
            dims_changed = {}
            for dim in set(list(curr_cell.keys()) + list(prev_cell.keys())):
                cv = _LEVEL_ORDER.get(curr_cell.get(dim, "indeterminate"), 0)
                pv = _LEVEL_ORDER.get(prev_cell.get(dim, "indeterminate"), 0)
                if cv > pv:
                    dims_changed[dim] = "up"
                elif cv < pv:
                    dims_changed[dim] = "down"
                else:
                    dims_changed[dim] = "stable"
            deltas[jur] = dims_changed
        period["trend"] = deltas


def _get_cells(period_data: dict[str, Any], jurisdiction: str) -> dict[str, str]:
    """Extract heat map cells for a specific jurisdiction from a period."""
    return (period_data.get("heat_map") or {}).get("cells", {}).get(jurisdiction, {})
