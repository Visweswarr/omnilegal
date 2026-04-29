from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_DATASET_ID = "YOUR_HF_USERNAME/omnilegal-reranker-triples"
DEFAULT_OUTPUT_MODEL_ID = "YOUR_HF_USERNAME/omnilegal-bge-reranker-v2-m3"
DEFAULT_BASE_MODEL = "BAAI/bge-reranker-v2-m3"
FALLBACK_BASE_MODEL = "BAAI/bge-reranker-base"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Train the OmniLegal reranker on Kaggle or Google Colab."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id", help="Hugging Face dataset id with query/positive/negative columns.")
    source.add_argument("--jsonl", help="Local JSONL file with query/positive/negative columns.")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output-dir", default="omni-reranker")
    parser.add_argument("--hub-model-id", default=None, help="Optional Hugging Face model id to push after training.")
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--eval-size", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--fp16", action="store_true", help="Use fp16 on T4/V100/A100 GPUs.")
    parser.add_argument("--private", action="store_true", help="Push the model as a private Hub repo.")
    return parser.parse_args()


def load_triples(args):
    from datasets import load_dataset

    if args.dataset_id:
        return load_dataset(args.dataset_id, split="train")
    path = Path(args.jsonl)
    return load_dataset("json", data_files=str(path), split="train")


def build_pair_dataset(triples):
    from datasets import Dataset

    pairs = []
    for item in triples:
        query = str(item.get("query", "")).strip()
        positive = str(item.get("positive", "")).strip()
        negative = str(item.get("negative", "")).strip()
        if query and positive:
            pairs.append({"sentence1": query, "sentence2": positive, "label": 1.0})
        if query and negative:
            pairs.append({"sentence1": query, "sentence2": negative, "label": 0.0})
    if not pairs:
        raise ValueError("No usable training pairs found. Expected query, positive, and negative fields.")
    return Dataset.from_list(pairs)


def main():
    args = parse_args()

    from huggingface_hub import HfApi, create_repo
    from sentence_transformers import CrossEncoder
    from sentence_transformers.cross_encoder import CrossEncoderTrainer, CrossEncoderTrainingArguments
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

    triples = load_triples(args)
    pairs = build_pair_dataset(triples)

    eval_dataset = None
    train_dataset = pairs
    if args.eval_size > 0 and len(pairs) >= 100:
        split = pairs.train_test_split(test_size=args.eval_size, seed=args.seed)
        train_dataset = split["train"]
        eval_dataset = split["test"]

    model = CrossEncoder(args.base_model, num_labels=1, max_length=args.max_length)
    loss = BinaryCrossEntropyLoss(model)

    training_args = CrossEncoderTrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        warmup_ratio=args.warmup_ratio,
        fp16=args.fp16,
        logging_steps=25,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset is not None else "no",
        report_to="none",
        push_to_hub=False,
        seed=args.seed,
    )

    trainer = CrossEncoderTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        loss=loss,
    )
    trainer.train()

    model.save_pretrained(args.output_dir)
    if args.hub_model_id:
        create_repo(
            repo_id=args.hub_model_id,
            repo_type="model",
            private=args.private,
            exist_ok=True,
        )
        HfApi().upload_folder(
            folder_path=args.output_dir,
            repo_id=args.hub_model_id,
            repo_type="model",
            commit_message="Upload trained OmniLegal reranker",
        )


if __name__ == "__main__":
    main()
