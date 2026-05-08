# OmniLegal — Product Requirements Document

_Last updated: 2026-01-08_

## Original problem statement (verbatim)

> I added so many .txt files in law text files folder please add them to the app
> like it uses all the things and add a feature where it tells about conflict as
> well like we ask a question about something what it conflicts with a local law
> of which country but internationally it is avoidable add a conflict feature as
> well where it tells everything that is conflicted [...] make sure it is state
> of the art best in everything right now make sure it can answer any question
> asked from the existing ingestion and the new .txt files and add a conflict
> detector in law [...] make sure you make the most of existing .env file as well

## User personas

- **Tourist** — practical rights & local law for travellers (default)
- **Law Student** — case-law-heavy IRAC answers
- **Researcher** — academic, footnote-dense
- **Layman** — plain-English, jargon-free
- **Conflict Detector** — cross-jurisdiction comparison with VCLT Art. 27 framing (NEW)

## Architecture

- **Frontend slot (port 3000)**: Chainlit research console (`/app/chainlit_app.py`).
  Persona picker, slash commands `/conflict`, `/irac`, `/verify`, side-by-side
  comparison cards, `[S#]` citation pane, citation audit panel.
- **Backend slot (port 8001)**: thin `httpx` proxy that forwards every `/api/*`
  request to `http://127.0.0.1:3000/api/*` (`/app/backend/server.py`). The actual
  REST endpoints are mounted **inside** the Chainlit FastAPI process via
  `src.api_router.attach_to_chainlit_app()` — this guarantees the embedded
  Qdrant client is single-process and never lock-contended.
- **Vector store**: embedded Qdrant at `data/qdrant_embedded/` with FastEmbed
  (`BAAI/bge-small-en-v1.5`, 384-dim) for dense retrieval.
- **LLMs**: Emergent universal key → Claude Sonnet 4.5 primary, Gemini 2.5 Flash
  fallback, Groq Llama-3.3-70B available for ladder fallback.

## Core requirements (static)

1. Multi-jurisdiction legal RAG over user-supplied corpora.
2. Persona-driven answer styles with grounded `[S#]` citations.
3. Cross-jurisdiction **conflict detector** with 4-tier classification
   (alignment / qualified_alignment / conflict / neutral) and VCLT Art. 27
   framing.
4. Per-jurisdiction **IRAC** synthesis with side-by-side comparison table.
5. **Citation verification** (CRAG-style n-gram overlap) graded
   high / medium / low / no-claims.
6. Idempotent ingestion of `Law Text Files/<folder>/*.txt` and PDF authorities.

## What's been implemented (2026-01-08)

- ✅ Ingested **7,876 chunks** from `Law Text Files/` (Indian + International +
  Israel + Russian + USA) via `scripts/ingest_law_text_files.py`. Folder routing:
  `Indian Law/ → STATUTES_IN`, `International Law Texts/ → COMMENTARY_GLOBAL`,
  `Israel Law/ → STATUTES_IL`, `Russian Law/ → STATUTES_RU`, `USA LAW/ → STATUTES_US`.
- ✅ Ingested PDFs (UN Charter, ICCPR, ICESCR, Indian Constitution, Malcolm
  Shaw's *International Law*) — total **9,972 chunks across 22 collections**.
- ✅ New service `src/services/conflict_detection.py` with both
  pairwise (`analyze_conflict`) and multi-jurisdiction
  (`analyze_multi_jurisdiction_conflict`) entry points. LLM-based
  entailment via Claude Sonnet 4.5 (Emergent) → Gemini fallback. Strict
  JSON contract; `used_model` propagated end-to-end.
- ✅ New service `src/services/cross_jurisdiction.py` (`comparison_payload`)
  for IRAC + comparative synthesis + markdown table.
- ✅ New service `src/services/citation_verification.py` (CRAG-style
  n-gram audit + flagged-claim renderer).
- ✅ New service `src/services/emergent_llm.py` — sync wrapper around
  Emergent `LlmChat` that runs in a fresh thread/event-loop so it works
  inside async FastAPI/Chainlit handlers.
- ✅ Chainlit UI rewritten (`chainlit_app.py`) with 5 personas, slash
  commands `/conflict` `/irac` `/verify`, color-coded labels (🟢🟠🔴🟡),
  VCLT reminder, and click-friendly Sources panel.
- ✅ FastAPI sidecar rewritten as a 300s `httpx.AsyncClient` proxy.
- ✅ `src.api_router.attach_to_chainlit_app()` mounts `/api/health`,
  `/api/ingestion/status`, `/api/ingestion/run`, `/api/conflict/analyze`,
  `/api/irac/analyze`, `/api/debug/retrieve` directly on Chainlit's FastAPI
  app and re-orders routes ahead of Chainlit's catch-all.

## Test results (iteration_3.json)

| Endpoint / feature | Result |
|---|---|
| `GET /api/health` | PASS |
| `GET /api/ingestion/status` (9,972 points, all required collections >0) | PASS |
| `GET /api/debug/retrieve?...&collections=STATUTES_IN` | PASS (real arbitration treatise) |
| `POST /api/conflict/analyze` (death penalty IN/US) | PASS — qualified_alignment 0.78/0.72 |
| `POST /api/irac/analyze` (anticipatory self-defense US/UK) | PASS |
| Chainlit UI title + 9,972 banner | PASS |
| Chainlit `/conflict` slash command full report | PASS |
| Chainlit Tourist query with [S#] + Sources + Citation audit | PASS |
| `used_model` propagation in conflict response (initially empty) | FIXED post-iteration_3 |

## Backlog / future ideas

### P1
- Streaming token-by-token answers in Chainlit (LangGraph already supports
  it; would need a Chainlit `cl.Message.stream_token` adaptation).
- Persist conflict reports to MongoDB for repeat queries / public links.

### P2
- True click-to-jump on `[S#]` markers (Chainlit element refs +
  scroll-into-view).
- Heavy reranker (BAAI/bge-reranker-v2-m3) — needs CUDA / >2 GB extra RAM.
- Audio Q&A via Whisper (already in `.env` budget but UI not wired).
- Comparative-law watchdog: schedule weekly re-runs of canonical conflict
  queries and email diffs.

### P3
- Multilingual answers (Hindi, Hebrew, Russian) — Claude already supports
  these but UI is English-only.

## Next tasks

1. Wire Chainlit `/verify` to the IRAC report so users can audit
   cross-jurisdiction synthesis claims as well as Tourist answers.
2. Add a `/save` slash command that pins the last conflict report for sharing.
3. Build a public read-only "Conflict Library" mini-page that lists
   curated cross-jurisdiction conflict reports.
