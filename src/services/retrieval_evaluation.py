from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.data.corpus_catalog import iter_normalized_records
from src.rag.retriever import search_documents
from src.schemas import EvaluationArtifact, EvaluationMetric


def build_retrieval_eval_records(limit: int = 50) -> list[dict[str, Any]]:
    """Create lightweight retrieval eval records from normalized local corpora."""
    records: list[dict[str, Any]] = []
    for record in iter_normalized_records(sample_limit_per_source=limit, include_summaries=False):
        query = record.question or record.summary or record.title
        if not query or len(query.strip()) < 20:
            continue
        records.append(
            {
                "query": query,
                "record_id": record.id,
                "source_repo": record.source_repo,
                "collection": record.collection,
                "language": record.language,
                "jurisdiction": record.jurisdiction,
            }
        )
        if len(records) >= limit:
            break
    return records


def evaluate_retrieval_baseline(
    records: list[dict[str, Any]] | None = None,
    *,
    limit: int = 25,
    collections: list[str] | None = None,
) -> EvaluationArtifact:
    eval_records = records or build_retrieval_eval_records(limit=limit)
    if limit:
        eval_records = eval_records[:limit]

    if not eval_records:
        return EvaluationArtifact(
            task="retrieval",
            benchmark="all_corpus_smoke",
            split="smoke",
            generated_at=datetime.now(timezone.utc).isoformat(),
            metrics=[EvaluationMetric(name="records", value=0.0)],
            notes=["No retrieval evaluation records could be generated."],
        )

    hits_at_5 = 0
    hits_at_10 = 0
    citation_coverage = 0
    source_diversity: set[str] = set()

    for record in eval_records:
        docs = search_documents(
            record["query"],
            k=10,
            collections=collections or [record["collection"]],
            source_repo=record["source_repo"],
        )
        source_diversity.update(str(doc.metadata.get("source_repo", "")) for doc in docs)
        ranked_record_ids = [str(doc.metadata.get("record_id", "")) for doc in docs]
        if any(record["record_id"] in item for item in ranked_record_ids[:5]):
            hits_at_5 += 1
        if any(record["record_id"] in item for item in ranked_record_ids[:10]):
            hits_at_10 += 1
        if any(doc.metadata.get("source_name") or doc.metadata.get("source_path") for doc in docs):
            citation_coverage += 1

    total = len(eval_records)
    return EvaluationArtifact(
        task="retrieval",
        benchmark="all_corpus_smoke",
        split="smoke",
        generated_at=datetime.now(timezone.utc).isoformat(),
        metrics=[
            EvaluationMetric(name="records", value=float(total)),
            EvaluationMetric(name="recall_at_5", value=hits_at_5 / total),
            EvaluationMetric(name="recall_at_10", value=hits_at_10 / total),
            EvaluationMetric(name="citation_coverage", value=citation_coverage / total),
            EvaluationMetric(name="source_diversity", value=float(len(source_diversity))),
        ],
        notes=[
            "Smoke retrieval eval generated from normalized local records.",
            "Run this before deciding whether to launch reranker adapter training.",
        ],
    )
