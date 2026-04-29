"""Embedded Qdrant + FastEmbed vector store — single file, no external server."""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from qdrant_client import QdrantClient

from pipeline_v2.settings import EMBED_MODEL, QDRANT_DIR

log = logging.getLogger("pipeline_v2.vector_store")

COLLECTION = "omnilegal_v2"

_client: QdrantClient | None = None
_embed_ready = False


def _client_instance() -> QdrantClient:
    global _client, _embed_ready
    if _client is None:
        log.info("Opening embedded Qdrant at %s", QDRANT_DIR)
        _client = QdrantClient(path=str(QDRANT_DIR))
    if not _embed_ready:
        _client.set_model(EMBED_MODEL)
        _embed_ready = True
    return _client


def ensure_collection() -> None:
    # Rely on Qdrant's fastembed `add()` to create the collection on first upsert.
    _client_instance()


def _doc_point_id(doc: dict[str, Any]) -> str:
    seed = "|".join([
        str(doc.get("source_id") or ""),
        str(doc.get("citation") or ""),
        str(doc.get("chunk_index") or 0),
        (doc.get("text") or "")[:200],
    ])
    digest = hashlib.sha256(seed.encode("utf-8", errors="ignore")).hexdigest()
    # Use UUID-style hex so qdrant-local accepts it
    return f"{digest[:8]}-{digest[8:12]}-{digest[12:16]}-{digest[16:20]}-{digest[20:32]}"


def upsert_documents(docs: list[dict[str, Any]]) -> int:
    if not docs:
        return 0
    client = _client_instance()
    texts = [d["text"] for d in docs]
    ids = [_doc_point_id(d) for d in docs]
    payloads = [
        {k: v for k, v in d.items() if k != "text"} | {"text": d["text"]}
        for d in docs
    ]
    client.add(
        collection_name=COLLECTION,
        documents=texts,
        metadata=payloads,
        ids=ids,
    )
    return len(docs)


def collection_count() -> int:
    try:
        client = _client_instance()
        info = client.get_collection(COLLECTION)
        return int(info.points_count or 0)
    except Exception:
        return 0


def hybrid_search(
    query: str,
    jurisdictions: list[str] | None = None,
    doc_types: list[str] | None = None,
    limit: int = 12,
) -> list[dict[str, Any]]:
    client = _client_instance()
    try:
        client.get_collection(COLLECTION)
    except Exception:
        return []

    from qdrant_client.models import FieldCondition, Filter, MatchAny

    must: list[FieldCondition] = []
    if jurisdictions:
        must.append(
            FieldCondition(key="jurisdiction", match=MatchAny(any=jurisdictions))
        )
    if doc_types:
        must.append(FieldCondition(key="doc_type", match=MatchAny(any=doc_types)))
    query_filter = Filter(must=must) if must else None

    results = client.query(
        collection_name=COLLECTION,
        query_text=query,
        query_filter=query_filter,
        limit=limit,
    )
    hits: list[dict[str, Any]] = []
    for r in results:
        meta = dict(r.metadata or {})
        text = meta.pop("document", None) or meta.pop("text", "") or ""
        hits.append({
            "text": text,
            "score": float(r.score or 0.0),
            "metadata": meta,
        })
    return hits


def clear_collection() -> None:
    client = _client_instance()
    try:
        client.delete_collection(COLLECTION)
        log.info("Deleted collection %s", COLLECTION)
    except Exception:
        pass
