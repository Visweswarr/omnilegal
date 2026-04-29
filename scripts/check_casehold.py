from datasets import load_dataset
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

ds = load_dataset("lex_glue", "case_hold", split="train[:3]")
print(f"Features: {ds.features}")
print(f"Columns: {ds.column_names}")
for i, row in enumerate(ds):
    for k, v in row.items():
        val = str(v)[:200]
        print(f"  {k}: {val}")
    print()
