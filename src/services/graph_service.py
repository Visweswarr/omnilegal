"""OmniLegal Citation Graph Explorer (Pillar 07).

Builds a force-directed citation graph by extracting citation patterns
from retrieved passages, plus optional CourtListener / Indian Kanoon
"cited-by" hops where available.

Edge type heuristics: keywords near a citation in the surrounding sentence
classify the edge as overrules / follows / distinguishes / cites.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any

log = logging.getLogger("omnilegal.graph")


# Citation patterns reused / simplified from forensics_service
_CITATION_PATTERNS = [
    # US citation: 50 U.S. 75 (1957)
    (re.compile(r"\b\d{1,4}\s+U\.?S\.?\s+\d{1,4}(?:\s*\(\d{4}\))?", re.IGNORECASE), "us_case"),
    # USC section
    (re.compile(r"\b\d{1,3}\s+U\.?S\.?C\.?\s*§?\s*\d+[a-z\-\d]*", re.IGNORECASE), "usc"),
    # UK / EHRR style
    (re.compile(r"\[\d{4}\]\s+[A-Z]{2,5}(?:HC|CA|SC)?\s*\d+"), "uk_case"),
    # ECHR application number
    (re.compile(r"\bapplication\s+no\.?\s*\d{4,6}/\d{2,4}", re.IGNORECASE), "echr_case"),
    # Named case: Smith v. Jones
    (re.compile(r"\b([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\s+v\.?\s+([A-Z][A-Za-z'\-]+(?:\s+[A-Z][A-Za-z'\-]+){0,3})\b"), "named_case"),
    # Indian section
    (re.compile(r"\bSection\s+\d+[A-Z]?\b", re.IGNORECASE), "indian_section"),
    # Treaty article
    (re.compile(r"\bArticle\s+\d+[A-Z]?\s*(?:of\s+the\s+[A-Z][A-Za-z\s]+)?", re.IGNORECASE), "treaty_article"),
]


_EDGE_KEYWORDS = [
    (re.compile(r"\boverrul(?:ed|es|ing)\b|\babrogated\b", re.IGNORECASE), "overrules"),
    (re.compile(r"\bdistinguish(?:ed|es|ing)\b", re.IGNORECASE), "distinguishes"),
    (re.compile(r"\bfollow(?:ed|s|ing)\b|\baffirm(?:ed|s|ing)\b|\breaffirm", re.IGNORECASE), "follows"),
    (re.compile(r"\bcriticis(?:ed|es)\b|\bcriticiz(?:ed|es)\b", re.IGNORECASE), "criticises"),
]


def _classify_edge(window: str) -> str:
    for pat, kind in _EDGE_KEYWORDS:
        if pat.search(window):
            return kind
    return "cites"


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


def _normalise_node(label: str) -> str:
    return re.sub(r"\s+", " ", label).strip().lower()


def build_graph(seed_query: str, max_nodes: int = 40) -> dict[str, Any]:
    seed_query = (seed_query or "").strip()
    if not seed_query:
        return {"error": "seed_query is required"}

    nodes: dict[str, dict[str, Any]] = {}
    edges_set: dict[tuple[str, str, str], int] = defaultdict(int)
    inbound: dict[str, int] = defaultdict(int)

    # 1) Seed node
    seed_id = "seed::" + _normalise_node(seed_query)
    nodes[seed_id] = {
        "id": seed_id, "label": seed_query, "kind": "topic",
        "jurisdiction": "", "year": None, "weight": 1, "is_seed": True,
    }

    # 2) Retrieve passages (corpus first; live registries as fallback or supplement)
    try:
        from src.services.retrieval_qa import retrieve_passages
        passages = retrieve_passages(seed_query, k=12, comparative=True)
    except Exception as exc:
        log.warning("graph retrieval failed: %s", exc)
        passages = []

    for p in passages:
        src_label = p.citation.source_name or "Unknown source"
        src_id = "src::" + _normalise_node(src_label)
        if src_id not in nodes:
            nodes[src_id] = {
                "id": src_id, "label": src_label, "kind": "document",
                "jurisdiction": p.citation.jurisdiction or "", "year": None, "weight": 1,
            }
        # Edge seed -> source
        edge_key = (seed_id, src_id, "retrieved")
        edges_set[edge_key] += 1
        inbound[src_id] += 1

        # Extract citations inside the passage content
        for cite_text, cite_kind, sent in _extract_citations_with_context(p.content or ""):
            cite_id = f"{cite_kind}::" + _normalise_node(cite_text)
            if cite_id == src_id:
                continue
            if cite_id not in nodes:
                year = _extract_year_in(cite_text) or _extract_year_in(sent)
                nodes[cite_id] = {
                    "id": cite_id, "label": cite_text, "kind": cite_kind,
                    "jurisdiction": p.citation.jurisdiction or "",
                    "year": year, "weight": 1,
                }
            edge_kind = _classify_edge(sent)
            ek = (src_id, cite_id, edge_kind)
            edges_set[ek] += 1
            inbound[cite_id] += 1
            if len(nodes) >= max_nodes:
                break
        if len(nodes) >= max_nodes:
            break

    # 3) Live-registry fallback / supplement so the graph always has nodes
    if len(nodes) < max(8, max_nodes // 4):
        try:
            from src.services.live_authority_service import search_live
            live = search_live(seed_query, ["indian_kanoon", "courtlistener", "hudoc", "eurlex"], 6)
            for hit in (live.get("results") or []):
                if len(nodes) >= max_nodes:
                    break
                title = (hit.get("title") or "").strip()
                if not title:
                    continue
                src_id = "live::" + _normalise_node(title)
                if src_id in nodes:
                    continue
                jur = hit.get("jurisdiction") or ""
                year = _extract_year_in(hit.get("date") or "") or _extract_year_in(title)
                nodes[src_id] = {
                    "id": src_id, "label": title[:140], "kind": "live_case",
                    "jurisdiction": jur, "year": year, "weight": 1,
                    "url": hit.get("url", ""), "live_source": hit.get("source", ""),
                }
                ek = (seed_id, src_id, "registry_match")
                edges_set[ek] += 1
                inbound[src_id] += 1

                # Extract embedded citations from snippet
                snippet = hit.get("snippet") or ""
                for cite_text, cite_kind, sent in _extract_citations_with_context(snippet):
                    cite_id = f"{cite_kind}::" + _normalise_node(cite_text)
                    if cite_id == src_id:
                        continue
                    if cite_id not in nodes and len(nodes) < max_nodes:
                        nodes[cite_id] = {
                            "id": cite_id, "label": cite_text, "kind": cite_kind,
                            "jurisdiction": jur, "year": _extract_year_in(cite_text),
                            "weight": 1,
                        }
                        ek = (src_id, cite_id, _classify_edge(sent))
                        edges_set[ek] += 1
                        inbound[cite_id] += 1
        except Exception as exc:
            log.warning("graph live-registry fallback failed: %s", exc)

    # Apply weights = inbound count
    for nid, n in nodes.items():
        n["weight"] = max(1, inbound.get(nid, 1))

    edges = [
        {"from": a, "to": b, "type": t, "count": cnt}
        for (a, b, t), cnt in edges_set.items()
    ]

    return {
        "seed": seed_query,
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "passages_used": len(passages),
            "live_supplemented": len(passages) == 0 or len(nodes) < 8,
        },
    }


_YEAR_RE = re.compile(r"\b(1[7-9]\d{2}|20\d{2})\b")


def _extract_year_in(text: str) -> int | None:
    if not text:
        return None
    m = _YEAR_RE.search(text)
    return int(m.group(0)) if m else None


def expand_node(node_label: str, depth: int = 1) -> dict[str, Any]:
    """Expand a single node by re-retrieving with that node's label."""
    return build_graph(node_label, max_nodes=20)
