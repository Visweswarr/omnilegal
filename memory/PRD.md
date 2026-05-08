# OmniLegal v3 — Product Requirements Document

## Original problem statement
> *"the issue is everything in this project feels like it can be done in chat
> gpt with a better prompt I want to make this better I want to make this state
> of the art how can I do it"*

## Vision / Ideology
> **ChatGPT gives you prose. OmniLegal gives you a verdict, a map, and proof.**

OmniLegal is positioned as the *trust-layer / oracle* for legal AI — not just
another chat wrapper. Six single-click expert workflows, every output grounded
in a 22-collection primary-source corpus, every claim auto-audited against the
corpus.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│ React shell at /app/frontend (port 3000)                 │
│ ├ /              Landing — "The Verdict, the Map, the    │
│ │                 Proof" hero + animated metrics         │
│ ├ /atlas         Pillar 01 — Conflict Atlas (world map)  │
│ ├ /forensics     Pillar 02 — Citation Forensics          │
│ ├ /advocacy      Pillar 03 — Advocacy Studio (was MUN)   │
│ ├ /live          Pillar 04 — Live Authority Engine       │
│ ├ /council       Pillar 05 — Council of Models           │
│ └ /research      Pillar 06 — Research Console            │
└────────────────────┬─────────────────────────────────────┘
                     │  /api/*
┌────────────────────▼─────────────────────────────────────┐
│ FastAPI direct host at /app/backend/server.py (port 8001)│
│ ├ legacy router (/app/src/api_router.py): health,        │
│ │      ingestion, conflict, irac, debug                  │
│ └ v3 router (/app/src/api_router_v2.py):                 │
│        atlas, forensics, advocacy, live, council,        │
│        research, overview                                │
└────────────────────┬─────────────────────────────────────┘
                     │
              ┌──────┴──────────┬────────────────────────┐
              │                 │                         │
   Embedded Qdrant       Live registries           LLM clients
   (3,730 chunks /        (Indian Kanoon,           (Claude Sonnet 4.5
    8 collections)         CourtListener,            via Emergent,
                           GovInfo, EUR-Lex,         Gemini 2.5 Flash
                           HUDOC, UN Treaties)       direct, Groq Llama
                                                     3.3 70B)
```

## Tech stack
- Backend: FastAPI 0.110+, uvicorn, embedded Qdrant + FastEmbed (BGE-small)
- Frontend: React 18 + CRA-craco, Tailwind, Framer Motion, react-simple-maps
- Typography: Newsreader (serif) + Geist (sans) + JetBrains Mono (mono)
- Design language: Dark onyx + paper-cream + verdict gold/red/green/amber

## What's been implemented (2026-05-08)

### Backend services (all NEW in this session)
- `src/services/atlas_service.py` — parallelised per-jurisdiction conflict
  analysis + AI-inferred fallback for non-grounded countries; honestly
  downgrades to `no_data` when the LLM analyser is unavailable.
- `src/services/forensics_service.py` — citation extraction (regex for
  US/UK/India/treaty patterns), retrieval against the 22-collection corpus,
  n-gram overlap scoring, per-claim grading
  (verified/partial/suspicious/hallucinated/not_found).
- `src/services/advocacy_service.py` — 4-section packet generator
  (position paper, opening speech, rebuttal cards, leverage cards) with
  schema-validated output and 5-stage provider fallback (Emergent Anthropic
  → Emergent Google → Direct Gemini → Direct Gemini Lite → Groq Llama).
- `src/services/live_authority_service.py` — concurrent calls to six
  registries (Indian Kanoon, CourtListener, GovInfo, EUR-Lex, HUDOC, UN
  Treaty index). Curated landmark fallback for HUDOC and EUR-Lex when their
  public endpoints are unavailable.
- `src/services/council_service.py` — three frontier LLMs answer the same
  question in parallel; a Groq-judge synthesises a final verdict with
  agreements / disagreements / ungrounded-warnings.

### API router
- `src/api_router_v2.py` — POST endpoints for atlas / forensics / advocacy /
  live / council / research; GET /api/overview for landing-page metrics.

### Backend rewrite
- `backend/server.py` — direct FastAPI host on 8001, no proxy. Mounts both
  legacy and v3 routers, CORS enabled.

### Frontend (entirely NEW)
- `frontend/src/App.js`, `index.js`, `index.css` (Tailwind + grain texture +
  print stylesheet + custom scrollbar + verdict stamp animation)
- `frontend/src/components/NavBar.js`, `UI.js`
- `frontend/src/pages/Landing.js`, `Atlas.js`, `Forensics.js`, `Advocacy.js`,
  `Live.js`, `Council.js`, `Research.js`
- `frontend/src/lib/api.js` — typed axios wrappers for every endpoint.

### Corpus
- 3,730 chunks across 8 collections re-ingested via
  `scripts/demo_quick_ingest.py`.

## Personas (preserved from previous version)
1. Researcher (default)
2. Law Student (IRAC)
3. Tourist (practical)
4. Layman (plain English)
5. Conflict Detector (cross-jurisdiction)

## Status of integrations
- Emergent universal key: **BUDGET EXCEEDED** ($1.014 used / $1.001 max).
  User must add balance via Profile → Universal Key → Add Balance.
- Direct Gemini API: rate-limited (free tier).
- Groq: ✅ working — currently powering Advocacy + Council.
- Indian Kanoon, CourtListener, GovInfo, UN Treaties: ✅ live.
- HUDOC, EUR-Lex: curated landmark fallback when public APIs unreachable.

## Backlog / next sessions

### P0 — fix while Emergent budget is replenished
- Atlas runs in lexical mode → currently shows `no_data` honestly. Once
  Emergent budget is restored it will go back to the full Claude entailment.

### P1 — Tier-2 pillars
- Citation Graph Explorer (case-to-case influence graph)
- Doctrine Time Machine (timeline of doctrinal evolution)
- Statute Diff Engine (compare two versions of a law)
- Voice MUN Coach → renamed to **Voice Coach** (live fact-checked dictation)
- Argument Workbench / Red Team Mode

### P2 — polish
- Saved reports library + public share links
- Print stylesheet refinements for Forensics report
- Citation graph edge weight tuning
- Streaming responses (SSE) for long-running endpoints

## Key user choices recorded
- Audience: all (researchers, students, lawyers, debaters, journalists, policy)
- Frontend: hybrid React shell, existing Chainlit preserved in repo (not
  served — replaced by React Research console using same backend services).
- LLMs: Claude Sonnet 4.5 (Emergent) + Gemini 2.5 Flash + Groq Llama 3.3 70B.
- Don't mention "MUN" anywhere — Pillar 03 is "Advocacy Studio" with
  "Leverage Cards" (universal terminology).

## Smart-business enhancement (revenue lever)
The most monetizable angle is **OmniLegal as the trust-layer for other AI
products** (Forensics-as-a-Service): law firms, EdTech companies and
journalism platforms could license a `/forensics/verify` API to grade
LLM-generated content. Pricing: per-verification or per-corpus-licence.
