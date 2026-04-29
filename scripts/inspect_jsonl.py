import json
from pathlib import Path

jsonl = Path(r"c:\Users\reddy\Downloads\NLP Legal Summarizer\case_with_all_sources_with_companion_cases_tag.jsonl")
with open(jsonl) as f:
    first = json.loads(f.readline())

# Print all keys and a sample of non-empty values
for k, v in sorted(first.items()):
    sample = str(v)[:200] if v else "(empty)"
    print(f"  {k}: {sample}")
