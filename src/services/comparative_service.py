"""Comparative Answer mode — parallel IRAC per jurisdiction + Kuzu cross-citations.

This is the "Pillar 19" feature: given a question like "Compare X under Indian,
US, and UK law", we run:

1. Concurrent fan-out retrieval per jurisdiction from Qdrant.
2. Kuzu citation-graph traversal to surface cross-jurisdiction precedent links
   (cases cited by documents from 2+ different jurisdictions).
3. Per-jurisdiction IRAC generation (LLM) in a ThreadPoolExecutor.
4. Cross-jurisdiction synthesis (LLM) on the assembled IRAC blocks.
5. Return a fully structured JSON payload.

The Kuzu traversal enriches each jurisdiction's IRAC prompt with a
`cross_citation_note` listing cases that are also cited in other jurisdictions —
giving the LLM explicit hooks to draw comparisons rather than inferring them.
"""
from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

log = logging.getLogger("omnilegal.comparative")

# ── Jurisdiction catalogue ─────────────────────────────────────────────────

JURISDICTION_LABELS: dict[str, str] = {
    "india":         "India",
    "in":            "India",
    "us":            "United States",
    "usa":           "United States",
    "uk":            "United Kingdom",
    "gb":            "United Kingdom",
    "eu":            "European Union",
    "international": "International (UN/Treaties)",
    "intl":          "International (UN/Treaties)",
    "russia":        "Russia",
    "ru":            "Russia",
    "israel":        "Israel",
    "il":            "Israel",
}

SUPPORTED_JURISDICTIONS: list[dict[str, str]] = [
    {"key": "india",   "label": "India",               "flag": "IN"},
    {"key": "us",      "label": "United States",        "flag": "US"},
    {"key": "uk",      "label": "United Kingdom",       "flag": "GB"},
    {"key": "eu",      "label": "European Union",       "flag": "EU"},
    {"key": "international", "label": "International",  "flag": "UN"},
]

_DEFAULT_JURISDICTIONS = ["india", "us", "uk"]


# ── Kuzu cross-citation traversal ─────────────────────────────────────────


def _safe_kuzu_query(query: str, params: dict | None = None) -> list[list]:
    """Run a Kuzu Cypher query; return rows as lists.  Silently fails to []."""
    try:
        from src.services.citation_graph import get_db
        _db, conn = get_db()
        result = conn.execute(query, params or {})
        rows: list[list] = []
        while result.has_next():
            rows.append(result.get_next())
        return rows
    except Exception as exc:
        log.debug("Kuzu query failed (non-fatal): %s", exc)
        return []


def _graph_cross_citations(limit: int = 20) -> list[dict[str, Any]]:
    """Find documents that are cited across the graph.

    First tries to find docs cited by nodes from 2+ distinct jurisdictions.
    Falls back to listing all documented citations grouped by citing jurisdiction.
    Returns a list of {cited_id, cited_source, citing_jurisdictions, edge_count}.
    """
    # Primary: cross-jurisdiction (a.jurisdiction ≠ b.jurisdiction or b.jurisdiction is null)
    rows = _safe_kuzu_query(
        """
        MATCH (a:Document)-[r:CITES]->(b:Document)
        WHERE a.jurisdiction IS NOT NULL AND a.jurisdiction <> ''
        RETURN b.canonical_doc_id, b.source_name, b.jurisdiction,
               a.jurisdiction, r.citation_string, a.source_name
        LIMIT $limit
        """,
        {"limit": limit * 8},
    )
    if not rows:
        return []

    # Group: cited_id → set of citing jurisdictions
    cited_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        cited_id  = str(row[0] or "")
        cited_src = str(row[1] or "")
        cited_jur = str(row[2] or "")
        citing_jur = str(row[3] or "")
        cit_str   = str(row[4] or "")
        citing_src = str(row[5] or "")
        if not cited_id:
            continue
        entry = cited_map.setdefault(
            cited_id,
            {"cited_id": cited_id,
             "cited_source": _fmt_cited_source(cited_id, cited_src, cit_str),
             "cited_jurisdiction": cited_jur,
             "citing_jurisdictions": set(),
             "citation_strings": set(),
             "edge_count": 0},
        )
        if citing_jur:
            entry["citing_jurisdictions"].add(citing_jur)
        if cit_str:
            entry["citation_strings"].add(cit_str)
        entry["edge_count"] += 1

    # Prefer nodes cited from 2+ jurisdictions; else show top by edge_count
    cross = [
        {
            "cited_source": v["cited_source"],
            "cited_jurisdiction": v["cited_jurisdiction"],
            "citing_jurisdictions": sorted(v["citing_jurisdictions"]),
            "citation_strings": sorted(v["citation_strings"])[:3],
            "edge_count": v["edge_count"],
            "cross_jurisdiction": len(v["citing_jurisdictions"]) >= 2,
        }
        for v in cited_map.values()
    ]
    cross.sort(
        key=lambda x: (x["cross_jurisdiction"], len(x["citing_jurisdictions"]), x["edge_count"]),
        reverse=True,
    )
    return cross[:limit]


def _graph_jurisdiction_precedents(jurisdiction: str, limit: int = 8) -> list[dict[str, Any]]:
    """Retrieve the most-cited outbound nodes for a given jurisdiction."""
    rows = _safe_kuzu_query(
        """
        MATCH (a:Document {jurisdiction: $jur})-[r:CITES]->(b:Document)
        RETURN b.canonical_doc_id, b.source_name, b.jurisdiction, r.citation_string
        LIMIT $limit
        """,
        {"jur": jurisdiction, "limit": limit},
    )
    out = []
    for row in rows:
        doc_id, src, jur, cit_str = (
            str(row[0] or ""), str(row[1] or ""),
            str(row[2] or ""), str(row[3] or ""),
        )
        if doc_id:
            out.append({"doc_id": doc_id, "source": src or doc_id,
                        "jurisdiction": jur, "citation": cit_str})
    return out


def _fmt_cited_source(cited_id: str, cited_src: str, cit_str: str) -> str:
    """Return a human-readable label for a cited node."""
    if cited_src and not cited_src.startswith("cite:"):
        return cited_src
    if cit_str:
        # Clean the citation string: remove prefix colons, normalize
        clean = cit_str.strip().lstrip(":")
        if clean:
            return clean
    if cited_id.startswith("cite:"):
        # cite:_(1973)_4_SCC_225 → (1973) 4 SCC 225
        return cited_id[5:].replace("_", " ").strip()
    return cited_id


def _build_cross_citation_note(
    jurisdiction_key: str,
    cross_citations: list[dict[str, Any]],
) -> str:
    """Build a short note injected into the IRAC prompt for one jurisdiction."""
    jur_label = JURISDICTION_LABELS.get(jurisdiction_key.lower(), jurisdiction_key)
    relevant = [
        cc for cc in cross_citations
        if any(jur_label.lower() in j.lower() for j in cc["citing_jurisdictions"])
    ]
    if not relevant:
        return ""
    lines = [
        f"Cross-jurisdiction precedent context (from the citation graph):\n"
        f"The following sources are also cited by other jurisdictions in this corpus,"
        f" suggesting they have cross-border authority:\n"
    ]
    for cc in relevant[:5]:
        citing = ", ".join(cc["citing_jurisdictions"])
        lines.append(
            f"  - {cc['cited_source']} (jurisdiction: {cc['cited_jurisdiction'] or 'unspecified'})"
            f" — cited by jurisdictions: {citing}"
        )
    return "\n".join(lines)


# ── Per-jurisdiction retrieval helpers ───────────────────────────────────


def _retrieve_passages_for_jur(query: str, jur_key: str) -> list[Any]:
    """Retrieve Qdrant passages scoped to one jurisdiction.

    For domestic jurisdictions: only domestic collections (so the LLM reasons
    about domestic law). International corpus goes to the International block only.
    """
    try:
        from src.services.conflict_detection import (
            _retrieve_for_jurisdiction,
            _retrieve_international,
        )
        if jur_key in ("international", "intl"):
            return _retrieve_international(query)
        # Domestic only — no international mix-in
        return _retrieve_for_jurisdiction(query, jur_key)
    except Exception as exc:
        log.warning("Passage retrieval failed for %s: %s", jur_key, exc)
        return []


def _is_relevant(passage_text: str, query: str) -> bool:
    """Quick keyword check — returns False for obviously off-topic passages."""
    if not passage_text:
        return False
    # Extract significant tokens from query (4+ chars)
    import re
    query_tokens = set(re.findall(r"[a-z]{4,}", query.lower()))
    passage_lower = passage_text.lower()
    # If at least 1 query token appears in passage → keep it
    return any(t in passage_lower for t in query_tokens)


def _passages_to_text(passages: list[Any], query: str = "") -> str:
    """Format retrieved passages, filtering irrelevant ones first."""
    import re

    # Extract concept-specific tokens from query, skip stopwords
    _STOPWORDS = {
        "what", "that", "with", "from", "this", "have", "been", "were", "they",
        "their", "when", "where", "which", "about", "under", "how", "does",
        "jurisdiction", "jurisdictions", "legal", "case", "court", "courts",
        "domestic", "international", "compare", "comparing", "treat", "treated",
        "law", "laws", "rule", "rules", "right", "rights",
    }
    if query:
        query_tokens = {
            t for t in re.findall(r"[a-z]{4,}", query.lower())
            if t not in _STOPWORDS
        }
    else:
        query_tokens = set()

    relevant, irrelevant = [], []
    for p in passages:
        content = getattr(p, "content", "") or str(p)
        if not query_tokens:
            relevant.append(p)
        elif any(t in content.lower() for t in query_tokens):
            relevant.append(p)
        else:
            irrelevant.append(p)

    # Use only relevant passages for the prompt
    to_use = relevant

    parts = []
    for i, p in enumerate(to_use, 1):
        try:
            src = p.citation.source_name
            jur = getattr(p.citation, "jurisdiction", "")
            content = p.content[:800]
        except AttributeError:
            src = "Unknown"
            jur = ""
            content = str(p)[:800]
        jur_tag = f" [{jur}]" if jur else ""
        parts.append(f"[S{i}] {src}{jur_tag}:\n{content}")

    result = "\n\n".join(parts)[:6000]

    # Explicit instruction when corpus retrieval found nothing relevant
    if not to_use:
        result = (
            "CORPUS NOTE: No relevant passages were found in the local corpus for this query. "
            "You MUST use your authoritative legal knowledge for this jurisdiction to complete the IRAC."
        )
    elif len(to_use) == 1 and irrelevant:
        result += (
            "\n\nCORPUS NOTE: Only one on-topic passage was retrieved. "
            "Supplement with your general legal knowledge as needed."
        )

    return result


# ── Parallel IRAC orchestration ───────────────────────────────────────────


def _run_one_irac(
    query: str,
    jur_key: str,
    cross_citations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Retrieve + build IRAC for a single jurisdiction (runs in a thread)."""
    jur_label = JURISDICTION_LABELS.get(jur_key.lower(), jur_key.capitalize())

    passages = _retrieve_passages_for_jur(query, jur_key)

    # ── Relevance filter — build passages_text ONLY from on-topic passages ──
    relevant_passages = [
        p for p in passages
        if _is_relevant(getattr(p, "content", "") or "", query)
    ]
    if relevant_passages:
        parts = []
        for i, p in enumerate(relevant_passages[:5], 1):
            src = getattr(getattr(p, "citation", None), "source_name", "Unknown")
            jur = getattr(getattr(p, "citation", None), "jurisdiction", "")
            content = getattr(p, "content", "")[:800]
            jur_tag = f" [{jur}]" if jur else ""
            parts.append(f"[S{i}] {src}{jur_tag}:\n{content}")
        # Add cross-citation context note at the top
        cross_note = _build_cross_citation_note(jur_key, cross_citations)
        prefix = (cross_note + "\n\n---\n\n") if cross_note else ""
        passages_text = prefix + "\n\n".join(parts)[:6000]
    else:
        # Nothing relevant — pass empty string so per_jurisdiction_irac uses knowledge mode
        passages_text = ""
    # ───────────────────────────────────────────────────────────────────────

    try:
        from src.services.cross_jurisdiction import per_jurisdiction_irac
        block = per_jurisdiction_irac(query, jur_label, passages_text)
    except Exception as exc:
        log.warning("IRAC generation failed for %s: %s", jur_key, exc)
        block = {
            "jurisdiction": jur_label,
            "issue": query,
            "rule": "",
            "application": "",
            "conclusion": "indeterminate — service error",
            "conditions_if_any": "",
            "confidence": 0.0,
            "key_authorities": [],
            "error": str(exc),
        }

    # Attach only relevant passage metadata for the UI
    block["passages"] = [
        {
            "source_name": getattr(getattr(p, "citation", None), "source_name", "Unknown"),
            "marker":      getattr(getattr(p, "citation", None), "marker",      f"[S{i+1}]"),
            "jurisdiction": getattr(getattr(p, "citation", None), "jurisdiction", ""),
            "excerpt":     (getattr(p, "content", "")[:280] if hasattr(p, "content") else ""),
        }
        for i, p in enumerate(relevant_passages[:4])
    ]
    block["has_source_data"] = bool(relevant_passages)
    return block


def _is_relevant(content: str, query: str) -> bool:
    """Returns True if content contains concept-specific tokens from query."""
    import re
    _STOPWORDS = {
        "what", "that", "with", "from", "this", "have", "been", "were",
        "they", "their", "when", "where", "which", "about", "under", "how",
        "does", "jurisdiction", "jurisdictions", "legal", "case", "court",
        "courts", "domestic", "international", "compare", "comparing",
        "treat", "treated", "treatment", "between", "across", "also", "each",
        "law", "laws", "rule", "rules", "right", "rights", "such", "would",
        "could", "should", "these", "those", "more", "less", "make", "many",
        "erga", "omnes",  # these are the query terms - DON'T filter them
    }
    # Actually: extract ALL meaningful tokens from query, then check passage
    # We want: "if passage is about the concept" not "if passage contains query words"
    # Better approach: use query tokens that are NOT generic legal terminology
    _GENERIC = {
        "what", "that", "with", "from", "this", "have", "been", "were",
        "they", "their", "when", "where", "which", "about", "under", "how",
        "does", "legal", "court", "courts", "domestic", "international",
        "compare", "comparing", "treat", "treated", "treatment", "between",
        "across", "also", "each", "law", "laws", "rule", "rules", "right",
        "rights", "such", "would", "could", "should", "these", "those",
        "more", "less", "make", "many", "jurisdiction", "jurisdictions",
    }
    tokens = {t for t in re.findall(r"[a-z]{4,}", query.lower()) if t not in _GENERIC}
    if not tokens:
        return True  # No specific tokens — accept all
    return any(t in content.lower() for t in tokens)


# ── Top-level entry point ─────────────────────────────────────────────────


def run_comparative(
    query: str,
    jurisdictions: list[str] | None = None,
) -> dict[str, Any]:
    """Main entry point called by the FastAPI endpoint.

    Args:
        query: The user's legal research question.
        jurisdictions: List of jurisdiction keys (e.g. ['india', 'us', 'uk']).
                       Defaults to India, US, UK.

    Returns:
        Structured dict with irac_blocks, synthesis, cross_citations, table, etc.
    """
    jur_keys = [j.lower().strip() for j in (jurisdictions or _DEFAULT_JURISDICTIONS)]
    if not jur_keys:
        jur_keys = list(_DEFAULT_JURISDICTIONS)

    # ── Step 1: Kuzu graph — cross-jurisdiction precedent links ───────────
    log.info("comparative: pulling Kuzu cross-citations for query=%r", query[:80])
    cross_citations = _graph_cross_citations(limit=20)
    log.info("comparative: kuzu returned %d cross-citation nodes", len(cross_citations))

    # ── Step 2: Per-jurisdiction IRAC (parallel) ──────────────────────────
    log.info("comparative: running IRAC for jurisdictions=%s", jur_keys)
    irac_blocks: list[dict[str, Any]] = [{}] * len(jur_keys)

    with ThreadPoolExecutor(max_workers=min(len(jur_keys), 4)) as pool:
        futures = {
            pool.submit(_run_one_irac, query, jur_key, cross_citations): idx
            for idx, jur_key in enumerate(jur_keys)
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                irac_blocks[idx] = future.result()
            except Exception as exc:
                jur_label = JURISDICTION_LABELS.get(jur_keys[idx], jur_keys[idx])
                log.error("IRAC thread for %s raised: %s", jur_label, exc)
                irac_blocks[idx] = {
                    "jurisdiction": jur_label,
                    "issue": query,
                    "rule": "", "application": "",
                    "conclusion": "indeterminate — thread error",
                    "conditions_if_any": "",
                    "confidence": 0.0,
                    "key_authorities": [],
                    "error": str(exc),
                    "passages": [],
                    "has_source_data": False,
                }

    # ── Step 3: Cross-jurisdiction synthesis ──────────────────────────────
    log.info("comparative: running synthesis over %d IRAC blocks", len(irac_blocks))
    intl_block = next(
        (b for b in irac_blocks if "international" in b.get("jurisdiction", "").lower()),
        None,
    )
    intl_summary = (intl_block or {}).get("rule") or (intl_block or {}).get("issue") or ""
    domestic_blocks = [b for b in irac_blocks if b is not intl_block]

    try:
        from src.services.cross_jurisdiction import (
            cross_jurisdiction_synthesis,
            markdown_comparison_table,
        )
        synthesis = cross_jurisdiction_synthesis(
            international_summary=intl_summary or query,
            irac_blocks=irac_blocks,
        )
        comparison_table = markdown_comparison_table(irac_blocks)
    except Exception as exc:
        log.error("synthesis/table generation failed: %s", exc)
        synthesis = {
            "international_rule_summary": intl_summary,
            "agreements": [],
            "disagreements": [],
            "gaps": [b.get("jurisdiction", "") for b in irac_blocks if not b.get("rule")],
            "vclt_article_27_warning": "",
            "error": str(exc),
        }
        comparison_table = ""

    # ── Step 4: Graph stats for UI ────────────────────────────────────────
    graph_stats: dict[str, Any] = {}
    try:
        from src.services.citation_graph import graph_stats as _gs
        graph_stats = _gs()
    except Exception:
        pass

    return {
        "query": query,
        "jurisdictions_requested": jur_keys,
        "irac_blocks": irac_blocks,
        "synthesis": synthesis,
        "comparison_table_markdown": comparison_table,
        "cross_citations": cross_citations,
        "graph_stats": graph_stats,
        "used_models": sorted({
            b.get("used_model", "")
            for b in irac_blocks
            if b.get("used_model")
        }),
    }
