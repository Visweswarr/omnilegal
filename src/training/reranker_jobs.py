from __future__ import annotations

import json
from pathlib import Path


DEFAULT_RERANKER_BASE = "BAAI/bge-reranker-v2-m3"
FALLBACK_RERANKER_BASE = "BAAI/bge-reranker-base"


def build_hf_jobs_reranker_script(
    *,
    dataset_repo_id: str,
    hub_model_id: str,
    base_model: str = DEFAULT_RERANKER_BASE,
    epochs: int = 1,
    batch_size: int = 8,
) -> str:
    """
    Return a self-contained UV script for Hugging Face Jobs. The script expects
    a Hub dataset with a train split containing query, positive, and negative
    string columns.
    """
    return f'''# /// script
# dependencies = ["datasets", "sentence-transformers>=3.0.0", "transformers", "huggingface-hub", "trackio"]
# ///

from datasets import Dataset, load_dataset
from sentence_transformers import CrossEncoder
from sentence_transformers.cross_encoder import CrossEncoderTrainer, CrossEncoderTrainingArguments
from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss
import trackio

dataset = load_dataset({dataset_repo_id!r}, split="train")
pairs = Dataset.from_list(
    [
        {{"sentence1": item["query"], "sentence2": item["positive"], "label": 1.0}}
        for item in dataset
    ]
    + [
        {{"sentence1": item["query"], "sentence2": item["negative"], "label": 0.0}}
        for item in dataset
    ]
)
model = CrossEncoder({base_model!r}, num_labels=1)
loss = BinaryCrossEntropyLoss(model)

args = CrossEncoderTrainingArguments(
    output_dir="omni-reranker",
    num_train_epochs={epochs},
    per_device_train_batch_size={batch_size},
    learning_rate=2e-5,
    warmup_ratio=0.1,
    logging_steps=10,
    save_strategy="epoch",
    report_to="trackio",
    push_to_hub=True,
    hub_model_id={hub_model_id!r},
)

trainer = CrossEncoderTrainer(
    model=model,
    args=args,
    train_dataset=pairs,
    loss=loss,
)
trainer.train()
trainer.push_to_hub()
'''


def write_hf_jobs_payload(
    output_path: str | Path,
    *,
    dataset_repo_id: str,
    hub_model_id: str,
    base_model: str = DEFAULT_RERANKER_BASE,
    flavor: str = "a10g-large",
    timeout: str = "2h",
) -> Path:
    script = build_hf_jobs_reranker_script(
        dataset_repo_id=dataset_repo_id,
        hub_model_id=hub_model_id,
        base_model=base_model,
    )
    payload = {
        "tool": "hf_jobs",
        "mode": "uv",
        "job": {
            "script": script,
            "flavor": flavor,
            "timeout": timeout,
            "secrets": {"HF_TOKEN": "$HF_TOKEN"},
        },
        "notes": [
            "Submit this only after retrieval baseline evaluation shows a reranker gap.",
            "HF Jobs require a paid Hugging Face plan and a write-capable HF token.",
            "The dataset must be on the Hub with columns: query, positive, negative.",
        ],
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output
