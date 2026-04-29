from __future__ import annotations

import json
from pathlib import Path

from src.schemas import EvaluationArtifact, EvaluationMetric


EVALUATION_DIR = Path(__file__).parent.parent.parent / "data" / "evaluation"


def _safe_mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _macro_f1(gold: list[str], predicted: list[str]) -> float | None:
    labels = sorted(set(gold) | set(predicted))
    if not labels:
        return None

    f1_scores = []
    for label in labels:
        tp = sum(1 for g, p in zip(gold, predicted) if g == label and p == label)
        fp = sum(1 for g, p in zip(gold, predicted) if g != label and p == label)
        fn = sum(1 for g, p in zip(gold, predicted) if g == label and p != label)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        if precision + recall == 0:
            f1_scores.append(0.0)
        else:
            f1_scores.append(2 * precision * recall / (precision + recall))
    return _safe_mean(f1_scores)


def evaluate_records(records: list[dict], task: str, benchmark: str, split: str) -> EvaluationArtifact:
    artifact = EvaluationArtifact(task=task, benchmark=benchmark, split=split)

    predictions = [record["prediction"] for record in records if "prediction" in record and "reference" in record]
    references = [record["reference"] for record in records if "prediction" in record and "reference" in record]

    if predictions and references:
        from rouge_score import rouge_scorer

        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
        rouge_scores = [scorer.score(ref, pred)["rougeL"].fmeasure for pred, ref in zip(predictions, references)]
        artifact.metrics.append(EvaluationMetric(name="rougeL", value=_safe_mean(rouge_scores)))

        try:
            from bert_score import score as bert_score

            _, _, bert_f1 = bert_score(predictions, references, lang="en", verbose=False)
            artifact.metrics.append(
                EvaluationMetric(name="bertscore_f1", value=float(bert_f1.mean().item()))
            )
        except Exception as exc:
            artifact.metrics.append(
                EvaluationMetric(name="bertscore_f1", value=None, notes=f"Unavailable: {exc}")
            )

    gold_labels = [record["gold_label"] for record in records if "gold_label" in record and "predicted_label" in record]
    predicted_labels = [record["predicted_label"] for record in records if "gold_label" in record and "predicted_label" in record]
    macro_f1 = _macro_f1(gold_labels, predicted_labels)
    if macro_f1 is not None:
        artifact.metrics.append(EvaluationMetric(name="macro_f1", value=macro_f1))

    citation_precisions = []
    retrieval_recalls = []
    manual_legaleval = []
    for record in records:
        gold_citations = set(record.get("gold_citations", []))
        predicted_citations = set(record.get("predicted_citations", []))
        if predicted_citations:
            citation_precisions.append(len(gold_citations & predicted_citations) / len(predicted_citations))

        gold_ids = set(record.get("gold_ids", []))
        retrieved_ids = set(record.get("retrieved_ids", []))
        if gold_ids:
            retrieval_recalls.append(len(gold_ids & retrieved_ids) / len(gold_ids))

        if "legaleval_q" in record and record["legaleval_q"] is not None:
            manual_legaleval.append(float(record["legaleval_q"]))

    if citation_precisions:
        artifact.metrics.append(
            EvaluationMetric(name="citation_precision", value=_safe_mean(citation_precisions))
        )
    if retrieval_recalls:
        artifact.metrics.append(
            EvaluationMetric(name="retrieval_recall", value=_safe_mean(retrieval_recalls))
        )
    if manual_legaleval:
        artifact.metrics.append(
            EvaluationMetric(name="legal_eval_q", value=_safe_mean(manual_legaleval))
        )

    return artifact


def save_evaluation_artifact(artifact: EvaluationArtifact, output_path: str | Path | None = None) -> Path:
    EVALUATION_DIR.mkdir(parents=True, exist_ok=True)
    if output_path is None:
        safe_task = artifact.task.replace(" ", "_")
        safe_split = artifact.split.replace(" ", "_")
        output_path = EVALUATION_DIR / f"{safe_task}_{safe_split}.json"
    else:
        output_path = Path(output_path)

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(artifact.model_dump(), handle, indent=2)
    return output_path


def load_latest_evaluation_artifact() -> EvaluationArtifact | None:
    if not EVALUATION_DIR.exists():
        return None

    artifacts = sorted(
        EVALUATION_DIR.glob("*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not artifacts:
        return None

    with artifacts[0].open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return EvaluationArtifact(**payload)
