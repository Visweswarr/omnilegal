"""Inspect lex_glue/ecthr_a to understand EU case data structure."""
from datasets import load_dataset
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

# Load a small sample of ECHR cases
ds = load_dataset("lex_glue", "ecthr_a", split="train[:5]")
print(f"Features: {ds.features}")
print(f"Columns: {ds.column_names}")
print()

for i, row in enumerate(ds):
    print(f"--- Example {i} ---")
    for k, v in row.items():
        if isinstance(v, list):
            if v and isinstance(v[0], str):
                total_len = sum(len(s) for s in v)
                print(f"  {k}: {len(v)} items, total {total_len} chars")
                if v:
                    print(f"    first: {v[0][:200]}...")
            else:
                print(f"  {k}: {v}")
        elif isinstance(v, str):
            print(f"  {k}: {v[:200]}")
        else:
            print(f"  {k}: {v}")
    print()
    if i >= 2:
        break
