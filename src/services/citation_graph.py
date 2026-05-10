"""Citation graph builder — Kuzu (embedded Cypher graph) + Eyecite + Indian/EU parsers.

Stores the citation graph compactly (edges only, ~100 bytes/edge) so we can do
precedent traversal across millions of cases without storing them.

Schema:
  Node Document(canonical_doc_id, source_name, jurisdiction, doc_type, year)
  Edge CITES(citing_doc_id -> cited_doc_id, citation_string, treatment)
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable

import kuzu

from src.config import DATA_DIR

GRAPH_DIR = DATA_DIR / "citation_graph"
GRAPH_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = GRAPH_DIR / "kuzu.db"


# ── Citation parsers ───────────────────────────────────────

# Indian neutral / vintage citation patterns
_INDIAN_PATTERNS = [
    re.compile(r"\b(\d{4})\s+SCC\s+(?:OnLine\s+)?(\w+)?\s*(\d+)", re.I),  # 2017 SCC 1
    re.compile(r"\b(\d{4})\s+\d+\s+SCC\s+\d+", re.I),
    re.compile(r"\bAIR\s+(\d{4})\s+SC\s+\d+", re.I),
    re.compile(r"\((\d{4})\)\s+\d+\s+SCC\s+\d+", re.I),
]

# EU ECLI pattern
_ECLI_PATTERN = re.compile(r"ECLI:[A-Z]{2}:[A-Z0-9]+:\d{4}:[A-Z0-9.]+", re.I)

# EU CELEX pattern
_CELEX_PATTERN = re.compile(r"\b[1-9]?\d{4}[A-Z]\d{4,}\b")


def parse_citations(text: str, *, jurisdiction: str = "") -> list[str]:
    """Return a list of citation strings extracted from `text`.

    Uses Eyecite for US/UK, regex for Indian/EU.
    """
    results: list[str] = []
    # US / UK via eyecite (handles Bluebook + many UK formats)
    try:
        from eyecite import get_citations
        from eyecite.tokenizers import HyperscanTokenizer
        try:
            tokens = HyperscanTokenizer()
            cits = get_citations(text, tokenizer=tokens)
        except Exception:
            cits = get_citations(text)
        for c in cits:
            try:
                s = c.matched_text() if hasattr(c, "matched_text") else str(c)
                if s:
                    results.append(s.strip())
            except Exception:
                continue
    except Exception:
        pass

    # India
    for pat in _INDIAN_PATTERNS:
        for m in pat.finditer(text):
            results.append(m.group(0))

    # EU ECLI / CELEX
    for m in _ECLI_PATTERN.finditer(text):
        results.append(m.group(0))
    for m in _CELEX_PATTERN.finditer(text):
        results.append(m.group(0))

    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for c in results:
        norm = c.strip()
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


# ── Graph storage ──────────────────────────────────────────


def _ensure_schema(conn: kuzu.Connection) -> None:
    try:
        conn.execute(
            """
            CREATE NODE TABLE IF NOT EXISTS Document(
                canonical_doc_id STRING,
                source_name STRING,
                jurisdiction STRING,
                doc_type STRING,
                year INT64,
                PRIMARY KEY (canonical_doc_id)
            )
            """
        )
        conn.execute(
            """
            CREATE REL TABLE IF NOT EXISTS CITES(
                FROM Document TO Document,
                citation_string STRING,
                treatment STRING
            )
            """
        )
    except RuntimeError as exc:
        # Older Kuzu versions don't support IF NOT EXISTS
        if "already exists" not in str(exc).lower():
            raise


def get_db() -> tuple[kuzu.Database, kuzu.Connection]:
    db = kuzu.Database(str(DB_PATH))
    conn = kuzu.Connection(db)
    _ensure_schema(conn)
    return db, conn


def upsert_document(conn: kuzu.Connection, doc: dict[str, Any]) -> None:
    conn.execute(
        "MERGE (d:Document {canonical_doc_id: $cid}) "
        "SET d.source_name = $name, d.jurisdiction = $j, d.doc_type = $dt, d.year = $y",
        {
            "cid": str(doc.get("canonical_doc_id") or ""),
            "name": str(doc.get("source_name") or ""),
            "j": str(doc.get("jurisdiction") or ""),
            "dt": str(doc.get("doc_type") or ""),
            "y": int(doc.get("year") or 0),
        },
    )


def upsert_citation(
    conn: kuzu.Connection,
    *,
    citing: str,
    cited: str,
    citation_string: str,
    treatment: str = "neutral",
) -> None:
    """Edge insert. The cited node may not exist yet; we create a stub.

    Stubs let us do graph queries before we've ingested every cited doc.
    """
    conn.execute("MERGE (d:Document {canonical_doc_id: $cid})", {"cid": cited})
    conn.execute(
        """
        MATCH (a:Document {canonical_doc_id: $citing}), (b:Document {canonical_doc_id: $cited})
        CREATE (a)-[:CITES {citation_string: $cs, treatment: $tr}]->(b)
        """,
        {"citing": citing, "cited": cited, "cs": citation_string, "tr": treatment},
    )


def build_from_chunks(chunks: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Walk an iterable of corpus chunks (dict with 'text' + 'metadata')
    and populate the citation graph.
    Returns counters."""
    db, conn = get_db()
    docs_seen = 0
    edges = 0
    skipped = 0
    seen_doc_ids: set[str] = set()
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        cid = str(meta.get("canonical_doc_id") or meta.get("chunk_id") or "")
        if not cid:
            skipped += 1
            continue
        if cid not in seen_doc_ids:
            upsert_document(conn, meta)
            seen_doc_ids.add(cid)
            docs_seen += 1
        text = chunk.get("text") or ""
        citations = parse_citations(text, jurisdiction=meta.get("jurisdiction", ""))
        for cit in citations[:50]:  # cap per chunk
            cited_id = f"cite:{re.sub(r'[^a-zA-Z0-9_]', '_', cit)[:48]}"
            try:
                upsert_citation(conn, citing=cid, cited=cited_id, citation_string=cit)
                edges += 1
            except Exception:
                # ignore individual edge failures so we don't lose the rest
                continue
    return {"documents": docs_seen, "edges": edges, "skipped": skipped}


def graph_stats() -> dict[str, int]:
    """Quick stats — useful for ingestion summary."""
    db, conn = get_db()
    n = conn.execute("MATCH (d:Document) RETURN count(d)").get_next()[0]
    e = conn.execute("MATCH ()-[r:CITES]->() RETURN count(r)").get_next()[0]
    return {"documents": int(n), "edges": int(e)}


def export_jsonl(out: Path) -> Path:
    """Export the graph to JSONL (for backups / external tools)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    db, conn = get_db()
    rows = conn.execute("MATCH (a)-[r:CITES]->(b) RETURN a.canonical_doc_id, b.canonical_doc_id, r.citation_string")
    with out.open("w", encoding="utf-8") as fh:
        while rows.has_next():
            row = rows.get_next()
            fh.write(json.dumps({"citing": row[0], "cited": row[1], "citation": row[2]}, ensure_ascii=False) + "\n")
    return out
