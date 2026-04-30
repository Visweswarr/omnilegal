# OmniLegal — Product Requirements Document

_Last updated: Apr 2026_

## Original problem statement

> "I want OmniLegal to actually interpret the PDFs (Malcolm Shaw etc.) and answer
> questions across all of them. Three modes: tourist, law student, researcher,
> layman. Keep Gemini fallback. Don't make a new pipeline — integrate into
> the existing one. Stay Chainlit + text-only. Reference the case-laws folder
> for ingestion. It must NOT look like a normal chatbot — this is for a funding
> presentation."

## Goal

A persona-aware international/comparative legal research console that pulls
verified excerpts from a 1,878-passage corpus (Malcolm Shaw, UN Charter,
ICCPR, ICESCR, Constitution of India, curated case-law catalog) and turns
them into answers tuned to the audience: **Tourist · Law Student ·
Researcher · Layman**.

## Core requirements

1. Index every bundled PDF (treaties + Indian Constitution + Malcolm Shaw 3,233
   pages) and the curated `caselaws/*.json` source catalog.
2. Hybrid retrieval — dense (BGE-m3 or FastEmbed BGE-small) + lexical fallback.
3. Persona-tuned synthesis with `[S#]` citations.
4. Free, primary LLM (Claude Haiku 4.5 via Emergent universal key) with Gemini
   2.5 Flash as the always-on fallback when retrieval is sparse.
5. Premium editorial UI — Oxford-blue + parchment, serif typography, no
   chatbot-style chrome.
6. Chainlit-based, text-only, idempotent ingestion script.

## User personas

| Persona | When to use | Voice |
|---------|-------------|-------|
| Tourist | Travellers, expats facing on-the-ground rights questions | Plain English, action-oriented |
| Law Student | Memos, moots, exam prep | Strict IRAC with citations |
| Researcher | Policy / scholarship / treaty analysis | Doctrinal, comparative, deep |
| Layman | Anyone curious without legal training | Conversational, jargon-free |

## What's been implemented (this session, Apr 30 2026)

- **Path bug fixed** (`src/config.py`): ROOT_DIR now points at `/app`, PDFs
  resolve to `data/pdfs/*`, ingestion actually finds Malcolm Shaw et al.
- **Four-mode persona system**:
  - `src/schemas.py` — AnswerMode enum (tourist_practical, law_student_case_law,
    researcher, layman)
  - `src/services/answer_modes.py` — full ModeSpec for each persona with
    audience, voice, focus, required sections, target word count
  - `src/pipeline/prompts.py` — `system_for(mode)` + `build_synthesis_message`
    are now mode-aware
- **Lenient citation verifier** (`src/pipeline/citation_verifier.py`) — when an
  LLM (emergent/groq/ollama) returns a real draft, publish it. Citations are
  graded as metadata, never used to wipe out a working answer. Fixes the
  primary user complaint ("not able to answer").
- **Gemini fallback hardened** (`src/services/gemini_fallback.py`) — when no
  GEMINI_API_KEY is present, keep the LLM's draft instead of overwriting with
  the canned tourist template.
- **LLM chain rebuilt** (`src/pipeline/llm.py`) — Emergent universal key
  (Claude Haiku 4.5) → Groq → Ollama. Free for the user, no extra config.
- **Vector store made lighter** (`src/rag/vector_store.py`) — automatic
  fall-through from BGE-m3 (FlagEmbedding) → FastEmbed BGE-small (~130 MB,
  CPU-only, no torch). Hybrid_search rewritten to use NumPy instead of torch.
- **Caselaws JSON ingestion** (`scripts/ingest_caselaws_sources.py`) — every
  source in `caselaws/*.json` is indexed into COMMENTARY_GLOBAL with
  source_role=source_catalog so "where can I find ICJ judgments?" works.
- **Bootstrap CLI** (`scripts/bootstrap_corpus.py`) — one command indexes
  everything.
- **Premium UI redesign**:
  - `chainlit_app.py` rewritten — `cl.ChatProfiles` for persona picker,
    diagnostic line, sources panel, inline-citation normaliser ([3] → [S3]).
  - `public/custom.css` — Oxford-blue + parchment editorial theme, Playfair
    Display + Cormorant Garamond + JetBrains Mono fonts, glassmorphism cards,
    block-quote source excerpts, `§` watermark.
  - `.chainlit/config.toml` — points to `public/custom.css`.
  - `chainlit.md` — landing copy describing the four personas.
- **Supervisor entry** (`/etc/supervisor/conf.d/supervisord_chainlit.conf`)
  for Chainlit on port 3000.
- **Validation** — testing agent confirmed all 14 critical checkpoints pass:
  4-persona switching, real grounded answers (Tourist 5 sources / 11 s,
  Law Student IRAC 5 sources / 19 s), Sources panel with page numbers,
  no escape-code leakage, no JS errors.

## Indexed corpus snapshot

- INTL_TREATIES: 275 passages (UN Charter, ICCPR, ICESCR)
- NATIONAL_IN: 241 passages (Constitution of India)
- SHAW_PRIVATE: 1,267 passages (Malcolm Shaw, *International Law*, 3,233 pp.)
- COMMENTARY_GLOBAL: 95 entries (curated case-law catalog from `caselaws/*.json`)

## Future / backlog (P1 → P2)

- P1 — Improve Tourist-mode retrieval relevance for cross-border queries
  (jurisdiction-aware reranking so "Russia traffic police" filters out unrelated
  Indian constitutional schedule entries).
- P1 — Optional GROQ_API_KEY path for local low-cost demos.
- P2 — Stream tokens as they arrive (currently waits for full Claude response).
- P2 — Persistent citation graph: hyperlinked [S#] tags scroll the Sources
  panel into view on click.
- P2 — Plug in a second LLM (gpt-5.2) when Emergent budget rises.
- P2 — Multi-PDF upload from the Chainlit composer with on-the-fly ingestion
  (currently disabled; PDFs must be dropped into `data/pdfs/`).

## Next action items

1. User should ship the included `.env.example` to local `.env` with their own
   `GEMINI_API_KEY` for true fallback safety.
2. Run `python scripts/bootstrap_corpus.py` once after adding new PDFs.
3. Ship to demo. Use Law Student or Researcher persona for the funding pitch
   to showcase IRAC reasoning + Malcolm Shaw retrieval.
