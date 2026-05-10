# OmniLegal — PRD

## Original problem
> "the database is currently shit ... I want to improve the sources properly like really properly ... please make the knowledge state of the art ... I want YOU to determine the optimal corpus strategy."

User attached two research docs and shared a `.env` listing all integration keys
they hold. The corpus had ~219 records total across all jurisdictions, so even
correct retrieval pipelines were producing weak answers.

## Architecture (Jan 2026)

* **Stack:** Chainlit UI on port 3000; LangGraph reasoning core; Qdrant
  (embedded mode at `/app/data/qdrant_embedded`); FastEmbed `bge-small-en-v1.5`
  for retrieval (384-d). Optional `bge-m3` (1024-d) is wired but not pre-loaded.
* **Citation graph:** Kuzu embedded DB at `/app/data/citation_graph/kuzu.db`
  built via Eyecite + Indian/EU regex parsers. Edge-only storage = ~100 bytes per
  edge so the graph stays small even at scale.
* **Storage discipline:** `/app` is only 8 GB free; Bronze (raw) goes to
  `/opt/omnilegal_cache`, models to `/opt/cache/huggingface`. Gold (chunks +
  metadata) lives on `/app/data/`.

## Corpus tiers (tier-based catalog)

| Tier | Catalog file | Sources | Decision basis |
|---|---|---|---|
| **S — Doctrinal** | `caselaws/tier_s_doctrinal.json` | Constitute Project, Doctrinal Canon (Blackstone, Story, Federalist, Maine, Pollock, Salmond, Bentham, Austin, Grotius, Vattel, Oppenheim, Justinian, Wigmore), OHCHR JURIS, ICRC IHL, UNCITRAL CLOUT, Refworld, HCCH, Italaw, UN Treaty Collection, Comparative Constitutions Project | Highest reasoning-density per GB. Public domain + open access. |
| **1 — Primary law** | `caselaws/tier_1_india.json` (+ legacy national/intl) | AWS Indian SC + 25 HCs (CC-BY-4.0), India Code, Indian Tribunals consolidated (ITAT/CESTAT/NCLAT/NGT/CAT/TDSAT/SAT/IBBI/AFT/DRT/CCI), PRS, Indian Kanoon API rate-limited, EUR-Lex CELLAR, GovInfo, CourtListener, legislation.gov.uk, Légifrance | Authoritative statutes + landmark cases per jurisdiction. |
| **2 — HF datasets** | `caselaws/tier_2_hf_datasets.json` | IL-TUR, ILDC, HLDC, LexGLUE, Multi-EURLEX, Pile-of-Law (bva subset), MultiLegalPile (commercial subset), ECtHR-cases, LegalBench, CaseHold, MILDSum, IL-PCR, NyayaAnumana, CUAD, RusLawOD | Curated, pre-cleaned, high-signal. |
| **DEFERRED** | (none) | Full Pile-of-Law (256 GB), full MultiLegalPile (689 GB), full OpenAlex/HathiTrust snapshots, BAILII bulk, CanLII (litigation risk), SudAct, all commercial DBs | Won't fit on this disk; use API-based on-demand retrieval if needed. |

## What was built / changed

### Code
- **9 new high-density adapters** in `src/services/adapters/`:
  `constitute_project.py`, `ohchr_juris.py`, `refworld.py`,
  `uncitral_clout.py`, `hcch.py`, `italaw.py`, `indian_tribunals.py`,
  `doctrinal_canon.py`, `india_aws_hc.py`.
- **Citation graph** at `src/services/citation_graph.py` (Kuzu + Eyecite +
  Indian/EU regex). Stores `Document` + `CITES` edges; sub-millisecond
  precedent traversal. Currently 171 docs, 271 edges from a small Tier-S seed.
- **Master orchestrator** at `scripts/run_master_ingest.py` — tiered, budget-aware,
  resumable. `python -m scripts.run_master_ingest --tier all --max-items 50`.
- **Adapter dispatch** `adapter_for_record()` in `remote_sources.py` extended
  to route the new sources by URL/keyword patterns.
- **Source registry** `configs/source_registry.yaml` rewritten from 7 hardcoded
  topics → ~80 topics covering international law, India, US, UK, EU, Russia,
  Israel, France/Germany/Spain, comparative, doctrinal foundations.

### Configuration
- `.env` populated from user's spec + Légifrance keys (PISTE_API_KEY,
  PISTE_CLIENT_ID). Permission flags set for academic research use.
- Storage paths pointed at `/opt` (88 GB) for Bronze + models cache.
- `OMNILEGAL_REMOTE_BUDGET_GB=4.0`,
  `OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE=200` — tight but sane defaults.

### Validated end-to-end
- Live ingestion run on Tier-S with `--max-items 3`: **615 chunks produced from
  10 sources in ~5 minutes**; **623 points in Qdrant** (582 COMMENTARY_GLOBAL +
  41 CASE_LAW_GLOBAL).
- Retrieval test against new corpus returns substantive matches:
  Blackstone for "law of property", Italaw for "ICSID arbitration",
  Brazil/Israel constitutions for separation-of-powers, etc.
- Citation graph built from existing corpus: **171 documents / 271 edges**.
- All new adapters lint clean (ruff).
- Existing Chainlit app + LangGraph imports unbroken.

## Backlog (priority order)

* **P0 — Run full Tier-S/1/2 ingestion** (~5 GB total, ~3–6 hours):
  `python -m scripts.run_master_ingest --tier all --max-items 80 --budget-gb 4.0`.
  Will populate Qdrant with ~25–50 K chunks for production-grade coverage.
* **P1 — Switch retrieval to bge-m3 (1024-d)** for Tier-S/1 high-value chunks.
  Two-tier embedding: bge-m3 for primary law + doctrinal canon (~10 K chunks),
  bge-small for the bulk Tier-2 corpus.
* **P1 — Live Qdrant** (Docker container) once `--budget-gb` exceeds 4 — embedded
  mode warns about slowdown beyond ~100 K points.
* **P2 — Add SPLADE sparse vectors** for hybrid retrieval (improves recall on
  rare legal terms).
* **P2 — JS-rendered scrapers** for Refworld, OHCHR JURIS, UNCITRAL CLOUT
  (currently return 0 chunks — the public pages are JS-heavy). Use Playwright
  or target their underlying APIs.
* **P2 — AWS Indian HC bulk** — fetch verified bucket prefix; current adapter
  tries 4 prefix patterns but the actual bucket layout may need adjustment.
* **P3 — Akoma Ntoso normaliser** for Silver layer (canonical XML for cross-
  jurisdiction reasoning).
* **P3 — Kuzu graph queries exposed in retrieval** — let the answer node do
  precedent traversal ("what cases cite this?").

## Next session
Run the full ingestion with `--tier all --max-items 80` and verify answer
quality on real queries from each jurisdiction.
