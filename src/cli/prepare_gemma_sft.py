from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.data.corpus_catalog import iter_normalized_records


SYSTEM_PROMPT = (
    "You are OmniLegal, a careful legal research assistant for MUN and comparative law. "
    "Use the provided legal material, avoid inventing citations, and distinguish legal analysis from policy advice."
)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "..."


def _example_from_record(record, source_char_limit: int) -> dict | None:
    source = _truncate(record.text, source_char_limit)
    if len(source) < 50:
        return None

    if record.question and record.answer:
        user = (
            f"Answer this legal research question using the provided source material.\n\n"
            f"Question: {record.question}\n\n"
            f"Source material:\n{source}"
        )
        assistant = record.answer
    elif record.summary:
        user = (
            f"Prepare a concise legal research brief for this material.\n\n"
            f"Title: {record.title or record.source_repo}\n"
            f"Source material:\n{source}"
        )
        assistant = record.summary
        if record.labels:
            assistant += f"\n\nRelevant labels: {record.labels}"
    elif record.labels:
        user = (
            f"Identify the relevant legal classification labels for this material.\n\n"
            f"Title: {record.title or record.source_repo}\n"
            f"Source material:\n{source}"
        )
        assistant = record.labels
    else:
        return None

    assistant = _truncate(assistant, 3000)
    if len(assistant) < 20:
        return None

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
        "collection": record.collection,
        "source_repo": record.source_repo,
        "source_path": record.source_path,
        "task_family": record.task_family,
        "language": record.language,
    }


def main():
    parser = argparse.ArgumentParser(description="Prepare Gemma 4 SFT chat data from OmniLegal corpora.")
    parser.add_argument("--output", default="data/training/gemma4_sft.jsonl")
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--sample-limit-per-source", type=int, default=5000)
    parser.add_argument("--source-char-limit", type=int, default=5000)
    parser.add_argument("--include-summaries", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    with output.open("w", encoding="utf-8") as handle:
        for record in iter_normalized_records(
            sample_limit_per_source=args.sample_limit_per_source,
            include_summaries=args.include_summaries,
        ):
            if written >= args.limit:
                break
            example = _example_from_record(record, args.source_char_limit)
            if not example:
                skipped += 1
                continue
            handle.write(json.dumps(example, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} Gemma 4 SFT examples to {output}")
    print(f"Skipped {skipped} records without usable QA, summary, or labels")


if __name__ == "__main__":
    main()
