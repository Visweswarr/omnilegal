"""Scan MORE HuggingFace legal datasets."""
from datasets import load_dataset_builder
import os
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

targets = [
    # India
    ("Peeradon/Indian_Legal_Cases", None),
    ("suyash012/Indian-Supreme-Court-Judgements", None),
    ("kiddothe2b/legal_pile_india", None),
    ("AI4Bharat/IN-Abs", None),
    # EU
    ("joelito/MultiEURLEX", None),
    ("coastalcph/multi_eurlex", None),
    ("rcds/eu_court_cases", None),
    ("EuropeanParliament/Europarl-Debates", None),
    # UK
    ("pile-of-law/uk-legislation", None),
    # International
    ("nguha/legalbench", None),
    ("allenai/WildBench", None),
    # General legal
    ("theatticfoundation/legal_contracts", None),
    ("casehold/casehold", None),
    ("lighteval/legal_summarization", None),
]

for name, config in targets:
    try:
        kwargs = {"name": config} if config else {}
        builder = load_dataset_builder(name, **kwargs)
        size = builder.info.download_size
        size_str = f"{size / 1024**2:.0f} MB" if size else "unknown"
        desc = (builder.info.description or "")[:150]
        splits = list((builder.info.splits or {}).keys())
        label = f"{name}/{config}" if config else name
        print(f"OK: {label} ({size_str}) splits={splits}")
        if desc:
            print(f"    {desc}")
    except Exception as e:
        err = str(e)[:120]
        label = f"{name}/{config}" if config else name
        print(f"FAIL: {label}")
    print()
