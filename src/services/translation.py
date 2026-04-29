"""Optional translation preparation for Russian/Hebrew corpora."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import (
    AZURE_TRANSLATOR_KEY,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_RU,
    DATA_DIR,
    DEEPL_API_KEY,
    GOOGLE_TRANSLATE_KEY,
)

TRANSLATION_DIR = DATA_DIR / "translations"
TRANSLATABLE_LANGUAGES = {"ru", "he"}


def choose_translation_provider(provider: str = "auto") -> str | None:
    if provider and provider != "auto":
        return provider
    if DEEPL_API_KEY:
        return "deepl"
    if AZURE_TRANSLATOR_KEY:
        return "azure"
    if GOOGLE_TRANSLATE_KEY:
        return "google"
    return None


def protect_citations(text: str) -> tuple[str, dict[str, str]]:
    pattern = re.compile(
        r"(\[[0-9A-Za-z][0-9A-Za-z .:-]{0,40}\]|\bArticle\s+[0-9A-Za-z().-]+|\bart\.?\s+[0-9A-Za-z().-]+|https?://\S+)"
    )
    protected: dict[str, str] = {}
    counter = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal counter
        token = f"__CITE_{counter}__"
        protected[token] = match.group(0)
        counter += 1
        return token

    return pattern.sub(repl, text), protected


def restore_citations(text: str, protected: dict[str, str]) -> str:
    output = text
    for token, value in protected.items():
        output = output.replace(token, value)
    return output


def _candidate_documents(collections: list[str], *, limit: int | None = None) -> list[dict[str, Any]]:
    from src.rag.vector_store import load_all_documents_metadata_only

    docs = []
    for payload in load_all_documents_metadata_only(collections):
        language = str(payload.get("language") or "").lower()
        if language in TRANSLATABLE_LANGUAGES and str(payload.get("translation_status") or "original") != "translated":
            docs.append(payload)
            if limit and len(docs) >= limit:
                break
    return docs


def prepare_translation(
    *,
    collections: list[str] | None = None,
    provider: str = "auto",
    limit: int | None = None,
    ingest: bool = True,
) -> dict[str, Any]:
    selected = collections or [COLLECTION_NATIONAL_RU, COLLECTION_NATIONAL_IL]
    TRANSLATION_DIR.mkdir(parents=True, exist_ok=True)
    chosen = choose_translation_provider(provider)
    candidates = _candidate_documents(selected, limit=limit)
    status = "ready"
    translated_chunks: list[dict[str, Any]] = []

    if chosen is None:
        status = "no_provider"
    else:
        # Provider integrations are intentionally explicit. The default local build
        # keeps multilingual retrieval; translation runs only once a real key exists.
        status = "provider_configured_not_run"

    upserted = 0
    if ingest and translated_chunks:
        from src.rag.vector_store import upsert_chunks

        grouped: dict[str, list[dict[str, Any]]] = {}
        for chunk in translated_chunks:
            grouped.setdefault(chunk["metadata"]["collection"], []).append(chunk)
        for collection, chunks in grouped.items():
            upserted += upsert_chunks(collection, chunks, batch_size=8)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collections": selected,
        "provider_requested": provider,
        "provider_selected": chosen,
        "status": status,
        "candidate_count": len(candidates),
        "translated_chunks": len(translated_chunks),
        "upserted": upserted,
        "policy": "original-language retrieval remains active; no ingest-time auto-translation without provider keys",
    }
    manifest_dir = TRANSLATION_DIR / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = manifest_dir / f"{timestamp}_translation_prepare_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    latest = manifest_dir / "latest_translation_prepare_manifest.json"
    latest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    manifest["manifest_path"] = str(path)
    manifest["latest_manifest_path"] = str(latest)
    return manifest


def latest_translation_manifest() -> dict[str, Any] | None:
    path = TRANSLATION_DIR / "manifests" / "latest_translation_prepare_manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
