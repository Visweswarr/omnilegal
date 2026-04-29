"""Local production readiness checks for OmniLegal."""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import (
    ALL_COLLECTIONS,
    ANTHROPIC_API_KEY,
    EMBED_MODEL,
    GROQ_API_KEY,
    GEMINI_API_KEY,
    LOCAL_LLM,
    NLI_MODEL,
    OMNILEGAL_ENABLE_HEAVY_MODELS,
    OMNILEGAL_QDRANT_EMBEDDED_PATH,
    OMNILEGAL_QUALITY_MODE,
    OMNILEGAL_USE_DENSE_RETRIEVAL,
    OMNILEGAL_VECTOR_BACKEND,
    QDRANT_URL,
    RERANKER_MODEL,
    REQUIRED_RUNTIME_PACKAGES,
    COLLECTION_CASE_LAW,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
)
from src.services.knowledge_base import knowledge_base_status
from src.services.model_cache import gliner_status, model_cache_status
from src.services.remote_sources import remote_status, source_audit_summary
from src.rag.vector_store import close_store, preferred_torch_devices

CORE_PACKAGES = {"chainlit", "langgraph", "groq", "spacy", "qdrant_client"}
OPTIONAL_HEAVY_PACKAGES = set(REQUIRED_RUNTIME_PACKAGES) - CORE_PACKAGES
PHASE4_REQUIRED_LOCAL_COLLECTIONS = {
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_SHAW_PRIVATE,
}


def _check_package(name: str) -> dict[str, Any]:
    if name == "gemini_sdk":
        new_sdk = importlib.util.find_spec("google.genai") is not None
        legacy_sdk = importlib.util.find_spec("google.generativeai") is not None
        return {
            "name": name,
            "ok": new_sdk or legacy_sdk,
            "google_genai": new_sdk,
            "google_generativeai": legacy_sdk,
        }
    if name == "gliner":
        status = gliner_status()
        return {
            "name": name,
            "ok": bool(status.get("ok")),
            "adapter": status,
        }
    try:
        found = importlib.util.find_spec(name) is not None
        if found:
            return {"name": name, "ok": True}
        importlib.import_module(name)
        return {"name": name, "ok": True}
    except Exception as exc:
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_qdrant() -> dict[str, Any]:
    status = knowledge_base_status().as_dict()
    backend = status.get("backend") or OMNILEGAL_VECTOR_BACKEND
    counts = status.get("counts") or {}
    collections = sorted(counts)
    return {
        "ok": not any(str(reason).startswith("Vector backend unavailable") for reason in status.get("failure_causes", [])),
        "backend": backend,
        "client": "embedded" if str(backend).startswith("embedded") else "server",
        "url": QDRANT_URL,
        "embedded_path": str(OMNILEGAL_QDRANT_EMBEDDED_PATH),
        "collections": collections,
        "counts": counts,
        "missing_production_collections": [c for c in ALL_COLLECTIONS if c not in collections],
        "knowledge_base_ready": status.get("ready"),
        "missing_required": status.get("missing_required", []),
        "shaw_coverage": status.get("shaw_coverage", {}),
        "failure_causes": status.get("failure_causes", []),
        "rebuild_command": status.get("rebuild_command"),
    }


def _check_spacy() -> dict[str, Any]:
    try:
        models = {}
        for name in ["en_core_web_sm", "en_legal_ner_trf"]:
            models[name] = importlib.util.find_spec(name) is not None
        return {"ok": any(models.values()), "models": models}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_docker() -> dict[str, Any]:
    docker = shutil.which("docker")
    if not docker:
        return {"ok": False, "error": "docker executable not found on PATH"}
    try:
        proc = subprocess.run(
            [docker, "ps", "--format", "{{.Image}} {{.Status}} {{.Names}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        return {"ok": proc.returncode == 0, "output": proc.stdout.strip(), "error": proc.stderr.strip()}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _check_ollama() -> dict[str, Any]:
    ollama = shutil.which("ollama")
    if not ollama:
        return {"ok": False, "model": LOCAL_LLM, "error": "ollama executable not found on PATH"}
    try:
        proc = subprocess.run([ollama, "list"], capture_output=True, text=True, timeout=20, check=False)
        return {"ok": proc.returncode == 0, "model": LOCAL_LLM, "output": proc.stdout.strip()}
    except Exception as exc:
        return {"ok": False, "model": LOCAL_LLM, "error": f"{type(exc).__name__}: {exc}"}

def _check_model_cache() -> dict[str, Any]:
    return model_cache_status()


def _check_torch_acceleration() -> dict[str, Any]:
    try:
        import torch
        devices = []
        for idx in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(idx)
            devices.append({
                "index": idx,
                "name": torch.cuda.get_device_name(idx),
                "total_memory_mb": round(props.total_memory / (1024 * 1024)),
            })
        return {
            "torch_version": torch.__version__,
            "cuda_available": bool(torch.cuda.is_available()),
            "cuda_version": torch.version.cuda,
            "device_count": torch.cuda.device_count(),
            "devices": devices,
            "selected_embedding_devices": preferred_torch_devices(),
            "embed_batch_size": os.getenv("OMNILEGAL_EMBED_BATCH_SIZE", "auto"),
            "rerank_batch_size": os.getenv("OMNILEGAL_RERANK_BATCH_SIZE", "auto"),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_checks() -> dict[str, Any]:
    package_results = [_check_package(name) for name in REQUIRED_RUNTIME_PACKAGES]
    qdrant = _check_qdrant()
    model_cache = _check_model_cache()
    remote = remote_status()
    counts = qdrant.get("counts", {}) if qdrant.get("ok") else {}
    empty_required_collections = list(qdrant.get("missing_required") or [])
    missing_optional = [
        p["name"] for p in package_results
        if not p["ok"] and p["name"] in OPTIONAL_HEAVY_PACKAGES
    ]
    missing_core = [
        p["name"] for p in package_results
        if not p["ok"] and p["name"] in CORE_PACKAGES
    ]
    degraded_reasons = []
    if missing_optional:
        degraded_reasons.append(f"Optional packages missing: {', '.join(sorted(missing_optional))}.")
    if not model_cache["embedding"]["cached"]:
        degraded_reasons.append(f"Embedding model not cached: {EMBED_MODEL}.")
    if not model_cache["reranker"]["cached"]:
        degraded_reasons.append(
            f"Reranker model not cached: {RERANKER_MODEL}; reranking falls back until prewarmed."
        )
    if OMNILEGAL_ENABLE_HEAVY_MODELS and not model_cache["nli"]["cached"]:
        degraded_reasons.append(f"Heavy NLI model not cached: {NLI_MODEL}.")
    if OMNILEGAL_ENABLE_HEAVY_MODELS and not model_cache["classifier"]["cached"]:
        degraded_reasons.append(f"Heavy classifier model not cached: {model_cache['classifier']['model']}.")
    if OMNILEGAL_ENABLE_HEAVY_MODELS and not model_cache["gliner"]["cached"]:
        degraded_reasons.append(f"GLiNER model not cached: {model_cache['gliner']['model']}.")
    if empty_required_collections:
        degraded_reasons.append(
            "Required local collections are empty: " + ", ".join(empty_required_collections) + "."
        )
    for reason in qdrant.get("failure_causes", []):
        if reason not in degraded_reasons:
            degraded_reasons.append(reason)
    if ANTHROPIC_API_KEY == "":
        degraded_reasons.append("ANTHROPIC_API_KEY missing; contextual retrieval uses Groq/fallbacks only.")
    if not remote.get("has_audit"):
        try:
            audit = source_audit_summary()
            remote["current_audit_summary"] = audit.get("summary", {})
        except Exception as exc:
            degraded_reasons.append(f"Remote source audit could not be read: {type(exc).__name__}: {exc}.")
    if remote.get("audit_summary", {}).get("missing_env"):
        missing = ", ".join(remote["audit_summary"]["missing_env"][:12])
        degraded_reasons.append(f"Remote source credentials/licence gates missing: {missing}.")
    elif remote.get("current_audit_summary", {}).get("missing_env"):
        missing = ", ".join(remote["current_audit_summary"]["missing_env"][:12])
        degraded_reasons.append(f"Remote source credentials/licence gates missing: {missing}.")
    return {
        "python": sys.version,
        "cwd": str(Path.cwd()),
        "env": {
            "GROQ_API_KEY": bool(GROQ_API_KEY),
            "GEMINI_API_KEY": bool(GEMINI_API_KEY),
            "ANTHROPIC_API_KEY": bool(ANTHROPIC_API_KEY),
            "QDRANT_URL": QDRANT_URL,
            "OMNILEGAL_VECTOR_BACKEND": OMNILEGAL_VECTOR_BACKEND,
            "OMNILEGAL_QDRANT_EMBEDDED_PATH": str(OMNILEGAL_QDRANT_EMBEDDED_PATH),
            "OMNILEGAL_QUALITY_MODE": OMNILEGAL_QUALITY_MODE,
            "OMNILEGAL_USE_DENSE_RETRIEVAL": OMNILEGAL_USE_DENSE_RETRIEVAL,
            "HF_TOKEN": bool(os.getenv("HF_TOKEN")),
            "LOCAL_LLM": LOCAL_LLM,
        },
        "packages": package_results,
        "qdrant": qdrant,
        "spacy": _check_spacy(),
        "docker": _check_docker(),
        "ollama": _check_ollama(),
        "torch_acceleration": _check_torch_acceleration(),
        "model_cache": model_cache,
        "remote_sources": remote,
        "empty_required_local_collections": empty_required_collections,
        "missing_core_packages": missing_core,
        "missing_optional_packages": missing_optional,
        "status": "failed" if missing_core or not qdrant.get("ok", False) or not qdrant.get("knowledge_base_ready", False) else ("degraded" if degraded_reasons else "ok"),
        "degraded_reasons": degraded_reasons,
        "ok": not missing_core and qdrant.get("ok", False) and qdrant.get("knowledge_base_ready", False),
    }


def main() -> None:
    result = run_checks()
    print(json.dumps(result, indent=2))
    missing_core = result.get("missing_core_packages", [])
    missing_optional = result.get("missing_optional_packages", [])
    if missing_core:
        print("\nMissing core packages:", ", ".join(missing_core))
        print("Run: .venv\\Scripts\\python.exe -m pip install -r requirements.txt")
    if missing_optional:
        print("\nOptional degraded packages:", ", ".join(missing_optional))
        print("Install when you need full PDF-path retrieval/eval features.")
    if not result["qdrant"].get("knowledge_base_ready"):
        print("\nKnowledge base is not ready. Run:")
        print(result["qdrant"].get("rebuild_command"))
    close_store()
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
