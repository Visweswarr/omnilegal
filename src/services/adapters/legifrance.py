"""Légifrance / PISTE API adapter — French law (requires OAuth2 credentials)."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import (
    COLLECTION_COMMENTARY_GLOBAL,
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
    PISTE_API_BASE_URL,
    PISTE_API_KEY,
    PISTE_CLIENT_ID,
    PISTE_CLIENT_SECRET,
    PISTE_OAUTH_URL,
)

_TOKEN_URL = PISTE_OAUTH_URL
_SEARCH_URL = f"{PISTE_API_BASE_URL.rstrip('/')}/dila/legifrance/lf-engine-app/search"

_SEED_QUERIES = [
    "Code civil",
    "Code pénal",
    "Code du travail",
    "Code de la consommation",
    "Code de procédure pénale",
]


def _client_id() -> str:
    return PISTE_CLIENT_ID or os.getenv("PISTE_CLIENT_ID", "")


def _client_secret() -> str:
    return PISTE_CLIENT_SECRET or os.getenv("PISTE_CLIENT_SECRET", "")


def _api_key() -> str:
    return PISTE_API_KEY or os.getenv("PISTE_API_KEY", "")


def _get_token() -> str:
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": _client_id(),
        "client_secret": _client_secret(),
        "scope": "openid",
    }).encode()
    req = urllib.request.Request(
        _TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())["access_token"]


def _search_legifrance(token: str, query: str, page_size: int = 5) -> list[dict[str, Any]]:
    payload = json.dumps({
        "recherche": {"champs": [{"typeChamp": "ALL", "criteres": [{"typeRecherche": "EXACTE", "valeur": query}]}],
                      "pageNumber": 1, "pageSize": page_size},
        "fond": "CODE_DATE",
    }).encode()
    req = urllib.request.Request(
        _SEARCH_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "KeyId": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    return list((data.get("results") or []))[:page_size]


def fetch(
    record: Any,
    plan: Any,
    *,
    root: Path,
    budget: Any,
    max_items: int = 0,
    max_bytes: int = 10 * 1024 * 1024,
    mode: str = "licensed",
    checkpoint: dict[str, dict[str, Any]] | None = None,
    resume: bool = True,
    ingest: bool = False,
    **_kwargs: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch French legislation metadata via Légifrance/PISTE API."""
    if not _api_key() or not _client_id() or not _client_secret():
        return [], [{"source": "Légifrance", "status": "error", "reason": "PISTE_API_KEY / PISTE_CLIENT_ID / PISTE_CLIENT_SECRET not set"}]

    try:
        token = _get_token()
    except Exception as exc:
        return [], [{"source": "Légifrance", "status": "error", "reason": f"OAuth token error: {exc}"}]

    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for query in _SEED_QUERIES:
        if len(seen) >= effective_max:
            break
        try:
            items = _search_legifrance(token, query, page_size=min(5, effective_max - len(seen)))
        except Exception as exc:
            events.append({"query": query, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
            continue

        for item in items:
            title = str(item.get("titre") or item.get("title") or query).strip()
            if title in seen:
                continue
            seen.add(title)
            cid = str(item.get("cid") or "").strip()
            source_url = (
                f"https://www.legifrance.gouv.fr/codes/texte_lc/{cid}/" if cid
                else "https://www.legifrance.gouv.fr/"
            )
            text = (
                f"Légifrance: {title}\n"
                f"CID: {cid}\n"
                f"Source: {source_url}"
            ).strip()
            checksum = hashlib.sha256(text.encode()).hexdigest()
            doc_chunks = chunk_remote_text(
                record, plan, text,
                url=source_url, checksum=checksum,
                download_key=f"legifrance:{cid or checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"Légifrance: {title}",
                    "jurisdiction": "fr",
                    "citation": title,
                    "source_url": source_url,
                    "license_note": "Open licence Etalab / Légifrance open data",
                    "language": "fr",
                })
            chunks.extend(doc_chunks)
            time.sleep(0.15)

    events.append({"source": "Légifrance", "status": "completed", "chunks": len(chunks)})
    return chunks, events
