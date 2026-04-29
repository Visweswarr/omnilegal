from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.data.corpus_catalog import iter_normalized_records
from src.training.reranker_jobs import write_hf_jobs_payload


def _query_for_record(record) -> str:
    return record.question or record.summary or record.title or record.text[:240]


def main():
    parser = argparse.ArgumentParser(description="Prepare OmniLegal reranker training triples.")
    parser.add_argument("--output", default="data/training/reranker_triples.jsonl")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--sample-limit-per-source", type=int, default=500)
    parser.add_argument("--hf-dataset-id", default=None, help="Hub dataset id for generated HF Jobs payload")
    parser.add_argument("--hub-model-id", default=None, help="Hub model id for generated HF Jobs payload")
    args = parser.parse_args()

    records = [
        record for record in iter_normalized_records(
            sample_limit_per_source=args.sample_limit_per_source,
            include_summaries=False,
        )
        if len(_query_for_record(record).strip()) >= 20 and len(record.text.strip()) >= 50
    ]

    triples = []
    for index, record in enumerate(records[: args.limit]):
        negative = next(
            (
                candidate
                for candidate in records[index + 1 :] + records[:index]
                if candidate.source_repo != record.source_repo
            ),
            None,
        )
        if negative is None:
            continue
        triples.append(
            {
                "query": _query_for_record(record),
                "positive": record.text,
                "negative": negative.text,
                "positive_id": record.id,
                "negative_id": negative.id,
                "collection": record.collection,
                "source_repo": record.source_repo,
            }
        )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for triple in triples:
            handle.write(json.dumps(triple, ensure_ascii=False) + "\n")
    print(f"Wrote {len(triples)} reranker triples to {output}")

    if args.hf_dataset_id and args.hub_model_id:
        payload_path = output.with_suffix(".hf_jobs_payload.json")
        write_hf_jobs_payload(
            payload_path,
            dataset_repo_id=args.hf_dataset_id,
            hub_model_id=args.hub_model_id,
        )
        print(f"Wrote HF Jobs payload template to {payload_path}")


if __name__ == "__main__":
    main()
