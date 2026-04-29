# OmniLegal — Verification-First Legal Research

## Original problem statement
User says the app is supposed to be like the PDF source map (multi-jurisdictional legal RAG over US / UK / EU / India / Russia / Israel / International law) but "nothing is working". Specifically:
- Wrong / hallucinated results
- Uses prewritten legal logic instead of retrieved sources
- Retrieval is inconsistent, pulls wrong jurisdictions
- Missing sources are not detected — system guesses
- No proper citation verification or grounding
- Ingestion partially exists but not reliably indexed

## Goal
A **verification-first legal assistant**, not an AI that tries to answer. Three uses:
1. **Legal Research** — cases / statutes / treaties with how-it-can-be-used / defended-against angles
2. **Legal Conflict Analyzer** — international vs domestic law, which prevails and why
3. **Tourist Safety** — what are my rights, duties, and what to do if something goes wrong abroad

## Architecture — what's been built (Jan 2026)

### New verification-first pipeline — `/app/pipeline_v2/`
- **settings.py** — loads `/app/.env`, centralises paths, model names (Groq llama-3.3-70b-versatile → Gemini 2.5 Flash → OpenRouter free as fallback)
- **vector_store.py** — embedded Qdrant + FastEmbed (`BAAI/bge-small-en-v1.5`, 384-d). Single-writer, file-backed, no external service needed
- **seed_corpus.py** — 38 hand-curated primary-law excerpts (UN Charter, VCLT, VCCR, VCDR, ICCPR, Refugee Convention, Vienna Road Traffic Convention, UDHR + US Constitution + Miranda, Medellín, Reid v Covert + UK HRA + PACE + EU Costa/ENEL + GDPR + India Art. 14/19/21/51, BNS, MV Act, Vishaka, Gramophone, Maneka Gandhi + Russia Art. 15(4), CoAO 12.7 + Israel Basic Law + LaGrand, Avena, Barcelona Traction, Nicaragua, Monism/Dualism doctrine, Tourist Consular Checklist)
- **ingest_seed.py** — one-shot ingestion; enriches with `/app/caselaws/*.json` as source-map commentary; final corpus ~133 indexed passages
- **classifier.py** — deterministic: detects mode (tourist / conflict / research), ISO country codes (US UK EU IN RU IL FR DE JP CN CA AU AE SA TR BR), doc types. No LLM needed
- **retriever.py** — hybrid search with hard jurisdiction filter, query-variant generation per mode, key-term overlap reranking, per-source dedup cap
- **prompts.py** — three specialised system prompts with HARD rules (cite or abstain)
- **llm.py** — Groq (llama-3.3-70b-versatile) → Gemini (2.5-flash) → OpenRouter (meta-llama/llama-3.3-70b-instruct:free) fallback chain
- **citation_verifier.py** — parses [S#] tags, flags unsupported sentences with `⚠ UNSUPPORTED` marker, detects invalid citation labels, computes a grounded-ratio; honours `INSUFFICIENT EVIDENCE:` abstention
- **orchestrator.py** — glue: classify → retrieve → generate → verify → repair-if-weak → format (headers, sources list, verification badge 🟢/🟡/🔴)

### Chainlit UI — `/app/chainlit_app.py`
- Rewritten from scratch; welcome banner shows corpus size
- Three mode chips (Legal Research / Conflict Analyzer / Tourist Safety)
- SHORT / LONG answer style prompt on first question
- Renders: answer → verification badge → sources list (with link + score) → disclaimer
- Inline prefix routing (`research:`, `conflict:`, `tourist:` before the question)

### Infrastructure fixes
- Created `/app/.env` with all user-supplied API keys (Groq, Gemini, OpenRouter, HF, CourtListener, etc.)
- Patched Chainlit 2.4.1 upstream: `_language_pattern` now accepts locale modifiers like `en-US@posix`; `load_translation` strips `@…` / `.…` suffixes so frontend placeholders load correctly
- Supervisor config: replaced the React `frontend` + FastAPI `backend` (which didn't exist) with a single `chainlit` program on port 3000, so the preview URL maps directly to the UI
- Installed `chainlit==2.4.1`, `qdrant-client[fastembed]`, `groq`, `eyecite`, `openai` (for OpenRouter)

## What's working (verified via live tests)
- ✅ Tourist mode with IN+RU + VCCR → 88 % grounded, 8 sources
- ✅ Conflict mode on ICJ vs Indian court → **100 % grounded**, cites Gramophone Co. v. Birendra Bahadur Pandey (1984) correctly, identifies India as dualist
- ✅ Research mode on Miranda v Arizona → **100 % grounded**
- ✅ Insufficient-evidence path: asking about Singapore Penal Code 377A (not in corpus) → system abstains with `INSUFFICIENT EVIDENCE:` block, ⚪ badge, no hallucinated law
- ✅ LLM fallback chain: primary call is Groq llama-3.3-70b, ~5 s latency end-to-end

## Known constraints / backlog
- **Corpus is a hand-curated bootstrap (133 passages).** Adding the 1 000s of real CourtListener / GovInfo / EUR-Lex / India Code bulk ingests is next. Adapters already exist in `src/services/adapters/` from the old pipeline; they can be wired into `pipeline_v2.ingest_<source>` modules.
- Embedded Qdrant is single-writer — running `python -m pipeline_v2.ingest_seed` while Chainlit is live requires `sudo supervisorctl stop chainlit` first. For multi-process ingestion, move to a Qdrant server later.
- No persistent chat history (Chainlit's default in-memory store). Add `literalai` / `chainlit data-layer` for long-term storage later.
- No auth / rate-limiting yet. The old `src/services/production_controls.py` still exists but is not wired into `pipeline_v2`.

## Prioritised backlog
- **P0 — bulk ingestion**: wire the working adapters (CourtListener, GovInfo, EUR-Lex CELLAR, Indian Kanoon, legislation.gov.uk) into `pipeline_v2` so the corpus grows from 133 → 100 000+ passages.
- **P1 — proper PDF/HTML chunking** for bulk docs (reuse `src/services/legal_chunking.py`). Currently only the seed texts are chunked by hand.
- **P1 — Re-ranker on top of dense search** (e.g., `BAAI/bge-reranker-v2-m3`) for even better precision once the corpus grows.
- **P2 — export / share** — let a user export the answer + sources as a PDF / markdown brief.
- **P2 — auth + multi-user history** via Chainlit's Literal AI data layer.
- **P2 — conflict-of-laws scoring** — add a numeric "supremacy confidence" when comparing treaty vs statute.

## Next Action Items
1. Add **bulk ingestion jobs** for at least one real source (CourtListener) using the existing token.
2. Schema-enforce doc_type / jurisdiction at ingest time (fail fast if an adapter returns unknown values).
3. Add **Chainlit persistent data layer** so users can revisit prior conversations.
4. Add a **"Why not cited?"** inspector in the UI — click a retrieved source to see why the LLM chose / ignored it.
