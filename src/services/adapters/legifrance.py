"""Legifrance / PISTE API adapter for French law."""
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
    OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP,
    PISTE_API_BASE_URL,
    PISTE_API_KEY,
    PISTE_CLIENT_ID,
    PISTE_CLIENT_SECRET,
    PISTE_OAUTH_URL,
)

_TOKEN_URL = PISTE_OAUTH_URL
_SEARCH_URL = f"{PISTE_API_BASE_URL.rstrip('/')}/dila/legifrance/lf-engine-app/search"
_ARTICLE_URL = f"{PISTE_API_BASE_URL.rstrip('/')}/dila/legifrance/consult/getArticle"

_SEED_QUERIES = [
    "Code civil",
    "Code penal",
    "Code du travail",
    "Code de la consommation",
    "Code de procedure penale",
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
        return json.loads(resp.read().decode("utf-8", errors="replace"))["access_token"]


def _post_json(token: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "KeyId": _api_key(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))
    return data if isinstance(data, dict) else {"results": data}


def _search_legifrance(token: str, query: str, page_size: int = 5) -> list[dict[str, Any]]:
    """Use broad PISTE search first, then exact search as a compatibility fallback."""
    search_types = ["TOUS_LES_MOTS_DANS_UN_CHAMP", "TOUS_LES_MOTS", "EXACTE"]
    last_error: Exception | None = None
    for search_type in search_types:
        payload = {
            "recherche": {
                "champs": [
                    {
                        "typeChamp": "ALL",
                        "criteres": [{"typeRecherche": search_type, "valeur": query}],
                    }
                ],
                "pageNumber": 1,
                "pageSize": page_size,
            },
            "fond": "CODE_DATE",
        }
        try:
            data = _post_json(token, _SEARCH_URL, payload)
        except Exception as exc:
            last_error = exc
            continue
        rows = data.get("results") or data.get("items") or data.get("documents") or []
        if isinstance(rows, list) and rows:
            return [row for row in rows if isinstance(row, dict)][:page_size]
    if last_error:
        raise last_error
    return []


def _first_value(data: Any, keys: set[str]) -> str:
    if isinstance(data, dict):
        lowered = {str(key).lower(): value for key, value in data.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if value not in (None, ""):
                return str(value)
        for value in data.values():
            found = _first_value(value, keys)
            if found:
                return found
    elif isinstance(data, list):
        for value in data:
            found = _first_value(value, keys)
            if found:
                return found
    return ""


def _collect_text_fields(data: Any, keys: set[str], *, limit: int = 8) -> list[str]:
    values: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            if len(values) >= limit:
                break
            if str(key).lower() in keys and isinstance(value, str) and value.strip():
                values.append(value.strip())
            elif isinstance(value, (dict, list)):
                values.extend(_collect_text_fields(value, keys, limit=limit - len(values)))
    elif isinstance(data, list):
        for value in data:
            if len(values) >= limit:
                break
            values.extend(_collect_text_fields(value, keys, limit=limit - len(values)))
    return values[:limit]


def _article_identity(item: dict[str, Any]) -> dict[str, str]:
    return {
        "article_id": _first_value(item, {"id", "idArticle", "articleId"}),
        "cid": _first_value(item, {"cid"}),
        "text_id": _first_value(item, {"textId", "texteId"}),
        "num": _first_value(item, {"num", "numero", "articleNumber"}),
        "title": _first_value(item, {"titre", "title", "libelle", "name"}),
    }


def _article_text(data: dict[str, Any], *, fallback_title: str = "") -> str:
    title = _first_value(data, {"titre", "title", "libelle", "name"}) or fallback_title
    body_parts = _collect_text_fields(
        data,
        {"texte", "text", "contenu", "content", "articletext", "textarticle", "extrait", "resume"},
    )
    return "\n\n".join(part for part in [title, *body_parts] if part).strip()


def _consult_article(token: str, item: dict[str, Any]) -> dict[str, Any]:
    ident = _article_identity(item)
    payloads: list[dict[str, Any]] = []
    if ident["article_id"]:
        payloads.extend([
            {"id": ident["article_id"]},
            {"idArticle": ident["article_id"]},
        ])
    if ident["cid"] and ident["article_id"]:
        payloads.append({"cid": ident["cid"], "id": ident["article_id"]})
    if ident["cid"] and ident["num"]:
        payloads.append({"cid": ident["cid"], "num": ident["num"]})
    if ident["text_id"] and ident["num"]:
        payloads.append({"textId": ident["text_id"], "num": ident["num"]})

    for payload in payloads:
        try:
            data = _post_json(token, _ARTICLE_URL, payload)
        except Exception:
            continue
        if _article_text(data, fallback_title=ident["title"]):
            return data
    return {}


def _metadata_text(item: dict[str, Any], query: str) -> str:
    ident = _article_identity(item)
    title = ident["title"] or query
    return "\n".join(
        part
        for part in [
            f"Legifrance: {title}",
            f"CID: {ident['cid']}" if ident["cid"] else "",
            f"Text ID: {ident['text_id']}" if ident["text_id"] else "",
            f"Article ID: {ident['article_id']}" if ident["article_id"] else "",
            f"Article number: {ident['num']}" if ident["num"] else "",
        ]
        if part
    )


def _source_url(item: dict[str, Any]) -> str:
    ident = _article_identity(item)
    if ident["article_id"]:
        return f"https://www.legifrance.gouv.fr/codes/article_lc/{ident['article_id']}/"
    if ident["cid"]:
        return f"https://www.legifrance.gouv.fr/codes/texte_lc/{ident['cid']}/"
    return "https://www.legifrance.gouv.fr/"


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
    """Fetch French legislation via Legifrance search and article consult APIs."""
    if not _api_key() or not _client_id() or not _client_secret():
        return [], [{
            "source": "Legifrance",
            "status": "error",
            "reason": "PISTE_API_KEY / PISTE_CLIENT_ID / PISTE_CLIENT_SECRET not set",
        }]

    try:
        token = _get_token()
    except Exception as exc:
        return [], [{"source": "Legifrance", "status": "error", "reason": f"OAuth token error: {exc}"}]

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
            ident = _article_identity(item)
            title = ident["title"] or query
            item_key = ident["article_id"] or ident["cid"] or title
            if item_key in seen:
                continue
            seen.add(item_key)

            source_url = _source_url(item)
            article = _consult_article(token, item)
            text = _article_text(article, fallback_title=title) or _metadata_text(item, query)
            raw_bytes = text.encode("utf-8", errors="ignore")
            if len(raw_bytes) > max_bytes:
                events.append({
                    "query": query,
                    "status": "skipped",
                    "reason": "item exceeded max-bytes-per-item",
                    "bytes": len(raw_bytes),
                })
                continue
            if not budget.reserve(len(raw_bytes)):
                events.append({"query": query, "status": "budget_exhausted", "bytes": len(raw_bytes)})
                break

            checksum = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
            doc_chunks = chunk_remote_text(
                record,
                plan,
                text,
                url=source_url,
                checksum=checksum,
                download_key=f"legifrance:{item_key or checksum[:16]}",
            )
            for chunk in doc_chunks:
                chunk["metadata"].update({
                    "doc_type": "statute",
                    "source_name": f"Legifrance: {title}",
                    "jurisdiction": "fr",
                    "citation": title,
                    "source_url": source_url,
                    "license_note": "Open licence Etalab / Legifrance open data",
                    "language": "fr",
                    "source_role": "local_statute",
                    "authority_tier": "primary_authority",
                    "canonical_doc_id": f"legifrance:{item_key}",
                    "source_fingerprint": item_key,
                })
            chunks.extend(doc_chunks)
            time.sleep(0.15)

    events.append({"source": "Legifrance", "status": "completed", "chunks": len(chunks), "items": len(seen)})
    return chunks, events
