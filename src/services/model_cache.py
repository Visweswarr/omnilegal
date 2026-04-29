"""Hugging Face model cache and Phase 4 prewarm helpers."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.env import load_environment

load_environment()

from src.config import CLASSIFIER_MODEL, EMBED_MODEL, GLINER_MODEL, NLI_MODEL, OMNILEGAL_DIR, RERANKER_MODEL


def hf_model_cache_path(model_name: str) -> Path:
    cache_root = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return cache_root / "hub" / f"models--{model_name.replace('/', '--')}"


def hf_model_cache_exists(model_name: str) -> bool:
    return hf_model_cache_path(model_name).exists()


def isolated_gliner_python() -> Path:
    return OMNILEGAL_DIR / ".venv-gliner" / "Scripts" / "python.exe"


def isolated_gliner_available(timeout: int = 20) -> dict[str, Any]:
    python_exe = isolated_gliner_python()
    if not python_exe.exists():
        return {"ok": False, "mode": "missing_venv", "python": str(python_exe)}
    try:
        proc = subprocess.run(
            [
                str(python_exe),
                "-c",
                "from gliner import GLiNER; import json; print(json.dumps({'ok': True}))",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": proc.returncode == 0,
            "mode": "isolated",
            "python": str(python_exe),
            "stdout": proc.stdout.strip(),
            "stderr": proc.stderr.strip(),
        }
    except Exception as exc:
        return {"ok": False, "mode": "isolated", "python": str(python_exe), "error": f"{type(exc).__name__}: {exc}"}


def main_gliner_available() -> dict[str, Any]:
    try:
        from gliner import GLiNER  # noqa: F401

        return {"ok": True, "mode": "main"}
    except Exception as exc:
        return {"ok": False, "mode": "main", "error": f"{type(exc).__name__}: {exc}"}


def gliner_status() -> dict[str, Any]:
    main = main_gliner_available()
    isolated = isolated_gliner_available(timeout=45)
    return {
        "ok": bool(main.get("ok") or isolated.get("ok")),
        "main": main,
        "isolated": isolated,
        "model": GLINER_MODEL,
        "cached": hf_model_cache_exists(GLINER_MODEL),
    }


def model_cache_status() -> dict[str, Any]:
    return {
        "embedding": {"model": EMBED_MODEL, "cached": hf_model_cache_exists(EMBED_MODEL), "path": str(hf_model_cache_path(EMBED_MODEL))},
        "reranker": {"model": RERANKER_MODEL, "cached": hf_model_cache_exists(RERANKER_MODEL), "path": str(hf_model_cache_path(RERANKER_MODEL))},
        "nli": {"model": NLI_MODEL, "cached": hf_model_cache_exists(NLI_MODEL), "path": str(hf_model_cache_path(NLI_MODEL))},
        "classifier": {"model": CLASSIFIER_MODEL, "cached": hf_model_cache_exists(CLASSIFIER_MODEL), "path": str(hf_model_cache_path(CLASSIFIER_MODEL))},
        "gliner": gliner_status(),
    }


def _snapshot_download(model_name: str) -> dict[str, Any]:
    try:
        from huggingface_hub import snapshot_download

        path = snapshot_download(
            repo_id=model_name,
            token=os.getenv("HF_TOKEN"),
            local_files_only=False,
            resume_download=True,
        )
        return {"model": model_name, "status": "cached", "path": path}
    except Exception as exc:
        return {"model": model_name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def prewarm_phase4_models(include_gliner: bool = True) -> dict[str, Any]:
    models = [EMBED_MODEL, RERANKER_MODEL, NLI_MODEL, CLASSIFIER_MODEL]
    if include_gliner:
        models.append(GLINER_MODEL)
    downloads = [_snapshot_download(model) for model in models]
    return {
        "hf_token": bool(os.getenv("HF_TOKEN")),
        "downloads": downloads,
        "cache_status": model_cache_status(),
    }


def print_json(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
