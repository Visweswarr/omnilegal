# OmniLegal Kaggle / Colab Training

## Recommended Reranker Choice

Use your own generated OmniLegal triples as the training dataset and fine-tune:

- Dataset repo: `YOUR_HF_USERNAME/omnilegal-reranker-triples`
- Base model: `BAAI/bge-reranker-v2-m3`
- Output model: `YOUR_HF_USERNAME/omnilegal-bge-reranker-v2-m3`
- Fallback for memory limits: `BAAI/bge-reranker-base`

This is the best first run for OmniLegal because the corpus is mixed English, EU multilingual, and Chinese legal material, and the app needs a second-stage reranker more than it needs another answer-generation LLM.

## Why This Model

`BAAI/bge-reranker-v2-m3` is the practical choice for the current repo:

- It is multilingual enough for `core_legal_en`, `eu_multilingual`, and `cn_legal`.
- It is compatible with `sentence-transformers` `CrossEncoderTrainer`.
- It can train on Kaggle/Colab with `max_length=512`, small batches, and gradient accumulation.
- It drops into the existing RAG architecture as a reranking layer after FAISS + BM25.

`Qwen/Qwen3-Reranker-0.6B` is a strong second experiment if you have better GPU access and time to add custom Qwen scoring/training code. It is not the first recommendation for this repo because it is less plug-and-play with the current CrossEncoder training path.

Reference links:

- `BAAI/bge-reranker-v2-m3`: https://huggingface.co/BAAI/bge-reranker-v2-m3
- `Qwen/Qwen3-Reranker-0.6B`: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- `sentence-transformers` CrossEncoder docs: https://www.sbert.net/docs/package_reference/cross_encoder/cross_encoder.html

## Step 1: Prepare The Local Dataset

Run this locally from `omnilegal` so the script can read the local legal repos:

```powershell
.\.venv\Scripts\python.exe -m src.cli.prepare_reranker_training `
  --output data/training/reranker_triples.jsonl `
  --limit 10000 `
  --sample-limit-per-source 5000
```

The JSONL rows contain:

```json
{"query": "...", "positive": "...", "negative": "...", "collection": "core_legal_en", "source_repo": "..."}
```

## Step 2: Upload To Hugging Face Dataset Repo

Use a private dataset repo unless you have verified every upstream license.

```python
!pip install -U datasets huggingface_hub
from huggingface_hub import login
from datasets import load_dataset

login()
dataset = load_dataset(
    "json",
    data_files="data/training/reranker_triples.jsonl",
    split="train",
)
dataset.push_to_hub("YOUR_HF_USERNAME/omnilegal-reranker-triples", private=True)
```

## Step 3: Train On Kaggle Or Colab

```bash
pip install -U "sentence-transformers>=5.0.0" datasets transformers accelerate huggingface_hub
```

Then run:

```bash
python -m src.training.train_reranker_colab \
  --dataset-id YOUR_HF_USERNAME/omnilegal-reranker-triples \
  --base-model BAAI/bge-reranker-v2-m3 \
  --hub-model-id YOUR_HF_USERNAME/omnilegal-bge-reranker-v2-m3 \
  --epochs 1 \
  --batch-size 2 \
  --gradient-accumulation-steps 4 \
  --max-length 512 \
  --fp16 \
  --private
```

If a free T4 runs out of memory, retry with:

```bash
python -m src.training.train_reranker_colab \
  --dataset-id YOUR_HF_USERNAME/omnilegal-reranker-triples \
  --base-model BAAI/bge-reranker-base \
  --hub-model-id YOUR_HF_USERNAME/omnilegal-bge-reranker-base \
  --epochs 1 \
  --batch-size 2 \
  --gradient-accumulation-steps 8 \
  --max-length 512 \
  --fp16 \
  --private
```

## Step 4: Evaluate Before Integrating

After training, rerun:

```powershell
.\.venv\Scripts\python.exe -m src.cli.retrieval_eval --limit 25
```

Only integrate the reranker into the Supreme Omni Model path if recall@10 and citation coverage improve against the baseline.

## Optional Gemma 4 Generator Track

Use Gemma 4 for answer generation and legal briefing style, not for reranking.

- Dataset repo: `YOUR_HF_USERNAME/omnilegal-gemma4-sft`
- Base model for free Colab/Kaggle first run: `google/gemma-4-E2B-it`
- Stronger base if memory allows: `google/gemma-4-E4B-it`
- Output model: `YOUR_HF_USERNAME/omnilegal-gemma-4-e2b-it`

Why not make Gemma 4 the reranker? Gemma 4 is a text-generation/reasoning model. It can write the final legal analysis after retrieval, but a cross-encoder reranker is still the right tool for ranking source passages.

Reference link:

- `google/gemma-4-E2B-it`: https://huggingface.co/google/gemma-4-E2B-it

Prepare Gemma 4 SFT data locally:

```powershell
.\.venv\Scripts\python.exe -m src.cli.prepare_gemma_sft `
  --output data/training/gemma4_sft.jsonl `
  --limit 5000 `
  --sample-limit-per-source 5000
```

Upload it to a private Hugging Face dataset:

```python
!pip install -U datasets huggingface_hub
from huggingface_hub import login
from datasets import load_dataset

login()
dataset = load_dataset(
    "json",
    data_files="data/training/gemma4_sft.jsonl",
    split="train",
)
dataset.push_to_hub("YOUR_HF_USERNAME/omnilegal-gemma4-sft", private=True)
```

Train with QLoRA on Kaggle or Colab:

```bash
pip install -U transformers accelerate datasets peft trl bitsandbytes huggingface_hub
```

```bash
python -m src.training.train_gemma4_sft_colab \
  --dataset-id YOUR_HF_USERNAME/omnilegal-gemma4-sft \
  --base-model google/gemma-4-E2B-it \
  --hub-model-id YOUR_HF_USERNAME/omnilegal-gemma-4-e2b-it \
  --epochs 1 \
  --batch-size 1 \
  --gradient-accumulation-steps 8 \
  --max-length 2048 \
  --private
```

If you have a better GPU and want the stronger variant:

```bash
python -m src.training.train_gemma4_sft_colab \
  --dataset-id YOUR_HF_USERNAME/omnilegal-gemma4-sft \
  --base-model google/gemma-4-E4B-it \
  --hub-model-id YOUR_HF_USERNAME/omnilegal-gemma-4-e4b-it \
  --epochs 1 \
  --batch-size 1 \
  --gradient-accumulation-steps 8 \
  --max-length 2048 \
  --private
```
