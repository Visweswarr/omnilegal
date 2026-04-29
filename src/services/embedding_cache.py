"""SQLite-backed query-embedding cache.

Avoids redundant vectorisation calls by caching embeddings keyed on
(model_name, normalised_query).  Thread-safe for the Chainlit event loop.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from src.config import EMBED_MODEL, OMNILEGAL_EMBEDDING_CACHE_PATH

logger = logging.getLogger(__name__)

_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


def _cache_key(model_name: str, query: str) -> str:
    normalised = " ".join(query.strip().lower().split())
    payload = json.dumps({"m": model_name, "q": normalised}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def _serialize(vec: np.ndarray) -> bytes:
    flat = vec.astype(np.float32).flatten()
    return struct.pack(f"{len(flat)}f", *flat)


def _deserialize(blob: bytes, dim: int) -> np.ndarray:
    count = len(blob) // 4
    return np.array(struct.unpack(f"{count}f", blob), dtype=np.float32)


class EmbeddingCache:
    """Thread-safe SQLite cache for query embeddings."""

    _instance: EmbeddingCache | None = None
    _lock = threading.Lock()

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path or OMNILEGAL_EMBEDDING_CACHE_PATH)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn_lock = threading.Lock()
        self._ensure_schema()

    @classmethod
    def get_instance(cls) -> EmbeddingCache:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Schema ─────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._path), timeout=15, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _ensure_schema(self) -> None:
        with self._conn_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS embedding_cache (
                        cache_key  TEXT PRIMARY KEY,
                        model_name TEXT NOT NULL,
                        dim        INTEGER NOT NULL,
                        embedding  BLOB NOT NULL,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    # ── Read / Write ───────────────────────────────────────────────────

    def get(self, query: str, *, model_name: str | None = None) -> np.ndarray | None:
        """Return cached embedding or ``None``."""
        model = model_name or EMBED_MODEL
        key = _cache_key(model, query)
        with self._conn_lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT dim, embedding, created_at FROM embedding_cache WHERE cache_key = ?",
                    (key,),
                ).fetchone()
                if row is None:
                    return None
                dim, blob, created_at = row
                if time.time() - float(created_at) > _TTL_SECONDS:
                    conn.execute("DELETE FROM embedding_cache WHERE cache_key = ?", (key,))
                    conn.commit()
                    return None
                return _deserialize(blob, int(dim))
            finally:
                conn.close()

    def put(self, query: str, embedding: np.ndarray, *, model_name: str | None = None) -> None:
        """Insert or replace a cached embedding."""
        model = model_name or EMBED_MODEL
        key = _cache_key(model, query)
        dim = int(embedding.shape[-1]) if embedding.ndim > 0 else 0
        blob = _serialize(embedding)
        with self._conn_lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO embedding_cache
                        (cache_key, model_name, dim, embedding, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (key, model, dim, blob, time.time()),
                )
                conn.commit()
            finally:
                conn.close()

    def get_batch(
        self,
        queries: Sequence[str],
        *,
        model_name: str | None = None,
    ) -> dict[str, np.ndarray | None]:
        """Look up multiple queries in one call."""
        return {q: self.get(q, model_name=model_name) for q in queries}

    def put_batch(
        self,
        items: dict[str, np.ndarray],
        *,
        model_name: str | None = None,
    ) -> None:
        """Bulk-insert embeddings."""
        for query, vec in items.items():
            self.put(query, vec, model_name=model_name)

    # ── Maintenance ────────────────────────────────────────────────────

    def evict_expired(self) -> int:
        """Remove all expired entries. Returns count deleted."""
        cutoff = time.time() - _TTL_SECONDS
        with self._conn_lock:
            conn = self._connect()
            try:
                cursor = conn.execute(
                    "DELETE FROM embedding_cache WHERE created_at < ?", (cutoff,)
                )
                conn.commit()
                return cursor.rowcount
            finally:
                conn.close()

    def stats(self) -> dict[str, int]:
        """Return basic cache statistics."""
        with self._conn_lock:
            conn = self._connect()
            try:
                total = conn.execute("SELECT COUNT(*) FROM embedding_cache").fetchone()[0]
                cutoff = time.time() - _TTL_SECONDS
                expired = conn.execute(
                    "SELECT COUNT(*) FROM embedding_cache WHERE created_at < ?", (cutoff,)
                ).fetchone()[0]
                return {"total": int(total), "expired": int(expired), "active": int(total) - int(expired)}
            finally:
                conn.close()
