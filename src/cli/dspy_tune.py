"""DSPy tuning entry point for the jurisdiction analyzer."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment
load_environment()

from src.config import GROQ_API_KEY, GROQ_MODEL, OMNILEGAL_DIR, OMNILEGAL_DSPY_TRAIN_DATA, OMNILEGAL_DSPY_COMPILED_PATH

RESULTS_DIR = OMNILEGAL_DIR / "artifacts" / "dspy"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _score_prediction(prediction, expected) -> float:
    # Handle DSPy Typed output
    pred_c = str(prediction.conclusion).lower() if hasattr(prediction, "conclusion") else ""
    expected_c = str(expected.conclusion).lower() if hasattr(expected, "conclusion") else ""
    
    score = 0.0
    if pred_c == expected_c and expected_c != "":
        score += 0.5
        
    pred_app = str(prediction.application).lower() if hasattr(prediction, "application") else ""
    exp_app = str(expected.application).lower() if hasattr(expected, "application") else ""
    
    pred_terms = {w for w in pred_app.split() if len(w) > 3}
    exp_terms = {w for w in exp_app.split() if len(w) > 3}
    
    if exp_terms:
        score += 0.5 * (len(pred_terms & exp_terms) / len(exp_terms))

    return score


def _try_dspy_compile(rows: list[dict], optimizer: str, limit: int | None) -> dict:
    try:
        import dspy
        from dspy.teleprompt import BootstrapFewShotWithRandomSearch
    except ImportError as exc:
        return {"status": "dependency_missing", "error": f"{type(exc).__name__}: {exc}"}

    if not GROQ_API_KEY:
        return {"status": "missing_llm_key", "error": "GROQ_API_KEY is required for DSPy tuning."}

    from src.models.dspy_modules import get_jurisdiction_module
    
    try:
        lm = dspy.LM(f"groq/{GROQ_MODEL}", api_key=GROQ_API_KEY)
        dspy.configure(lm=lm)
    except Exception as exc:
        return {"status": "lm_config_failed", "error": f"{type(exc).__name__}: {exc}"}

    examples = []
    for row in (rows[:limit] if limit else rows):
        try:
            ex = dspy.Example(
                jurisdiction=row.get("jurisdiction", ""),
                question=row.get("question", ""),
                context=row.get("context", ""),
                applicable_rules=row.get("applicable_rules", ""),
                application=row.get("application", ""),
                conclusion=row.get("conclusion", ""),
                conditions_if_any=row.get("conditions_if_any", ""),
                confidence=row.get("confidence", 0.0),
            ).with_inputs("jurisdiction", "question", "context")
            examples.append(ex)
        except Exception:
            continue

    if not examples:
        return {
            "status": "no_supervised_examples",
            "compiled": False,
            "error": "The eval set must contain jurisdiction, question, context, application, and conclusion.",
        }

    module = get_jurisdiction_module()()

    try:
        kwargs = dict(metric=_score_prediction)
        try:
            from dspy.teleprompt import MIPROv2
            if optimizer == "miprov2":
                optimizer_obj = MIPROv2(**kwargs)
            else:
                optimizer_obj = BootstrapFewShotWithRandomSearch(**kwargs)
        except ImportError:
            # Fall back if MIPROv2 not available
            optimizer_obj = BootstrapFewShotWithRandomSearch(**kwargs)

        compiled = optimizer_obj.compile(module, trainset=examples[: max(1, min(len(examples), 8))])
        
        # Save artifact
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out_path = Path(OMNILEGAL_DSPY_COMPILED_PATH)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        compiled.save(str(out_path))
        
        return {
            "status": "compiled",
            "compiled": True,
            "optimizer_class": type(optimizer_obj).__name__,
            "module_class": type(compiled).__name__,
            "train_examples": len(examples),
            "artifact_saved_to": str(out_path),
        }
    except Exception as exc:
        return {
            "status": "compile_failed",
            "compiled": False,
            "error": f"{type(exc).__name__}: {exc}",
            "train_examples": len(examples),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tune OmniLegal DSPy modules against the local eval set.")
    parser.add_argument("--optimizer", default="miprov2", choices=["miprov2", "bootstrap_fewshot_random_search"])
    parser.add_argument("--train-set", default=OMNILEGAL_DSPY_TRAIN_DATA)
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    eval_path = Path(args.train_set)
    rows = _load_jsonl(eval_path)
    payload = {
        "status": "completed" if rows else "missing_eval_set",
        "optimizer": args.optimizer,
        "eval_set": str(eval_path),
        "eval_rows": len(rows),
    }
    
    if rows:
        payload["dspy"] = _try_dspy_compile(rows, args.optimizer, args.limit)
    else:
        payload["next_step"] = "Create a JSONL eval set with typed output fields."

    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
