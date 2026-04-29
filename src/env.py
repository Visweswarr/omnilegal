"""Shared environment bootstrap for all OmniLegal entry points."""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def project_paths() -> tuple[Path, Path]:
    omnilegal_dir = Path(__file__).resolve().parents[1]
    root_dir = omnilegal_dir.parent
    return root_dir, omnilegal_dir


def load_environment() -> None:
    """Load .env before any Hugging Face, LLM, or Qdrant client is created."""
    global _LOADED
    if _LOADED:
        return

    root_dir, omnilegal_dir = project_paths()
    env_paths = [
        omnilegal_dir / ".env",
        root_dir / ".env",
        Path.cwd() / ".env",
    ]
    try:
        from dotenv import load_dotenv

        for path in env_paths:
            if path.exists():
                load_dotenv(path, override=True)
    except Exception:
        pass

    hf_token = os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN")
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)

    openrouter_token = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_token:
        os.environ.setdefault("OPENAI_API_KEY", openrouter_token)
        os.environ.setdefault("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    # Backfill GOVINFO_API_KEY and CONGRESS_API_KEY from DATAGOV_API_KEY
    datagov = os.getenv("DATAGOV_API_KEY", "")
    if datagov:
        os.environ.setdefault("GOVINFO_API_KEY", datagov)
        os.environ.setdefault("CONGRESS_API_KEY", datagov)

    # Backfill INDIAN_KANOON_API_TOKEN from legacy INDIAN_KANOON_API_KEY
    ik_key = os.getenv("INDIAN_KANOON_API_KEY", "")
    if ik_key:
        os.environ.setdefault("INDIAN_KANOON_API_TOKEN", ik_key)

    _LOADED = True
