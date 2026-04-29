"""
Contextual Document Retrieval

Generates document-level semantic context strings injected into chunk objects to boost global vector matching.
Caches generation states dynamically inside SQLite instances tracking hashes natively.
"""
from __future__ import annotations

import json
import sqlite3
import hashlib
from pathlib import Path
from typing import Any

from src.env import load_environment
load_environment()

from src.config import (
    GEMINI_API_KEY, 
    ANTHROPIC_API_KEY, 
    GROQ_API_KEY,
    GROQ_MODEL,
    OMNILEGAL_ENABLE_CONTEXTUAL_RETRIEVAL,
    OMNILEGAL_CONTEXTUAL_PROVIDER,
    OMNILEGAL_CONTEXTUAL_MODEL,
    OMNILEGAL_CONTEXTUAL_CACHE_DIR,
    OMNILEGAL_CONTEXTUAL_MAX_DOC_CHARS,
    OMNILEGAL_CONTEXTUAL_SUMMARY_TARGET_TOKENS
)
from src.services.gemini_client import compact_gemini_error, generate_gemini_content

_CONTEXTUAL_DISABLED_REASON: str | None = None


class ContextCache:
    """Persistent SQLite cache mapping deterministic hashes to LLM context answers directly."""
    
    def __init__(self, db_path: str = OMNILEGAL_CONTEXTUAL_CACHE_DIR):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS context_cache (
                    hash_key TEXT PRIMARY KEY,
                    context_out TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get(self, hash_key: str) -> str | None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT context_out FROM context_cache WHERE hash_key = ?", (hash_key,))
                row = cursor.fetchone()
                return row[0] if row else None
        except Exception as exc:
            print(f"Warning: SQLite Cache GET failed: {exc}")
            return None

    def set(self, hash_key: str, context_out: str) -> None:
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO context_cache (hash_key, context_out) VALUES (?, ?)",
                    (hash_key, context_out)
                )
                conn.commit()
        except Exception as exc:
            print(f"Warning: SQLite Cache SET failed: {exc}")


_CACHE_INSTANCE = None


def _get_cache() -> ContextCache:
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is None:
        _CACHE_INSTANCE = ContextCache()
    return _CACHE_INSTANCE


def _stable_hash(source_name: str, doc_text: str) -> str:
    """Generates immutable content ID."""
    seed = f"{source_name}::{doc_text}".encode("utf-8", "ignore")
    return hashlib.sha256(seed).hexdigest()


def _compress_document_length(doc_text: str, max_chars: int) -> str:
    """Trim overly long PDFs natively targeting header and tail configurations mapping semantic structures."""
    if len(doc_text) <= max_chars:
        return doc_text
    
    head_size = int(max_chars * 0.7)
    tail_size = max_chars - head_size
    return doc_text[:head_size] + "\n\n...[TRUNCATED_INTERMEDIATE_PAGES]...\n\n" + doc_text[-tail_size:]


def generate_document_context(
    source_name: str, 
    doc_text: str, 
    jurisdiction: str, 
    doc_type: str
) -> str:
    """
    Produce a rich 50-100 token document-level context mapping document-type, bounds, and issues safely.
    Runs globally over document caching states. Avoids LLM loops scaling per chunk exponentially.
    """
    global _CONTEXTUAL_DISABLED_REASON

    if not OMNILEGAL_ENABLE_CONTEXTUAL_RETRIEVAL:
        return ""
    
    if _CONTEXTUAL_DISABLED_REASON:
        return ""

    if not doc_text.strip():
        return ""

    hash_key = _stable_hash(source_name, doc_text)
    cache = _get_cache()
    cached = cache.get(hash_key)
    
    if cached is not None:
        return cached

    prompt_system = (
        "You are an expert legal metadata assistant. Summarize the following document "
        f"into exactly one dense paragraph. Target ~{OMNILEGAL_CONTEXTUAL_SUMMARY_TARGET_TOKENS} tokens. "
        "The summary MUST emphasize the document type (e.g. treaty, case, statute), jurisdiction, "
        "core legal issue area, identifying instrument numbers or titles, and why this document matters "
        "for overall indexing and retrieval. This will be prepended to chunks to improve vector semantic search."
    )
    
    compressed_text = _compress_document_length(doc_text, OMNILEGAL_CONTEXTUAL_MAX_DOC_CHARS)
    
    prompt_user = (
        f"Source Name: {source_name}\n"
        f"Jurisdiction: {jurisdiction}\n"
        f"Doc Type: {doc_type}\n\n"
        f"DOCUMENT:\n{compressed_text}\n\nContext block:"
    )

    result = ""

    # 1. Gemini Pathway
    if OMNILEGAL_CONTEXTUAL_PROVIDER == "gemini" and GEMINI_API_KEY:
        generation = generate_gemini_content(
            system=prompt_system,
            prompt=prompt_user,
            model=OMNILEGAL_CONTEXTUAL_MODEL,
            fallback_models=[],
            temperature=0.0,
            max_output_tokens=150,
        )
        result = generation.text
        if not result and generation.error:
            print(
                "Warning: Gemini contextual provider failed: "
                f"{compact_gemini_error(generation.error)} Attempting Anthropic fallback..."
            )

    # 2. Anthropic Fallback
    if not result and ANTHROPIC_API_KEY:
        try:
            from anthropic import Anthropic
            client = Anthropic(api_key=ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model="claude-3-5-haiku-latest",
                max_tokens=150,
                temperature=0,
                system=prompt_system,
                messages=[{"role": "user", "content": prompt_user}],
            )
            result = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text").strip()
        except Exception as exc:
            print(f"Warning: Anthropic contextual provider failed: {exc}")
            if "rate" in str(exc).lower():
                _CONTEXTUAL_DISABLED_REASON = f"Contextual retrieval disabled globally after rate-limit: {exc}"
                return ""

    # 3. Groq Fallback
    if not result and GROQ_API_KEY:
        try:
            from groq import Groq
            client = Groq(api_key=GROQ_API_KEY)
            resp = client.chat.completions.create(
                model=GROQ_MODEL,
                messages=[
                    {"role": "system", "content": prompt_system},
                    {"role": "user", "content": prompt_user},
                ],
                max_tokens=150,
                temperature=0.0,
            )
            result = resp.choices[0].message.content.strip()
        except Exception as exc:
            print(f"Warning: Groq contextual provider failed: {exc}")
            if "rate" in str(exc).lower() or "429" in str(exc):
                _CONTEXTUAL_DISABLED_REASON = f"Contextual retrieval disabled globally after rate-limit: {exc}"
                return ""

    if result:
        # Prevent hallucinated prefix labels
        prefix = "Context block:"
        if result.startswith(prefix):
            result = result[len(prefix):].strip()
            
        cache.set(hash_key, result)
        
    return result
