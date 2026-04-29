from __future__ import annotations

import json
from pathlib import Path

from src.adapters.donor_registry import build_provenance
from src.adapters.retrieval_patterns import retrieval_ids_for_passages
from src.data.registry import get_datasets_for_task
from src.schemas import BenchmarkRun, EvaluationArtifact, EvaluationMetric
from src.services.argument_mining import build_argument_map
from src.services.brief_generation import generate_issue_brief
from src.services.conflict_detection import analyze_conflict
from src.services.evaluation import evaluate_records, save_evaluation_artifact
from src.services.retrieval_qa import answer_question
from src.services.stance_prediction import predict_indian_stance


GOLD_DIR = Path(__file__).resolve().parents[2] / "data" / "gold"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_conflict_benchmark(limit: int | None = None) -> BenchmarkRun:
    rows = _load_jsonl(GOLD_DIR / "conflict_gold.jsonl")
    if limit is not None:
        rows = rows[:limit]

    records = []
    for row in rows:
        result = analyze_conflict(
            row.get("indian_provision", ""),
            row.get("international_provision"),
        )
        records.append(
            {
                "gold_label": row.get("label"),
                "predicted_label": result.label,
            }
        )

    artifact = evaluate_records(records, task="conflict_detection", benchmark="manual_conflict_gold", split="smoke")
    artifact.provenance = build_provenance("retrieval", usage_mode="runtime", donor_ids=["clerc", "lleqa", "bsard"])
    save_evaluation_artifact(artifact, output_path=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "conflict_smoke.json")
    return BenchmarkRun(
        task="conflict_detection",
        title="Conflict Smoke Benchmark",
        status="completed",
        datasets=["manual_conflict_gold"],
        summary=f"Ran {len(records)} local conflict examples.",
        artifact=artifact,
        provenance=artifact.provenance,
    )


def run_stance_benchmark(limit: int | None = None) -> BenchmarkRun:
    rows = _load_jsonl(GOLD_DIR / "stance_gold.jsonl")
    if limit is not None:
        rows = rows[:limit]

    records = []
    for row in rows:
        result = predict_indian_stance(row.get("issue", ""))
        records.append(
            {
                "gold_label": row.get("stance_label"),
                "predicted_label": result.stance_label,
                "predicted_citations": [citation.source_name for citation in result.top_domestic_authorities],
                "gold_citations": row.get("top_authorities", []),
            }
        )

    artifact = evaluate_records(records, task="stance_prediction", benchmark="manual_stance_gold", split="smoke")
    artifact.provenance = build_provenance(
        "stance_prior",
        usage_mode="evaluation",
        donor_ids=["indian_bail_judgments_1200"],
    )
    save_evaluation_artifact(artifact, output_path=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "stance_smoke.json")
    return BenchmarkRun(
        task="stance_prediction",
        title="India Stance Smoke Benchmark",
        status="completed",
        datasets=["manual_stance_gold"],
        summary=f"Ran {len(records)} local stance examples.",
        artifact=artifact,
        provenance=artifact.provenance,
    )


def run_qa_smoke_benchmark() -> BenchmarkRun:
    prompts = [
        "How does India's domestic framework interact with ICCPR Article 19?",
        "What is the Corfu Channel case?",
    ]
    records = []
    for prompt in prompts:
        result = answer_question(prompt, use_groq=False)
        retrieved_ids = retrieval_ids_for_passages(result.sources)
        records.append(
            {
                "predicted_citations": [citation.source_name for citation in result.citations],
                "retrieved_ids": retrieved_ids,
                "has_answer": bool(result.answer.strip()),
                "comparative": result.comparative,
            }
        )

    artifact = EvaluationArtifact(
        task="qa",
        benchmark="local_smoke_queries",
        split="smoke",
        metrics=[
            EvaluationMetric(
                name="answer_with_citation_rate",
                value=sum(1 for record in records if record["predicted_citations"]) / len(records),
            ),
            EvaluationMetric(
                name="comparative_query_detection_rate",
                value=sum(1 for record in records if record["comparative"]) / len(records),
            ),
        ],
        notes=[
            "This is a structural smoke benchmark, not a full IndicLegalQA evaluation.",
            "Full QA benchmark datasets remain registry-backed and offline by default.",
        ],
        provenance=build_provenance(
            "long_form_qa",
            usage_mode="runtime",
            donor_ids=["lleqa"],
        )
        + build_provenance("retrieval", usage_mode="reference", donor_ids=["clerc", "bsard"]),
    )
    save_evaluation_artifact(artifact, output_path=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "qa_smoke.json")
    return BenchmarkRun(
        task="qa",
        title="Legal QA Smoke Benchmark",
        status="completed",
        datasets=["project_local_corpus"],
        summary="Ran a small local citation/structure QA smoke benchmark.",
        artifact=artifact,
        provenance=artifact.provenance,
    )


def run_brief_benchmark(limit: int | None = None) -> BenchmarkRun:
    rows = _load_jsonl(GOLD_DIR / "brief_eval.jsonl")
    if limit is not None:
        rows = rows[:limit]

    if not rows:
        rows = [{"issue": "Use of force and humanitarian access in Gaza."}]

    completeness = []
    citation_backing = []
    for row in rows:
        result = generate_issue_brief(row.get("issue", ""))
        headings = {section.heading for section in result.sections}
        required = {
            "Issue",
            "International Obligations",
            "Indian Domestic Position",
            "Conflict or Alignment",
            "Predicted Indian Stance",
            "Suggested MUN Talking Points",
            "Citations",
        }
        completeness.append(len(required & headings) / len(required))
        citation_backing.append(1.0 if result.citations else 0.0)

    artifact = EvaluationArtifact(
        task="brief_generation",
        benchmark="manual_brief_eval",
        split="smoke",
        metrics=[
            EvaluationMetric(name="section_completeness", value=sum(completeness) / len(completeness)),
            EvaluationMetric(name="citation_backed_brief_rate", value=sum(citation_backing) / len(citation_backing)),
        ],
        notes=[
            "This is a local structure/citation smoke benchmark.",
            "Manual usefulness and faithfulness review remains required for release-quality brief evaluation.",
        ],
        provenance=build_provenance(
            "summarization",
            usage_mode="runtime",
            donor_ids=["summarization"],
        ),
    )
    save_evaluation_artifact(artifact, output_path=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "brief_smoke.json")
    return BenchmarkRun(
        task="brief_generation",
        title="Brief Generation Smoke Benchmark",
        status="completed",
        datasets=["manual_brief_eval"],
        summary=f"Checked brief completeness and citation coverage on {len(rows)} issue(s).",
        artifact=artifact,
        provenance=artifact.provenance,
    )


def run_argument_benchmark(limit: int | None = None) -> BenchmarkRun:
    rows = _load_jsonl(GOLD_DIR / "brief_eval.jsonl")
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        rows = [{"issue": "India and humanitarian intervention"}]

    counts = []
    cited_span_rates = []
    for row in rows:
        argument_map = build_argument_map(row.get("issue", ""))
        counts.append(len(argument_map.spans))
        cited_span_rates.append(
            sum(1 for span in argument_map.spans if span.citation is not None) / max(1, len(argument_map.spans))
        )

    artifact = EvaluationArtifact(
        task="argument_mining",
        benchmark="manual_argument_smoke",
        split="smoke",
        metrics=[
            EvaluationMetric(name="avg_argument_spans", value=sum(counts) / len(counts)),
            EvaluationMetric(name="cited_span_rate", value=sum(cited_span_rates) / len(cited_span_rates)),
        ],
        notes=[
            "This is a structural smoke benchmark for Debate Coach argument extraction.",
            "RMU:ECHR remains registry-backed for richer offline evaluation.",
        ],
        provenance=build_provenance(
            "argument_mining",
            usage_mode="runtime",
            donor_ids=["mining_legal_arguments"],
        ),
    )
    save_evaluation_artifact(artifact, output_path=Path(__file__).resolve().parents[2] / "data" / "evaluation" / "argument_smoke.json")
    return BenchmarkRun(
        task="argument_mining",
        title="Argument Mining Smoke Benchmark",
        status="completed",
        datasets=["manual_brief_eval"],
        summary=f"Checked debate span extraction on {len(rows)} issue(s).",
        artifact=artifact,
        provenance=artifact.provenance,
    )


def list_benchmark_runs() -> list[BenchmarkRun]:
    return [
        BenchmarkRun(
            task="qa",
            title="Legal QA Benchmark Coverage",
            status="ready",
            datasets=[record.dataset_id for record in get_datasets_for_task("qa")],
            summary="Registry-backed QA and retrieval evaluation coverage is configured.",
            notes=["Use smoke benchmarks locally and full dataset benchmarks offline."],
            provenance=build_provenance("long_form_qa", usage_mode="evaluation", donor_ids=["lleqa"]),
        ),
        BenchmarkRun(
            task="brief_generation",
            title="Brief Generation Benchmark Coverage",
            status="ready",
            datasets=[record.dataset_id for record in get_datasets_for_task("brief_generation")],
            summary="Summarization and brief-generation datasets are registered for training and evaluation.",
            provenance=build_provenance("summarization", usage_mode="evaluation", donor_ids=["summarization"]),
        ),
        BenchmarkRun(
            task="argument_mining",
            title="Argument Mining Benchmark Coverage",
            status="ready",
            datasets=[record.dataset_id for record in get_datasets_for_task("argument_mining")],
            summary="Argument-mining donor coverage is registered for debate-support evaluation.",
            provenance=build_provenance("argument_mining", usage_mode="evaluation", donor_ids=["mining_legal_arguments"]),
        ),
    ]
