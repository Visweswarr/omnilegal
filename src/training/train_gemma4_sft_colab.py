from __future__ import annotations

import argparse
from pathlib import Path


DEFAULT_DATASET_ID = "YOUR_HF_USERNAME/omnilegal-gemma4-sft"
DEFAULT_BASE_MODEL = "google/gemma-4-E2B-it"
STRONGER_BASE_MODEL = "google/gemma-4-E4B-it"
DEFAULT_OUTPUT_MODEL_ID = "YOUR_HF_USERNAME/omnilegal-gemma-4-e2b-it"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fine-tune Gemma 4 for OmniLegal answer generation on Kaggle or Colab."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dataset-id", help="Hugging Face dataset id with a messages column.")
    source.add_argument("--jsonl", help="Local JSONL file with a messages column.")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output-dir", default="omni-gemma4-sft")
    parser.add_argument("--hub-model-id", default=None)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-4)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--eval-size", type=float, default=0.03)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--no-4bit", action="store_true", help="Disable 4-bit QLoRA loading.")
    parser.add_argument("--bf16", action="store_true", help="Use bf16 instead of fp16 when supported.")
    parser.add_argument("--private", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def load_messages_dataset(args):
    from datasets import load_dataset

    if args.dataset_id:
        return load_dataset(args.dataset_id, split="train")
    return load_dataset("json", data_files=str(Path(args.jsonl)), split="train")


def main():
    args = parse_args()

    import torch
    from huggingface_hub import HfApi, create_repo
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoProcessor, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    dataset = load_messages_dataset(args)
    processor = AutoProcessor.from_pretrained(args.base_model)

    def to_text(example):
        messages = example["messages"]
        try:
            text = processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
                enable_thinking=False,
            )
        except TypeError:
            text = processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=False,
            )
        return {"text": text}

    dataset = dataset.map(to_text, remove_columns=[col for col in dataset.column_names if col != "messages"])
    if "messages" in dataset.column_names:
        dataset = dataset.remove_columns(["messages"])

    eval_dataset = None
    train_dataset = dataset
    if args.eval_size > 0 and len(dataset) >= 100:
        split = dataset.train_test_split(test_size=args.eval_size, seed=args.seed)
        train_dataset = split["train"]
        eval_dataset = split["test"]

    dtype = torch.bfloat16 if args.bf16 else torch.float16
    quantization_config = None
    if not args.no_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=dtype,
            bnb_4bit_use_double_quant=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        args.base_model,
        device_map="auto",
        torch_dtype=dtype,
        quantization_config=quantization_config,
    )

    peft_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj.linear",
            "k_proj.linear",
            "v_proj.linear",
            "o_proj.linear",
            "gate_proj.linear",
            "up_proj.linear",
            "down_proj.linear",
        ],
    )

    training_args = SFTConfig(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation_steps,
        learning_rate=args.learning_rate,
        max_length=args.max_length,
        packing=False,
        logging_steps=10,
        save_strategy="epoch",
        eval_strategy="epoch" if eval_dataset is not None else "no",
        report_to="none",
        push_to_hub=False,
        seed=args.seed,
    )

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        peft_config=peft_config,
    )
    trainer.train()

    trainer.save_model(args.output_dir)
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
            commit_message="Upload trained OmniLegal Gemma 4 adapter",
        )


if __name__ == "__main__":
    main()
