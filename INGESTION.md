# OmniLegal Corpus — Build & Run Guide

## Quick reference

```bash
# Run full ingestion across all tiers (production):
python -m scripts.run_master_ingest --tier all --max-items 80 --budget-gb 4.0

# Dev / smoke test — 3 items per source:
python -m scripts.run_master_ingest --tier S --max-items 3

# Lexical-only (skip dense embeddings — useful when you just want to seed BM25):
python -m scripts.run_master_ingest --tier all --lexical-only

# Reset and start fresh:
python -m scripts.run_master_ingest --tier all --reset-checkpoint
```

## Storage budget (designed for /app == 8 GB)

| Layer | Path | Purpose |
|---|---|---|
| Gold | `/app/data/qdrant_embedded` | Vector index (small, on-app) |
| Citation graph | `/app/data/citation_graph/kuzu.db` | Eyecite-extracted edges |
| Bronze (raw) | `/opt/omnilegal_cache/bronze` | Raw downloads — outside `/app` |
| Models cache | `/opt/cache/huggingface` | bge-small / bge-m3 weights |

## Known failure modes & remedies

* **Internet Archive 503**: temporary throttling. The doctrinal canon adapter
  retries with exponential backoff and falls back to advancedsearch.php to
  locate alternative editions. If a particular item keeps 503-ing, replace its
  ID in `_CANON` (in `src/services/adapters/doctrinal_canon.py`) with another
  verified IA item.
* **Refworld / OHCHR JURIS / UNCITRAL CLOUT returning 0 chunks**: the
  public pages are JavaScript-rendered. Playwright or their respective
  XML APIs are needed; this is in P2.
* **AWS Indian HC adapter empty**: the actual bucket prefix layout may differ
  from our 4 fallback prefixes. Run `aws s3 ls s3://indian-high-court-judgments
  --no-sign-request` to confirm.
* **Embedding very slow on first run**: bge-small downloads ~135 MB on first
  use, then is cached at `/opt/cache/fastembed`.

## Adding a new source

1. Add a JSON entry to `caselaws/<file>.json`. Use `name`, `url`, `type`,
   `coverage`, `access`, `format`, `license`, `recommended_for` (collection
   targets).
2. Either:
   * Reuse an existing adapter (the dispatcher matches by URL/keyword), OR
   * Add a new file in `src/services/adapters/` and register it in
     `adapters/__init__.py`. Pattern: `def fetch(record, plan, *, root, budget,
     max_items, max_bytes, mode, checkpoint, resume, ingest, quality_gate,
     **_kwargs) -> tuple[list[chunk], list[event]]`.
3. Add a routing rule in `adapter_for_record()` in
   `src/services/remote_sources.py`.
4. Run a smoke test: `python -m scripts.run_master_ingest --tier S
   --max-items 2`.
