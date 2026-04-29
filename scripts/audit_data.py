import json
from pathlib import Path

jsonl = Path(r"c:\Users\reddy\Downloads\NLP Legal Summarizer\case_with_all_sources_with_companion_cases_tag.jsonl")
print(f"Exists: {jsonl.exists()}")
if jsonl.exists():
    print(f"Size: {jsonl.stat().st_size / 1024 / 1024:.1f} MB")
    with open(jsonl) as f:
        first = json.loads(f.readline())
    print(f"Keys: {list(first.keys())[:15]}")
    cn = first.get("case_name", "?")
    jur = first.get("jurisdiction", "?")
    print(f"Case name: {cn}")
    print(f"Jurisdiction: {jur}")
    # Count total
    with open(jsonl) as f:
        total = sum(1 for _ in f)
    print(f"Total cases: {total}")
else:
    print("JSONL not found")

# Check PDFs
for name, label in [
    (r"c:\Users\reddy\Downloads\NLP Legal Summarizer\Indian Constitutition.pdf", "Indian Constitution"),
    (r"c:\Users\reddy\Downloads\NLP Legal Summarizer\uncharter.pdf", "UN Charter"),
    (r"c:\Users\reddy\Downloads\NLP Legal Summarizer\ccpr.pdf", "ICCPR"),
    (r"c:\Users\reddy\Downloads\NLP Legal Summarizer\cescr.pdf", "ICESCR"),
    (r"c:\Users\reddy\Downloads\NLP Legal Summarizer\International Law (Malcolm N. Shaw).pdf", "Shaw"),
]:
    p = Path(name)
    if p.exists():
        print(f"{label}: {p.stat().st_size / 1024 / 1024:.1f} MB")
    else:
        print(f"{label}: NOT FOUND")

# Check remote sources
rs = Path(r"c:\Users\reddy\Downloads\NLP Legal Summarizer\omnilegal\data\remote_sources")
if rs.exists():
    items = list(rs.rglob("*"))
    files = [f for f in items if f.is_file()]
    print(f"\nRemote sources dir: {len(files)} files")
    for f in files[:10]:
        print(f"  {f.relative_to(rs)} ({f.stat().st_size / 1024:.0f} KB)")
