# OmniLegal v3 — Product Requirements Document

## Original Problem Statement
Build a "Comparative Answer" mode (Pillar 19) for OmniLegal — the user asks
"Compare X under Indian, US, and UK law" and OmniLegal does parallel
IRAC-per-jurisdiction with cross-citations. The Kuzu graph already supports
the precedent-traversal query. Wire that into the LangGraph answer node.

Corpus: Constitute Project + Italaw + ICRC IHL + UN Treaty Collection.
Citation graph: Kuzu graph with CITES edges.

---

## Application Architecture

**Frontend**: React 18 + Tailwind + Lucide-React, served on port 3000
**Backend**: FastAPI (Python 3.11+) served on port 8001 via uvicorn/supervisor
**Vector Store**: SQLite fallback (fastembed BGE-small-en-v1.5 embeddings, 239 docs seeded)
**Citation Graph**: Kuzu in-process graph (248 nodes, 9 edges from corpus extraction)
**LLM Waterfall**: Emergent LLM (Claude Sonnet 4.5) → Groq (llama-3.3-70b) → Gemini 2.5 Flash
**External APIs**: Indian Kanoon, CourtListener, GovInfo, Data.gov, HuggingFace

---

## Corpus Collections Seeded (239 documents)

| Collection       | Docs |
|------------------|------|
| CASE_LAW_GLOBAL  |  50  |
| CASE_LAW_IN      |  17  |
| CASE_LAW_US      |  13  |
| CASE_LAW_UK      |  12  |
| CASE_LAW_EU      |  12  |
| CASE_LAW_IL      |   8  |
| CASE_LAW_RU      |   8  |
| INTL_TREATIES    |   9  |
| NATIONAL_*       |  56  |
| STATUTES_*       |  47  |
| COMMENTARY_GLOBAL|  11  |

---

## Features Implemented (as of 2026-05-10)

### Pillar 01 — Atlas
- Document research with RAG (Qdrant/SQLite + BGE embeddings)
- Multi-source retrieval with reranking

### Pillar 02 — Forensics
- Legal document forensics / deep analysis

### Pillar 03 — Advocacy
- Case argument drafting

### Pillar 04 — Live
- Real-time legal news / live sources

### Pillar 05 — Council
- Multi-agent legal council mode

### Pillar 06 — Research
- Structured legal research assistant

### Pillar 07 — Graph (Citation Graph)
- `POST /api/graph/build` — build Kuzu citation subgraph from seed
- Visualised with D3/force-directed layout

### Pillar 08 — Doctrine
- Legal doctrine analysis

### Pillar 09 — Diff
- Compare two legal texts or positions

### Pillar 10 — Red Team
- Adversarial testing of legal arguments

### Pillar 11 — TimeMachine
- Historical legal document analysis

### Pillar 12 — Voice
- Voice-based legal research

### Pillar 13 — Reading
- Annotated reading mode

### Pillar 14 — Library
- Document library with search

### Pillar 15 — Adversarial (SOTA)
- Adversarial argument generation

### Pillar 16 — Arbitrage (SOTA)
- Cross-jurisdiction legal arbitrage

### Pillar 17 — Drift (SOTA)
- Legal doctrine drift detection

### Pillar 18 — Sentinel (SOTA)
- Compliance sentinel

### Pillar 18b — Stress (SOTA)
- Stress-test legal arguments

### Pillar 19 — Comparative (NEW — 2026-05-10, improved 2026-05-10)
- `POST /api/compare/analyze` — parallel IRAC per jurisdiction + Kuzu cross-citations
- `GET /api/compare/jurisdictions` — supported jurisdictions catalogue
- Supported: India, US, UK, EU, International
- **Smart relevance filter**: strips irrelevant corpus passages so LLM uses authoritative general legal knowledge when corpus is sparse for abstract concepts (erga omnes, jus cogens, etc.)
- **Knowledge-mode IRAC**: when no relevant corpus passages found, sends clean knowledge-mode prompt — LLM cites Barcelona Traction, Filartiga, Pinochet, Vishaka, etc. from training
- LLM marks non-corpus sources as `[general knowledge]` — transparent provenance
- Frontend: `/comparative` page with jurisdiction selector, IRAC grid, synthesis, cross-citation panel

---

## API Routes Summary

| Router    | Prefix  | Key Endpoints                               |
|-----------|---------|---------------------------------------------|
| v1        | /api    | atlas, forensics, advocacy, live, council, research |
| v2        | /api    | graph/build, graph/query                    |
| v3        | /api    | irac/analyze, debug/retrieve                |
| v4        | /api    | adversarial, arbitrage, drift, sentinel, stress |
| v5 (NEW)  | /api    | compare/analyze, compare/jurisdictions      |

---

## Environment Variables (from /app/.env)

- `EMERGENT_LLM_KEY` — Claude Sonnet 4.5 via Emergent
- `GROQ_API_KEY` — Groq llama-3.3-70b (secondary LLM)
- `GEMINI_API_KEY` — Gemini 2.5 Flash (tertiary LLM)
- `OMNILEGAL_VECTOR_BACKEND=embedded_qdrant` (uses SQLite fallback)
- `INDIAN_KANOON_API_TOKEN`, `COURTLISTENER_TOKEN`, `GOVINFO_API_KEY`, etc.

---

## Backlog (P0/P1/P2)

### P0 — Must Have
- [ ] Populate Qdrant with full Constitute Project + Italaw corpus (currently using SQLite fallback with 239 seed docs)
- [ ] Install `qdrant-client` to enable real embedded Qdrant instead of SQLite fallback
- [ ] Expand Kuzu cross-citation edges (currently only 9 India→India citations extracted)

### P1 — Should Have
- [ ] Cross-jurisdiction PDF export for Comparative reports
- [ ] Streaming responses for long compare queries
- [ ] More corpus: Italaw arbitration cases, ICRC IHL full text, UN Treaty Collection

### P2 — Nice to Have
- [ ] Comparative mode: add Russia, Israel jurisdiction support
- [ ] Real-time citation graph updates as new cases are ingested
- [ ] Share/embed comparative report as URL

---

## Next Tasks

1. Run `pip install qdrant-client` and restart backend to enable embedded Qdrant
2. Ingest full Italaw/ICRC/UN Treaties corpus via the ingestion pipeline
3. Add more CITES edges by running regex citation extraction over all documents
4. Add streaming SSE to the compare endpoint for real-time IRAC display
