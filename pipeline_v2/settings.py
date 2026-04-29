"""Central settings for pipeline_v2 — loads .env once and exposes config."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path("/app")
ENV_PATH = ROOT / ".env"
if ENV_PATH.exists():
    load_dotenv(ENV_PATH, override=False)

# Storage paths
DATA_DIR = ROOT / "data"
QDRANT_DIR = DATA_DIR / "qdrant_v2"
CORPUS_DIR = DATA_DIR / "corpus_v2"
TRACE_DIR = DATA_DIR / "traces"
for path in (DATA_DIR, QDRANT_DIR, CORPUS_DIR, TRACE_DIR):
    path.mkdir(parents=True, exist_ok=True)

# API keys
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

# Models
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_MODEL_FALLBACK = os.getenv("GROQ_MODEL_FALLBACK", "llama-3.1-8b-instant")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
)

# Embedding (FastEmbed default, small, fast, no torch required)
EMBED_MODEL = os.getenv("EMBED_MODEL_V2", "BAAI/bge-small-en-v1.5")
EMBED_DIM = 384  # bge-small-en-v1.5 dimension

# Retrieval
TOP_K_DENSE = int(os.getenv("TOP_K_DENSE", "12"))
TOP_K_FINAL = int(os.getenv("TOP_K_FINAL", "8"))
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.30"))

# Generation
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "1800"))

# Legal disclaimer
DISCLAIMER = (
    "_This is not legal advice. Outputs may contain errors — verify every citation "
    "against the original source before acting. Consult a qualified lawyer in the "
    "relevant jurisdiction._"
)
