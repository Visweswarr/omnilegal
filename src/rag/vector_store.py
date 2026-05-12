"""Vector store abstraction supporting Qdrant and a SQLite fallback."""
from __future__ import annotations

import os
import sys
import json
import sqlite3
import hashlib
import urllib.request
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    ALL_COLLECTIONS,
    EMBEDDING_DIM as _CFG_EMBEDDING_DIM,
    EMBEDDING_MODEL,
    OMNILEGAL_QDRANT_EMBEDDED_PATH,
    OMNILEGAL_VECTOR_BACKEND,
    QDRANT_URL,
    VECTOR_DB_DIR,
)
from src.services.authority import annotate_authority_tier


def _embedding_dim() -> int:
    """Resolve the embedding dimension from current config (allows runtime override)."""
    from src import config as _cfg  # noqa: WPS433
    return int(getattr(_cfg, "EMBEDDING_DIM", _CFG_EMBEDDING_DIM) or _CFG_EMBEDDING_DIM)


# Backwards-compat alias so existing references still resolve.
EMBEDDING_DIM = _CFG_EMBEDDING_DIM

logger = logging.getLogger(__name__)

try:
    from qdrant_client import QdrantClient  # compatibility for tests and legacy callers
except Exception:  # pragma: no cover - optional in fallback-only installs
    QdrantClient = None  # type: ignore[assignment]

class BaseVectorStore(ABC):
    @abstractmethod
    def create_collection(self, name: str, *, recreate: bool = False) -> None:
        pass

    @abstractmethod
    def upsert_chunks(self, collection: str, chunks: list[dict[str, Any]], *, batch_size: int = 32) -> int:
        pass

    @abstractmethod
    def available_collections(self) -> list[str]:
        pass

    @abstractmethod
    def collection_point_count(self, collection: str) -> int:
        pass

    @abstractmethod
    def load_all_documents_metadata_only(self, collections: list[str] | None = None) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def hybrid_search(self, query: str, dense_vec: list[float], sparse_weights: dict[int, float], collection: str, k: int) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def lexical_search(self, query: str, query_terms: set[str], collection: str, k: int) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    def scroll_payload_matches(self, collection: str, key: str, value: Any, limit: int) -> list[dict[str, Any]]:
        pass

def _stable_point_id(collection: str, chunk: dict[str, Any]) -> int:
    metadata = chunk.get("metadata") or {}
    seed = metadata.get("chunk_id")
    if not seed:
        text_hash = hashlib.sha256((chunk.get("text") or "").encode("utf-8", errors="ignore")).hexdigest()
        seed = "|".join([
            collection,
            str(metadata.get("source_name") or ""),
            str(metadata.get("citation") or ""),
            str(metadata.get("chunk_index") or 0),
            text_hash[:24],
        ])
    digest = hashlib.sha256(str(seed).encode("utf-8", errors="ignore")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) & ((1 << 63) - 1)


def _display_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("raw_text") or chunk.get("text") or "")


def _embedding_text(chunk: dict[str, Any]) -> str:
    return str(chunk.get("index_text") or chunk.get("text") or chunk.get("raw_text") or "")


def _hash_text(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8", errors="ignore")).hexdigest()


def _legal_type_for_payload(payload: dict[str, Any], collection: str) -> str:
    doc_type = str(payload.get("doc_type") or "").lower()
    collection = str(collection or payload.get("collection") or "").upper()
    if doc_type == "case_law" or "CASE_LAW" in collection:
        return "case_law"
    if doc_type == "treaty" or collection == "INTL_TREATIES":
        return "treaty"
    if doc_type in {"constitutional_text", "domestic_law", "statute", "legislation"} or "STATUTES" in collection or "NATIONAL" in collection:
        return "statute"
    if doc_type in {"source_catalog", "source_map", "project_reference", "ingestion_manifest"}:
        return "source_metadata"
    return "commentary"


def _importance_for_payload(payload: dict[str, Any], collection: str) -> tuple[float, str, list[str]]:
    haystack = " ".join(
        str(payload.get(key) or "")
        for key in ("source_name", "citation", "doc_type", "collection")
    ).lower()
    collection = str(collection or payload.get("collection") or "").upper()
    if any(name in haystack for name in ["un charter", "iccpr", "icescr", "constitution of india"]):
        return 1.0, "core treaty or constitutional material", ["core_local_corpus"]
    if "CASE_LAW" in collection or str(payload.get("doc_type") or "").lower() == "case_law":
        return 0.7, "case-law authority", ["case_law"]
    if collection == "SHAW_PRIVATE":
        return 0.6, "licensed doctrinal commentary", ["private_commentary"]
    if str(payload.get("doc_type") or "").lower() == "treaty":
        return 0.8, "primary treaty material", ["treaty"]
    return 0.5, "ingested legal corpus material", ["ingested_corpus"]


def payload_with_ingestion_defaults(collection: str, chunk: dict[str, Any]) -> dict[str, Any]:
    """Build a Qdrant payload and fill production metadata defaults."""
    raw_text = _display_text(chunk)
    index_text = _embedding_text(chunk)
    payload = {
        **(chunk.get("metadata") or {}),
        "text": raw_text,
        "raw_text": raw_text,
        "index_text": index_text,
    }

    text_for_hash = str(payload.get("raw_text") or payload.get("text") or "")
    source_name = str(payload.get("source_name") or payload.get("citation") or collection)
    citation = str(payload.get("citation") or source_name)
    year = payload.get("year") or payload.get("date") or payload.get("source_version") or "undated"
    article = payload.get("article_number") or payload.get("section") or ""
    canonical_seed = "|".join([str(collection), source_name, citation, str(year), str(article)])
    fingerprint = hashlib.sha256("|".join([source_name.lower(), citation.lower(), str(year)]).encode("utf-8", errors="ignore")).hexdigest()
    importance_score, importance_reason, importance_signals = _importance_for_payload(payload, collection)

    payload.setdefault("collection", collection)
    collection_upper = str(collection or payload.get("collection") or "").upper()
    doc_type_lower = str(payload.get("doc_type") or "").lower()
    if "source_role" not in payload:
        if doc_type_lower == "treaty" or collection_upper == "INTL_TREATIES":
            payload["source_role"] = "treaty"
        elif doc_type_lower == "case_law" or "CASE_LAW" in collection_upper:
            payload["source_role"] = "case_law"
        elif doc_type_lower == "official_guidance" or collection_upper.startswith("NATIONAL_"):
            payload["source_role"] = "official_guidance"
        elif doc_type_lower in {"statute", "legislation", "domestic_law"} or "STATUTES" in collection_upper:
            payload["source_role"] = "local_statute"
        elif doc_type_lower == "commentary" or "COMMENTARY" in collection_upper or collection_upper == "SHAW_PRIVATE":
            payload["source_role"] = "commentary"
    payload.setdefault("doc_hash", _hash_text(text_for_hash))
    payload.setdefault("canonical_doc_id", hashlib.sha256(canonical_seed.encode("utf-8", errors="ignore")).hexdigest())
    payload.setdefault("source_fingerprint", fingerprint)
    payload.setdefault("legal_type", _legal_type_for_payload(payload, collection))
    payload.setdefault("source_version", str(year))
    payload.setdefault("version_date", str(year))
    payload.setdefault("language", "en")
    payload.setdefault("translation_status", "original_only")
    payload.setdefault("importance_score", importance_score)
    payload.setdefault("importance_reason", importance_reason)
    payload.setdefault("importance_signals", importance_signals)
    return annotate_authority_tier(payload)

def _hit_from_point(point: Any, *, score: float = 0.05) -> dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    payload.pop("index_text", None)
    text = payload.pop("raw_text", "") or payload.pop("text", "") or payload.get("content", "")
    return {"text": text, "score": score, "metadata": payload}

def _qdrant_request(path: str, payload: dict[str, Any] | None = None, timeout: int = 2) -> dict[str, Any]:
    url = f"{QDRANT_URL.rstrip('/')}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

class QdrantVectorStore(BaseVectorStore):
    def __init__(self, client):
        self.client = client

    def create_collection(self, name: str, *, recreate: bool = False) -> None:
        from qdrant_client.models import Distance, SparseIndexParams, SparseVectorParams, VectorParams
        existing = {c.name for c in self.client.get_collections().collections}
        if name in existing:
            if recreate:
                self.client.delete_collection(name)
            else:
                return
        self.client.create_collection(
            collection_name=name,
            vectors_config={"dense": VectorParams(size=_embedding_dim(), distance=Distance.COSINE)},
            sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))},
        )
        print(f"Created Qdrant collection: {name}")

    def upsert_chunks(self, collection: str, chunks: list[dict[str, Any]], *, batch_size: int = 32) -> int:
        from qdrant_client.models import PointStruct, SparseVector
        if not chunks: return 0
        embed = get_embed_model()
        self.create_collection(collection)
        total = 0
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [_embedding_text(c) for c in batch]
            outputs = embed.encode(texts, return_dense=True, return_sparse=True, return_colbert_vecs=False)
            dense_vecs = outputs["dense_vecs"]
            sparse_weights = outputs["lexical_weights"]
            points = []
            for j, chunk in enumerate(batch):
                sparse_indices = [int(k) for k in sparse_weights[j].keys()]
                sparse_values = [float(v) for v in sparse_weights[j].values()]
                payload = payload_with_ingestion_defaults(collection, chunk)
                points.append(
                    PointStruct(
                        id=_stable_point_id(collection, chunk),
                        vector={
                            "dense": dense_vecs[j].tolist(),
                            "sparse": SparseVector(indices=sparse_indices, values=sparse_values),
                        },
                        payload=payload,
                    )
                )
            self.client.upsert(collection_name=collection, points=points)
            total += len(points)
        return total

    def available_collections(self) -> list[str]:
        try:
            existing = {c.name for c in self.client.get_collections().collections}
            return [c for c in ALL_COLLECTIONS if c in existing]
        except Exception:
            try:
                data = _qdrant_request("/collections", timeout=5)
                existing = {c["name"] for c in data.get("result", {}).get("collections", [])}
                return [c for c in ALL_COLLECTIONS if c in existing]
            except Exception:
                return []

    def collection_point_count(self, collection: str) -> int:
        try:
            info = self.client.get_collection(collection)
            return info.points_count or 0
        except Exception:
            try:
                data = _qdrant_request(f"/collections/{collection}", timeout=5)
                return int(data.get("result", {}).get("points_count") or 0)
            except Exception:
                return 0

    def load_all_documents_metadata_only(self, collections: list[str] | None = None) -> list[dict[str, Any]]:
        selected = collections or self.available_collections()
        docs = []
        for col in selected:
            try:
                offset = None
                while True:
                    result, offset = self.client.scroll(
                        collection_name=col, limit=256, offset=offset, with_payload=True, with_vectors=False
                    )
                    for point in result:
                        payload = dict(point.payload or {})
                        payload["collection"] = col
                        docs.append(payload)
                    if offset is None: break
            except Exception as exc:
                print(f"Warning: could not scroll {col}: {exc}")
        return docs

    def hybrid_search(self, query: str, dense_vec: list[float], sparse_weights: dict[int, float], collection: str, k: int) -> list[dict[str, Any]]:
        from qdrant_client.models import FusionQuery, Prefetch, SparseVector, Fusion
        prefetch = [
            Prefetch(query=dense_vec, using="dense", limit=k * 2),
            Prefetch(query=SparseVector(indices=list(sparse_weights.keys()), values=list(sparse_weights.values())), using="sparse", limit=k * 2),
        ]
        results = self.client.query_points(
            collection_name=collection, prefetch=prefetch, query=FusionQuery(fusion=Fusion.RRF), limit=k, with_payload=True,
        )
        hits = []
        for pt in results.points:
            payload = dict(pt.payload or {})
            payload.pop("index_text", None)
            text = payload.pop("raw_text", "") or payload.pop("text", "")
            hits.append({"text": text, "score": pt.score, "metadata": payload})
        return hits

    def lexical_search(self, query: str, query_terms: set[str], collection: str, k: int) -> list[dict[str, Any]]:
        try:
            points, _ = self.client.scroll(
                collection_name=collection,
                limit=max(k * 50, 256),
                with_payload=True,
                with_vectors=False,
            )
        except Exception:
            return []
        hits = []
        for point in points:
            payload = dict(getattr(point, "payload", None) or {})
            index_text = str(payload.pop("index_text", "") or "")
            text = payload.pop("raw_text", "") or payload.pop("text", "") or payload.get("content", "")
            if not text:
                continue
            lowered = f"{index_text}\n{text}".lower()
            overlap = sum(1 for term in query_terms if term in lowered)
            score = overlap + (0.5 if any(marker in lowered for marker in ["article", "court", "charter", "held"]) else 0.0)
            if score <= 0 and query_terms:
                continue
            hits.append({"text": text, "score": float(score or 0.1), "metadata": payload})
        return sorted(hits, key=lambda item: item["score"], reverse=True)[:k]

    def scroll_payload_matches(self, collection: str, key: str, value: Any, limit: int) -> list[dict[str, Any]]:
        if value in (None, "", []): return []
        try:
            from qdrant_client.models import FieldCondition, Filter, MatchValue
            points, _ = self.client.scroll(
                collection_name=collection,
                scroll_filter=Filter(must=[FieldCondition(key=key, match=MatchValue(value=value))]),
                limit=limit, with_payload=True, with_vectors=False,
            )
            return [_hit_from_point(point) for point in points]
        except Exception:
            return []

class SQLiteVectorStore(BaseVectorStore):
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    point_id INTEGER,
                    collection TEXT,
                    text TEXT,
                    metadata_json TEXT,
                    dense_vec_json TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_collection ON documents(collection)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_point_id ON documents(point_id)")

    def create_collection(self, name: str, *, recreate: bool = False) -> None:
        if recreate:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("DELETE FROM documents WHERE collection = ?", (name,))
        print(f"Verified SQLite collection: {name}")

    def upsert_chunks(self, collection: str, chunks: list[dict[str, Any]], *, batch_size: int = 32) -> int:
        if not chunks: return 0
        embed = get_embed_model()
        self.create_collection(collection)
        total = 0
        with sqlite3.connect(self.db_path) as conn:
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i : i + batch_size]
                texts = [_embedding_text(c) for c in batch]
                outputs = embed.encode(texts, return_dense=True, return_sparse=False, return_colbert_vecs=False)
                dense_vecs = outputs["dense_vecs"]
                for j, chunk in enumerate(batch):
                    point_id = _stable_point_id(collection, chunk)
                    payload = payload_with_ingestion_defaults(collection, chunk)
                    # Delete existing to simulate upsert
                    conn.execute("DELETE FROM documents WHERE collection = ? AND point_id = ?", (collection, point_id))
                    conn.execute(
                        "INSERT INTO documents (point_id, collection, text, metadata_json, dense_vec_json) VALUES (?, ?, ?, ?, ?)",
                        (point_id, collection, _display_text(chunk), json.dumps(payload), json.dumps(dense_vecs[j].tolist()))
                    )
                    total += 1
        return total

    def available_collections(self) -> list[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT DISTINCT collection FROM documents").fetchall()
            existing = {r[0] for r in rows}
            return [c for c in ALL_COLLECTIONS if c in existing]

    def collection_point_count(self, collection: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT COUNT(*) FROM documents WHERE collection = ?", (collection,)).fetchone()
            return row[0] if row else 0

    def load_all_documents_metadata_only(self, collections: list[str] | None = None) -> list[dict[str, Any]]:
        selected = collections or self.available_collections()
        docs = []
        with sqlite3.connect(self.db_path) as conn:
            for col in selected:
                rows = conn.execute("SELECT metadata_json FROM documents WHERE collection = ?", (col,)).fetchall()
                for (metadata_json,) in rows:
                    payload = json.loads(metadata_json)
                    payload["collection"] = col
                    docs.append(payload)
        return docs

    def hybrid_search(self, query: str, dense_vec: list[float], sparse_weights: dict[int, float], collection: str, k: int) -> list[dict[str, Any]]:
        import numpy as np  # noqa: WPS433
        query_arr = np.asarray(dense_vec, dtype=np.float32)
        q_norm = float(np.linalg.norm(query_arr)) or 1.0
        hits = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT text, metadata_json, dense_vec_json FROM documents WHERE collection = ?", (collection,)).fetchall()
            if not rows: return []

            texts, metas, vectors = [], [], []
            for text, meta_json, vec_json in rows:
                texts.append(text)
                metas.append(json.loads(meta_json))
                vectors.append(json.loads(vec_json))

            doc_arr = np.asarray(vectors, dtype=np.float32)
            if doc_arr.size and doc_arr.ndim == 2 and doc_arr.shape[1] == query_arr.shape[0]:
                doc_norms = np.linalg.norm(doc_arr, axis=1)
                doc_norms[doc_norms == 0] = 1.0
                scores = (doc_arr @ query_arr) / (doc_norms * q_norm)
                for i, score in enumerate(scores.tolist()):
                    meta = metas[i]
                    meta.pop("index_text", None)
                    text = meta.pop("raw_text", "") or meta.pop("text", "") or texts[i]
                    hits.append({"text": text, "score": float(score), "metadata": meta})

        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:k]

    def lexical_search(self, query: str, query_terms: set[str], collection: str, k: int) -> list[dict[str, Any]]:
        hits = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT text, metadata_json FROM documents WHERE collection = ?", (collection,)).fetchall()
            for text, meta_json in rows:
                if not text: continue
                meta = json.loads(meta_json)
                index_text = str(meta.pop("index_text", "") or "")
                lowered = text.lower()
                haystack = f"{index_text}\n{lowered}".lower()
                overlap = sum(1 for term in query_terms if term in haystack)
                score = overlap + (0.5 if any(marker in haystack for marker in ["article", "court", "charter", "held"]) else 0.0)
                if score <= 0 and query_terms: continue
                final_text = meta.pop("raw_text", "") or meta.pop("text", "") or text
                hits.append({"text": final_text, "score": float(score), "metadata": meta})
        return sorted(hits, key=lambda item: item["score"], reverse=True)[:k]

    def scroll_payload_matches(self, collection: str, key: str, value: Any, limit: int) -> list[dict[str, Any]]:
        if value in (None, "", []): return []
        hits = []
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT text, metadata_json FROM documents WHERE collection = ?", (collection,)).fetchall()
            for text, meta_json in rows:
                payload = json.loads(meta_json)
                if payload.get(key) == value:
                    payload.pop("index_text", None)
                    final_text = payload.pop("raw_text", "") or payload.pop("text", "") or text
                    hits.append({"text": final_text, "score": 0.05, "metadata": payload})
                    if len(hits) >= limit:
                        break
        return hits


_store_instance = None
_embed_model = None

def _ensure_transformers_flagembedding_compat() -> None:
    try:
        import transformers.utils as transformers_utils
        import transformers.utils.import_utils as import_utils
        if not hasattr(import_utils, "is_torch_fx_available"):
            import_utils.is_torch_fx_available = lambda: False
        if not hasattr(transformers_utils, "is_torch_fx_available"):
            transformers_utils.is_torch_fx_available = import_utils.is_torch_fx_available
    except Exception:
        pass


def preferred_torch_devices() -> list[str] | None:
    raw = os.getenv("OMNILEGAL_EMBED_DEVICES") or os.getenv("OMNILEGAL_EMBED_DEVICE")
    if raw:
        devices = [part.strip() for part in raw.split(",") if part.strip()]
        return devices or None
    try:
        import torch
        if torch.cuda.is_available():
            return ["cuda:0"]
    except Exception:
        return None
    return None


def get_embed_model():
    """Return an embedding model that exposes BGE-m3-style ``encode(...)``.

    Resolution order:
      1. ``OMNILEGAL_EMBED_PROVIDER=flagembedding`` → BGE-m3 via FlagEmbedding (heavy, dense+sparse).
      2. ``OMNILEGAL_EMBED_PROVIDER=fastembed`` → FastEmbed BGE-small (light, dense only).
      3. ``auto`` (default): try FlagEmbedding, fall back to FastEmbed if it fails to load.
    """
    global _embed_model
    if _embed_model is not None:
        return _embed_model

    from src.config import OMNILEGAL_EMBED_PROVIDER

    provider = (OMNILEGAL_EMBED_PROVIDER or "auto").lower()

    def _load_flag_embedding():
        _ensure_transformers_flagembedding_compat()
        from FlagEmbedding import BGEM3FlagModel  # noqa: WPS433

        devices = preferred_torch_devices()
        batch_size = int(os.getenv("OMNILEGAL_EMBED_BATCH_SIZE", "8" if devices else "32"))
        logger.info(
            "Loading %s for embeddings on %s with batch_size=%s",
            EMBEDDING_MODEL,
            devices or "cpu",
            batch_size,
        )
        return BGEM3FlagModel(
            EMBEDDING_MODEL,
            use_fp16=bool(devices),
            devices=devices,
            batch_size=batch_size,
        )

    def _load_fastembed():
        from src.config import EMBEDDING_DIM, FASTEMBED_DIM, FASTEMBED_MODEL  # noqa: WPS433
        # FastEmbed runs CPU, ships the model on first call (~130MB for BGE-small).
        from fastembed import TextEmbedding  # noqa: WPS433

        logger.info("Loading FastEmbed model %s for dense embeddings", FASTEMBED_MODEL)
        model = TextEmbedding(model_name=FASTEMBED_MODEL)

        class _FastEmbedAdapter:
            def __init__(self, _inner):
                self._inner = _inner

            def encode(self, texts, return_dense=True, return_sparse=False, return_colbert_vecs=False, **_kwargs):
                import numpy as np  # noqa: WPS433

                vectors = list(self._inner.embed(list(texts)))
                array = np.array(vectors, dtype=np.float32)
                output = {"dense_vecs": array}
                if return_sparse:
                    # Provide an empty sparse map so callers that expect it don't crash.
                    output["lexical_weights"] = [{} for _ in texts]
                return output

        # Push the configured embedding dim back so the vector store creates collections of the right size.
        if EMBEDDING_DIM != FASTEMBED_DIM:
            try:
                from src import config as _cfg  # noqa: WPS433
                _cfg.EMBEDDING_DIM = FASTEMBED_DIM  # type: ignore[attr-defined]
            except Exception:
                pass
        return _FastEmbedAdapter(model)

    if provider == "flagembedding":
        _embed_model = _load_flag_embedding()
        return _embed_model

    if provider == "fastembed":
        _embed_model = _load_fastembed()
        return _embed_model

    # auto
    try:
        _embed_model = _load_flag_embedding()
        return _embed_model
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "FlagEmbedding unavailable (%s); falling back to FastEmbed for dense embeddings.",
            exc,
        )
        _embed_model = _load_fastembed()
        return _embed_model

def configured_vector_backend() -> str:
    # Re-read from env to pick up .env changes loaded by dotenv
    from src.env import load_environment
    load_environment()
    backend = os.getenv("OMNILEGAL_VECTOR_BACKEND", OMNILEGAL_VECTOR_BACKEND).lower().replace("-", "_")
    return backend

def get_store() -> BaseVectorStore:
    global _store_instance
    if _store_instance is not None:
        return _store_instance

    if os.getenv("OMNILEGAL_FORCE_FALLBACK_STORE", "0") in {"1", "true", "yes"}:
        logger.warning("OMNILEGAL_FORCE_FALLBACK_STORE enabled. Forcing SQLite fallback vector store.")
        db_path = VECTOR_DB_DIR / "local_fallback.sqlite"
        _store_instance = SQLiteVectorStore(db_path)
        return _store_instance

    backend = configured_vector_backend()
    logger.info("Vector backend resolved to: %s (QDRANT_URL=%s)", backend, QDRANT_URL)
    print(f"[OmniLegal] Vector backend = {backend!r}, QDRANT_URL = {QDRANT_URL!r}")
    allow_sqlite_fallback = os.getenv("OMNILEGAL_ALLOW_SQLITE_FALLBACK", "0").lower() in {"1", "true", "yes"}

    # Safety: if backend says embedded but a Qdrant server is reachable, prefer server
    if backend in {"embedded_qdrant", "local_qdrant", "qdrant_local"} and QdrantClient is not None:
        try:
            _probe = QdrantClient(url=QDRANT_URL, timeout=3)
            _probe.get_collections()
            _probe.close()
            logger.info("Qdrant server detected at %s — auto-switching from embedded to server_qdrant", QDRANT_URL)
            print(f"[OmniLegal] Auto-switching from embedded to server_qdrant (server at {QDRANT_URL} is alive)")
            backend = "server_qdrant"
        except Exception:
            pass  # Server not reachable, use embedded as configured

    try:
        if QdrantClient is None:
            raise RuntimeError("qdrant-client is not installed")
        if backend in {"embedded_qdrant", "local_qdrant", "qdrant_local"}:
            OMNILEGAL_QDRANT_EMBEDDED_PATH.mkdir(parents=True, exist_ok=True)
            logger.warning("Using EMBEDDED Qdrant at %s — this can be slow with large collections!", OMNILEGAL_QDRANT_EMBEDDED_PATH)
            client = QdrantClient(path=str(OMNILEGAL_QDRANT_EMBEDDED_PATH))
            client.get_collections()
            _store_instance = QdrantVectorStore(client)
            return _store_instance
        if backend in {"server_qdrant", "qdrant_server", "qdrant"}:
            logger.info("Connecting to Qdrant server at %s", QDRANT_URL)
            client = QdrantClient(url=QDRANT_URL, timeout=float(os.getenv("QDRANT_TIMEOUT_SECONDS", "60")))
            client.get_collections()
            logger.info("Successfully connected to Qdrant server")
            _store_instance = QdrantVectorStore(client)
            return _store_instance
        if backend in {"sqlite", "sqlite_fallback", "fallback_sqlite"}:
            logger.warning("Using SQLite vector store because OMNILEGAL_VECTOR_BACKEND=%s.", backend)
            db_path = VECTOR_DB_DIR / "local_fallback.sqlite"
            _store_instance = SQLiteVectorStore(db_path)
            return _store_instance
        raise RuntimeError(f"Unknown OMNILEGAL_VECTOR_BACKEND={backend!r}")
    except Exception as exc:
        if not allow_sqlite_fallback:
            raise RuntimeError(
                f"Vector backend {backend!r} is unavailable: {exc}. "
                "Set OMNILEGAL_VECTOR_BACKEND=embedded_qdrant or rebuild the embedded store."
            ) from exc
        logger.warning("Vector backend %s unavailable (%s). Using explicit SQLite fallback.", backend, exc)
        db_path = VECTOR_DB_DIR / "local_fallback.sqlite"
        _store_instance = SQLiteVectorStore(db_path)
        return _store_instance

# Backward compatibility wrappers targeting `get_store()`
def get_client(*args, **kwargs):
    # Deprecated: Retained purely for scripts expecting Qdrant client directly.
    return getattr(get_store(), "client", None)

def create_collection(name: str, *, recreate: bool = False) -> None:
    get_store().create_collection(name, recreate=recreate)

def upsert_chunks(collection: str, chunks: list[dict[str, Any]], *, batch_size: int = 32) -> int:
    return get_store().upsert_chunks(collection, chunks, batch_size=batch_size)


def upsert_chunks_lexical_only(collection: str, chunks: list[dict[str, Any]], *, batch_size: int = 32) -> int:
    """Upsert payloads with zero vectors so lexical/Qdrant scroll retrieval works without embeddings."""
    if not chunks:
        return 0

    from qdrant_client.models import PointStruct, SparseVector

    store = get_store()
    client = getattr(store, "client", None)
    if client is None:
        return store.upsert_chunks(collection, chunks, batch_size=batch_size)

    store.create_collection(collection)
    zero_dense = [0.0] * _embedding_dim()
    total = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        points = [
            PointStruct(
                id=_stable_point_id(collection, chunk),
                vector={
                    "dense": zero_dense,
                    "sparse": SparseVector(indices=[], values=[]),
                },
                payload=payload_with_ingestion_defaults(collection, chunk),
            )
            for chunk in batch
        ]
        client.upsert(collection_name=collection, points=points)
        total += len(points)
    return total

def available_collection_indices() -> list[str]:
    return get_store().available_collections()

def available_collections() -> list[str]:
    return get_store().available_collections()

def collection_point_count(collection: str) -> int:
    return get_store().collection_point_count(collection)

def load_all_documents_metadata_only(collections: list[str] | None = None) -> list[dict[str, Any]]:
    return get_store().load_all_documents_metadata_only(collections)


def close_store() -> None:
    global _store_instance
    store = _store_instance
    _store_instance = None
    client = getattr(store, "client", None)
    if client is not None and hasattr(client, "close"):
        try:
            client.close()
        except Exception:
            pass
