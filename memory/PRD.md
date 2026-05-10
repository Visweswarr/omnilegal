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

### Pillar 19 — Comparative v2 (2026-05-10)
- `POST /api/compare/analyze` now returns `heat_map` field alongside irac_blocks + synthesis
- **Jurisdictional Heat Map**: `generate_heat_map()` in `cross_jurisdiction.py` — LLM extracts 4-5 query-specific dimensions and classifies each jurisdiction as full/partial/none/indeterminate
- **Query Expansion**: `_run_one_irac()` falls back to CASE_LAW_GLOBAL when domestic corpus has no relevant passages — abstract concepts (erga omnes, jus cogens) now get Barcelona Traction [S2], Wall Opinion [S1] etc. as real corpus citations
- **Frontend HeatMap component**: colour-coded matrix (green=full, amber=partial, red=none, gray=?), flags, short jurisdiction names, summary verdict, "Brief" print button with clean print CSS
- Duplicate `_is_relevant` function cleaned up

### Pillar 20 — Longitudinal Heat Maps (2026-05-10)
- `POST /api/compare/longitudinal` — parallel IRAC + heat-map for every jurisdiction × time-period combination
- `GET /api/compare/period-presets` — returns the 3 built-in presets (century / postwar / modern)
- `longitudinal_service.py`: year-filtered passage retrieval, period-constrained IRAC prompt ("Analyse position AS IT EXISTED during {period}"), per-period heat map, automatic trend deltas (`up`/`down`/`stable`) between consecutive periods
- Frontend route `/longitudinal` + NavBar entry (Clock icon) — period cards as mini heat maps, click-to-explore IRAC accordion, evolution trend summary panel
- Backend smoke test: 4 periods × 2 jurisdictions returns ≈37KB JSON with full heat maps and trends

---

## API Routes Summary

| Router    | Prefix  | Key Endpoints                               |
|-----------|---------|---------------------------------------------|
| v1        | /api    | atlas, forensics, advocacy, live, council, research |
| v2        | /api    | graph/build, graph/query                    |
| v3        | /api    | irac/analyze, debug/retrieve                |
| v4        | /api    | adversarial, arbitrage, drift, sentinel, stress |
| v5 (NEW)  | /api    | compare/analyze, compare/jurisdictions, compare/longitudinal, compare/period-presets |

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

1. Locally ingest the three new corpus files via `python scripts/seed_qdrant.py`:
   - `/app/data/corpus/intl_treaties/icrc_ihl_corpus.jsonl`
   - `/app/data/corpus/intl_treaties/un_treaties_full.jsonl`
   - `/app/data/corpus/case_law_global/ihl_case_law.jsonl`
2. Rebuild Kuzu citation graph after ingestion (more cross-citation edges)
3. Add streaming SSE to compare/longitudinal endpoints for real-time period reveal
4. PDF export of Longitudinal timeline reports

