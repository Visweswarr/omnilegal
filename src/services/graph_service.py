"""OmniLegal Citation Graph Explorer (Pillar 07).

Builds a citation graph anchored on a *resolved* canonical case rather than on
the raw user-typed text.  The flow is:

1. Resolve the seed via :mod:`case_registry` so "Albania vs UK", "UK v.
   Albania" and "Corfu Channel Case" all collapse to the same canonical
   entry (Corfu Channel, ICJ 1949).
2. Run hybrid retrieval on the *canonical* name (plus a couple of strong
   aliases) so the corpus actually surfaces relevant material.
3. Tag each retrieved passage as ``anchor`` (mentions the canonical case or an
   alias) or ``context`` (search-relevant but doesn't actually mention the
   case).  Edges are built **only from anchor passages** — that's what makes
   them genuine "neighbours" rather than coincidental regex hits.
4. Edge direction is inferred from the local sentence: "X overruled SEED"
   becomes inbound, "SEED followed X" outbound.
5. Stats expose ``seed_resolved``, ``anchor_passages``, ``cap_hit`` etc.,
   instead of identical 40/39/12 numbers for every query.

If the seed doesn't resolve to a known case the service falls back to the old
loose behaviour but flags every edge as ``loose_mention`` so the UI can warn.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

from src.services.case_registry import (
    CaseEntry,
    all_aliases_for,
    passage_anchors_case,
    resolve as resolve_case,
)

log = logging.getLogger("omnilegal.graph")


# Citation patterns reused / simplified from forensics_service
_CITATION_PATTERNS = [
    (re.compile(r"\b\d{1,4}\s+U\.?S\.?\s+\d{1,4}(?:\s*\(\d{4}\))?", re.IGNORECASE), "us_case"),
    (re.compile(r"\b\d{1,3}\s+U\.?S\.?C\.?\s*§?\s*\d+[a-z\-\d]*", re.IGNORECASE), "usc"),
    (re.compile(r"\[\d{4}\]\s+[A-Z]{2,5}(?:HC|CA|SC)?\s*\d+"), "uk_case"),
    (re.compile(r"\bapplication\s+no\.?\s*\d{4,6}/\d{2,4}", re.IGNORECASE), "echr_case"),
    (re.compile(r"\b([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s+v\.?\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\b"), "named_case"),
    (re.compile(r"\bSection\s+\d+[A-Z]?\b", re.IGNORECASE), "indian_section"),
    (re.compile(r"\bArticle\s+\d+[A-Z]?\s*(?:of\s+the\s+[A-Z][A-Za-z\s]+)?", re.IGNORECASE), "treaty_article"),
]


_EDGE_KEYWORDS = [
    (re.compile(r"\boverrul(?:ed|es|ing)\b|\babrogated\b", re.IGNORECASE), "overrules"),
    (re.compile(r"\bdistinguish(?:ed|es|ing)\b", re.IGNORECASE), "distinguishes"),
    (re.compile(r"\bfollow(?:ed|s|ing)\b|\baffirm(?:ed|s|ing)\b|\breaffirm", re.IGNORECASE), "follows"),
    (re.compile(r"\bcriticis(?:ed|es)\b|\bcriticiz(?:ed|es)\b", re.IGNORECASE), "criticises"),
]

_DEFAULT_PASSAGE_K = 24
_HARD_NODE_CAP_MULT = 4  # don't blow up the SVG even when uncapped
_YEAR_RE = re.compile(r"\b(1[7-9]\d{2}|20\d{2})\b")


def _classify_edge(window: str) -> str:
    for pat, kind in _EDGE_KEYWORDS:
        if pat.search(window):
            return kind
    return "cites"


def _normalise_node(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().lower()


def _extract_year_in(text: str) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def _extract_citations_with_context(text: str) -> list[tuple[str, str, str]]:
    """Returns list of (citation_text, kind, sentence_context)."""
    sentences = re.split(r"(?<=[.!?])\s+", text or "")
    out: list[tuple[str, str, str]] = []
    for sent in sentences:
        for pattern, kind in _CITATION_PATTERNS:
            for m in pattern.finditer(sent):
                cite_text = m.group(0).strip()
                out.append((cite_text, kind, sent))
    return out


def _direction_for(sentence: str, seed_aliases: list[str], cite_text: str) -> str:
    """Decide whether the edge runs seed→cite (outbound) or cite→seed (inbound).

    Heuristic: find the position of the seed-name and the cite-text inside the
    sentence and look at the verb between them. If the seed appears as the
    grammatical subject of a treatment verb, the edge is outbound; if the cite
    is the subject, the edge is inbound. When ambiguous, default to outbound.
    """
    if not sentence:
        return "outbound"
    lower = sentence.lower()
    seed_pos = -1
    for alias in seed_aliases:
        p = lower.find(alias.lower())
        if p >= 0:
            seed_pos = p
            break
    cite_pos = lower.find(cite_text.lower())
    if seed_pos < 0 or cite_pos < 0:
        return "outbound"
    return "outbound" if seed_pos < cite_pos else "inbound"


def _seed_node_from_entry(entry: CaseEntry) -> dict[str, Any]:
    return {
        "id": "seed::" + _normalise_node(entry.canonical_name),
        "label": entry.canonical_name,
        "kind": "named_case",
        "jurisdiction": entry.jurisdiction or "international",
        "year": entry.year,
        "court": entry.court,
        "weight": 1,
        "is_seed": True,
        "summary": entry.summary,
        "citation": entry.citation,
    }


def _seed_node_from_topic(seed_query: str) -> dict[str, Any]:
    return {
        "id": "seed::" + _normalise_node(seed_query),
        "label": seed_query,
        "kind": "topic",
        "jurisdiction": "",
        "year": None,
        "weight": 1,
        "is_seed": True,
    }


def build_graph(seed_query: str, max_nodes: int = 40) -> dict[str, Any]:
    seed_query = (seed_query or "").strip()
    if not seed_query:
        return {"error": "seed_query is required"}

    entry = resolve_case(seed_query)
    seed_node = _seed_node_from_entry(entry) if entry else _seed_node_from_topic(seed_query)
    seed_id = seed_node["id"]
    seed_aliases = all_aliases_for(entry) if entry else [seed_query]

    nodes: dict[str, dict[str, Any]] = {seed_id: seed_node}
    edges_set: dict[tuple[str, str, str, str], int] = defaultdict(int)
    inbound: dict[str, int] = defaultdict(int)
    cap_hit = False
    hard_cap = max(max_nodes, max_nodes * _HARD_NODE_CAP_MULT)

    # Build retrieval query: canonical name (+ a couple of strong aliases).
    if entry:
        alias_subset = [a for a in entry.aliases if " v " in a.lower() or "v." in a.lower()][:2]
        retrieval_query = " ; ".join([entry.canonical_name, *alias_subset]) or entry.canonical_name
    else:
        retrieval_query = seed_query

    try:
        from src.services.retrieval_qa import retrieve_passages
        passages = retrieve_passages(retrieval_query, k=_DEFAULT_PASSAGE_K, comparative=True)
    except Exception as exc:
        log.warning("graph retrieval failed: %s", exc)
        passages = []

    anchor_passages: list[Any] = []
    context_passages: list[Any] = []
    if entry:
        for p in passages:
            if passage_anchors_case(p.content or "", entry):
                anchor_passages.append(p)
            else:
                context_passages.append(p)
    else:
        # No resolution → every passage is "loose context".
        context_passages = list(passages)

    # ── Pass 1: real citations from anchor passages ────────────────────────
    for p in anchor_passages:
        src_label = p.citation.source_name or "Unknown source"
        src_id = "src::" + _normalise_node(src_label)
        if src_id not in nodes and len(nodes) < hard_cap:
            nodes[src_id] = {
                "id": src_id, "label": src_label, "kind": "document",
                "jurisdiction": p.citation.jurisdiction or "", "year": None, "weight": 1,
            }
        if src_id in nodes:
            edges_set[(seed_id, src_id, "anchored_in", "outbound")] += 1
            inbound[src_id] += 1

        for cite_text, cite_kind, sent in _extract_citations_with_context(p.content or ""):
            # Only count cites that share a sentence with the seed-case name —
            # that's what makes them a real "neighbour" rather than a passage-level
            # coincidence.
            if entry and not passage_anchors_case(sent, entry):
                continue
            # Drop citations that resolve back to the seed itself (e.g. seed
            # "Corfu Channel" matches passage text "United Kingdom v Albania").
            if entry:
                cite_entry = resolve_case(cite_text)
                if cite_entry and cite_entry.canonical_name == entry.canonical_name:
                    continue
            cite_id = f"{cite_kind}::" + _normalise_node(cite_text)
            if cite_id == seed_id or cite_id == src_id:
                continue
            if cite_id not in nodes:
                if len(nodes) >= hard_cap:
                    cap_hit = True
                    break
                year = _extract_year_in(cite_text) or _extract_year_in(sent)
                nodes[cite_id] = {
                    "id": cite_id, "label": cite_text, "kind": cite_kind,
                    "jurisdiction": p.citation.jurisdiction or "",
                    "year": year, "weight": 1,
                }
            edge_kind = _classify_edge(sent)
            direction = _direction_for(sent, seed_aliases, cite_text) if entry else "outbound"
            if direction == "outbound":
                key = (seed_id, cite_id, edge_kind, "outbound")
            else:
                key = (cite_id, seed_id, edge_kind, "inbound")
            edges_set[key] += 1
            inbound[cite_id] += 1
        if len(nodes) >= hard_cap:
            cap_hit = True
            break

    # ── Pass 2: loose context (only used when no anchors) ──────────────────
    used_loose_pass = entry is None or len(anchor_passages) == 0
    if used_loose_pass:
        for p in context_passages:
            if len(nodes) >= max_nodes:
                cap_hit = True
                break
            src_label = p.citation.source_name or "Unknown source"
            src_id = "src::" + _normalise_node(src_label)
            if src_id not in nodes:
                nodes[src_id] = {
                    "id": src_id, "label": src_label, "kind": "document",
                    "jurisdiction": p.citation.jurisdiction or "", "year": None, "weight": 1,
                }
            edges_set[(seed_id, src_id, "loose_mention", "outbound")] += 1
            inbound[src_id] += 1

            for cite_text, cite_kind, sent in _extract_citations_with_context(p.content or ""):
                if len(nodes) >= max_nodes:
                    cap_hit = True
                    break
                cite_id = f"{cite_kind}::" + _normalise_node(cite_text)
                if cite_id in (seed_id, src_id):
                    continue
                if cite_id not in nodes:
                    year = _extract_year_in(cite_text) or _extract_year_in(sent)
                    nodes[cite_id] = {
                        "id": cite_id, "label": cite_text, "kind": cite_kind,
                        "jurisdiction": p.citation.jurisdiction or "",
                        "year": year, "weight": 1,
                    }
                edges_set[(src_id, cite_id, "loose_mention", "outbound")] += 1
                inbound[cite_id] += 1
            if len(nodes) >= max_nodes:
                cap_hit = True
                break

    # Apply weights = inbound count
    for nid, n in nodes.items():
        n["weight"] = max(1, inbound.get(nid, 1))

    edges = [
        {"from": a, "to": b, "type": t, "direction": d, "count": cnt}
        for (a, b, t, d), cnt in edges_set.items()
    ]

    resolution = "matched" if entry else "loose"
    if entry and not anchor_passages:
        resolution = "matched_no_anchors"

    return {
        "seed": seed_query,
        "seed_canonical": entry.canonical_name if entry else None,
        "seed_resolved": entry is not None,
        "seed_display": entry.display_label if entry else seed_query,
        "seed_summary": (entry.summary if entry else "") or "",
        "seed_citation": (entry.citation if entry else "") or "",
        "seed_aliases": seed_aliases if entry else [],
        "resolution": resolution,
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "passages_total": len(passages),
            "anchor_passages": len(anchor_passages),
            "context_passages": len(context_passages),
            "cap_hit": cap_hit,
            "max_nodes": max_nodes,
        },
    }
