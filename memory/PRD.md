# OmniLegal v3 — Product Requirements Document

## Original problem statement
Audit and harden the user-built Tier-2 pillars (Diff, Library, Redteam, Doctrine, Graph,
Reading, Voice). Fix issues where Indian Kanoon / CourtListener / Data.gov / EUR-Lex were
giving repetitive answers. Then build genuinely state-of-the-art capabilities that
ChatGPT (or any general LLM) cannot replicate, using only free APIs + Groq + Gemini +
Emergent's Claude.

## Architecture
- **Backend**: FastAPI on :8001 with 4 routers
  - `src.api_router`         — health, ingestion, conflict, irac, debug
  - `src.api_router_v2`      — Atlas, Forensics, Advocacy, Live, Council, Research, Overview
  - `src.api_router_v3`      — Tier-2: Diff, Reports, Redteam, Doctrine, Graph, Reading, Voice
  - `src.api_router_v4`      — **State-of-the-art**: Adversarial, Arbitrage, Drift, Sentinel, Stress
- **Frontend**: React 18 + craco + Tailwind + react-router on :3000.
- **LLM Waterfall**: 5-stage (Emergent Anthropic → Emergent Google → Direct Gemini Flash →
  Direct Gemini Lite → Groq Llama). Used by every Tier-2 + SOTA pillar that needs JSON.
- **Live Registries**: Indian Kanoon, CourtListener (v4), GovInfo, EUR-Lex (real SPARQL),
  HUDOC (40+ landmark index), UN Treaty Index.

## What's been implemented (May 8, 2026)

### Audit + fixes
- Backend env file (`/app/.env`) created with the user's full key bundle.
- Replaced exhausted Emergent key with the friend's account key (`sk-emergent-3Fb5454E7Eb5c492aD`).
- Installed `qdrant-client` + `fastembed`.
- **EUR-Lex**: replaced static curated list with REAL SPARQL search against the EU
  Publications Office endpoint (`publications.europa.eu/webapi/rdf/sparql`).
- **HUDOC**: expanded curated landmark index from 12 to 40+ cases; keyword scoring now
  produces variation across queries.
- **CourtListener**: migrated v3 → v4 endpoint (v3 was deprecated and rate-limited).
- **Indian Kanoon date filters**: fixed inline `fromdate:DD-MM-YYYY` syntax (was being
  ignored when sent as URL params).
- **Graph service**: added live-registry fallback so it always returns nodes when the
  Qdrant corpus is empty.
- **Doctrine service**: enriched candidate retrieval (8 live hits, was 5), tightened the
  LLM prompt so it doesn't drop thin-snippet candidates.
- **Adversarial service**: added duplicate-index guard.
- **CourtListener Drift**: 429-rate-limit retry with backoff; throttled to 4 parallel.

### NEW state-of-the-art pillars (5)
1. **Pillar 14 — Adversarial Case Finder** (`POST /api/adversarial/find`):
   Inverts user's claim, hits live registries with the kill-thesis, ranks results by
   adversarial damage, returns weaponisable quote per precedent.
2. **Pillar 15 — Jurisdiction Arbitrage** (`POST /api/arbitrage/scan`):
   Extracts friction points from a transaction, scans 4-6 jurisdictions in parallel,
   returns favorability matrix with primary citations.
3. **Pillar 16 — Authority Drift Tracker** (`POST /api/drift/analyze`):
   Decade-by-decade citation velocity from Indian Kanoon + CourtListener with date
   filters; produces strengthening/fading/overruled/emerging/stable verdict.
4. **Pillar 17 — Compliance Sentinel** (`POST /api/sentinel/scan`):
   17-rule curated catalogue of pending legal changes (DPDP India, EU AI Act phases,
   GDPR/Schrems II, MiCA, NIS2, BNS, CPRA, etc.). Pattern matches + LLM disambiguation
   + clause-specific remediation.
5. **Pillar 18 — Statute Stress Test** (`POST /api/stress/test`):
   LLM generates 8-12 boundary hypotheticals, classifies each as covered/borderline/gap,
   probes Indian Kanoon + CourtListener for cases that may have decided the boundary.

### Frontend
- 5 new pages: `Adversarial.js`, `Arbitrage.js`, `Drift.js`, `Sentinel.js`, `Stress.js`.
- NavBar grouped: Flagship · Tier-2 · State-of-the-Art · Library.
- Landing redesigned with prominent SOTA section ("Five things no chatbot can do").
- All pages: Save-to-library buttons, sample-loader buttons, primary-source links.
- Every interactive element has a `data-testid` attribute.

## Verified working end-to-end (curl smoke tests)
- `/api/__sidecar_health`, `/api/health` — 3 LLMs configured
- `/api/overview` — 6 live sources, 3 council models
- `/api/diff/compare` — Claude impact summary works
- `/api/redteam/analyze` — 5 weak points, 5 counter-args via Claude
- `/api/doctrine/track` — 8 milestones for "basic structure" via Claude+IK
- `/api/graph/build` — 15 nodes via live registries when corpus empty
- `/api/live/search` — 10 hits across 4 registries (HUDOC, IK, EUR-Lex, CL)
- `/api/sentinel/rules` — 17 rules
- `/api/sentinel/scan` — 5 confirmed findings on a 6-line policy
- `/api/adversarial/find` — 8 ranked counter-precedents in <40s
- `/api/arbitrage/scan` — 5-jurisdiction matrix with hostile/neutral/no_data postures
- `/api/drift/analyze` — "right to privacy" → 14538 hits, "strengthening" verdict
- `/api/stress/test` — 12 hypotheticals, 6 drafting flaws on IT Act §66A

## Known caveats
- **Qdrant corpus**: `data/qdrant_embedded/` is empty (no chunks ingested). Graph,
  Doctrine, and Voice gracefully fall back to live registries instead. Re-running
  `scripts/demo_quick_ingest.py` would produce ~3,730 grounded chunks.
- **HUDOC**: their `app/query/results` JSON endpoint is firewalled in 2025-26;
  curated landmark index is the only viable approach.
- **CourtListener rate limit**: 5 concurrent requests trigger 429; we throttle to 4
  with retry+backoff in Drift Tracker.
- **Voice Coach**: requires Chrome/Edge (uses `webkitSpeechRecognition`).

## Personas
1. **MUN delegate** — uses Atlas, Advocacy, Live for cross-jurisdiction speeches.
2. **Litigator** — uses Adversarial, Drift, Stress, Forensics for case prep.
3. **Compliance officer** — uses Sentinel, Diff, Arbitrage for contract review.
4. **Law researcher** — uses Research, Council, Doctrine, Graph for academic work.

## Backlog (P1-P2)
- Re-ingest the 3,730-chunk corpus so corpus-grounded features have material to ground
  on (instead of relying solely on live registries).
- Pillar 19 — Counter-Cite Sniper: given a list of cases user wants to cite, find the
  strongest opposing cases for each.
- Pillar 20 — Treaty Compliance Audit: scan a domestic statute against ratified UN/
  regional treaty obligations.
- Voice Coach: integrate with new Adversarial Finder so live transcript is fact-checked
  AND adversarially probed.

## Next action items
- Smoke-test the 5 new SOTA pages in browser.
- Optionally rebuild the Qdrant corpus.
- Top up Emergent budget for sustained Claude use.
