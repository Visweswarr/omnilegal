"""
Qdrant hybrid retriever with bge-m3 dense+sparse, RRF fusion (c=60),
and bge-reranker-v2-m3 cross-encoder reranking.
"""
from __future__ import annotations

import sys
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import (
    OMNILEGAL_DIR,
    ALL_COLLECTIONS,
    CASE_LAW_COLLECTIONS,
    COLLECTION_ALIAS_MAP,
    COLLECTION_CASE_LAW,
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    ISSUE_COLLECTION_MAP,
    OMNILEGAL_ENABLE_HEAVY_MODELS,
    OMNILEGAL_USE_DENSE_RETRIEVAL,
    RERANKER_MODEL,
    RERANK_TOP_N,
    RETRIEVAL_TOP_K_CANDIDATES,
    RRF_K,
    QDRANT_URL,
)
from src.services.authority import authority_weight, infer_authority_tier

try:
    from qdrant_client import QdrantClient  # compatibility for older tests/callers
except Exception:  # pragma: no cover - optional dependency on degraded installs
    QdrantClient = None  # type: ignore[assignment]
from src.rag.vector_store import get_store, get_embed_model, preferred_torch_devices
from src.services.embedding_cache import EmbeddingCache
from src.config import OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS

_reranker = None
_transformers_reranker = None
_collection_cache: tuple[float, set[str]] | None = None
_QDRANT_REST_TIMEOUT_SECONDS = 2
_USE_DENSE_RETRIEVAL = OMNILEGAL_USE_DENSE_RETRIEVAL

_COUNTRY_ROUTE_LABELS = {
    "in": [COLLECTION_NATIONAL_IN, COLLECTION_STATUTES_IN, COLLECTION_CASE_LAW_IN],
    "india": [COLLECTION_NATIONAL_IN, COLLECTION_STATUTES_IN, COLLECTION_CASE_LAW_IN],
    "indian": [COLLECTION_NATIONAL_IN, COLLECTION_STATUTES_IN, COLLECTION_CASE_LAW_IN],
    "us": [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    "usa": [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    "united states": [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    "american": [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    "gb": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "uk": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "united kingdom": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "british": [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    "eu": [COLLECTION_STATUTES_EU, COLLECTION_CASE_LAW_EU],
    "european union": [COLLECTION_STATUTES_EU, COLLECTION_CASE_LAW_EU],
    "european": [COLLECTION_STATUTES_EU, COLLECTION_CASE_LAW_EU],
    "ru": [COLLECTION_STATUTES_RU, COLLECTION_CASE_LAW_RU],
    "russia": [COLLECTION_STATUTES_RU, COLLECTION_CASE_LAW_RU],
    "russian": [COLLECTION_STATUTES_RU, COLLECTION_CASE_LAW_RU],
    "il": [COLLECTION_STATUTES_IL, COLLECTION_CASE_LAW_IL],
    "israel": [COLLECTION_STATUTES_IL, COLLECTION_CASE_LAW_IL],
    "israeli": [COLLECTION_STATUTES_IL, COLLECTION_CASE_LAW_IL],
}

_COLLECTION_JURISDICTIONS = {
    COLLECTION_NATIONAL_IN: "in",
    COLLECTION_NATIONAL_US: "us",
    COLLECTION_NATIONAL_UK: "gb",
    COLLECTION_NATIONAL_EU: "eu",
    COLLECTION_NATIONAL_RU: "ru",
    COLLECTION_NATIONAL_IL: "il",
    COLLECTION_STATUTES_IN: "in",
    COLLECTION_STATUTES_US: "us",
    COLLECTION_STATUTES_UK: "gb",
    COLLECTION_STATUTES_EU: "eu",
    COLLECTION_STATUTES_RU: "ru",
    COLLECTION_STATUTES_IL: "il",
    COLLECTION_CASE_LAW_IN: "in",
    COLLECTION_CASE_LAW_US: "us",
    COLLECTION_CASE_LAW_UK: "gb",
    COLLECTION_CASE_LAW_EU: "eu",
    COLLECTION_CASE_LAW_RU: "ru",
    COLLECTION_CASE_LAW_IL: "il",
    COLLECTION_CASE_LAW_GLOBAL: "international",
    COLLECTION_COMMENTARY_GLOBAL: "international",
    COLLECTION_INTL_TREATIES: "international",
    COLLECTION_SHAW_PRIVATE: "international",
    COLLECTION_COMMENTARY: "international",
}

_JURISDICTION_ALIASES = {
    "in": "in", "india": "in", "indian": "in",
    "us": "us", "usa": "us", "u.s.": "us", "united states": "us", "american": "us",
    "gb": "gb", "uk": "gb", "united kingdom": "gb", "british": "gb", "great britain": "gb",
    "eu": "eu", "european union": "eu", "european": "eu",
    "ru": "ru", "russia": "ru", "russian federation": "ru", "russian": "ru",
    "il": "il", "israel": "il", "israeli": "il",
    "international": "international", "intl": "international", "global": "international",
    "un": "international", "united nations": "international", "icj": "international",
}

_NOISE_SOURCE_NAMES = {"nato", "unctad", "african court", "isds"}
_ANCHOR_STOP_TERMS = {
    "about",
    "act",
    "article",
    "articles",
    "case",
    "cases",
    "constitution",
    "constitutional",
    "court",
    "courts",
    "domestic",
    "does",
    "fundamental",
    "india",
    "indian",
    "international",
    "jurisdiction",
    "law",
    "laws",
    "legal",
    "right",
    "rights",
    "section",
    "source",
    "state",
    "states",
    "supreme",
    "tell",
    "treaty",
    "under",
    "union",
    "what",
}


def _is_source_discovery_query(query: str) -> bool:
    lowered = query.lower()
    return any(
        term in lowered
        for term in [
            "source", "sources", "dataset", "datasets", "corpus", "available",
            "ingested", "download", "license", "coverage", "api", "where can",
        ]
    )


def _normalize_jurisdiction(value: Any) -> str:
    cleaned = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if not cleaned:
        return ""
    return _JURISDICTION_ALIASES.get(cleaned, cleaned)


def _collection_jurisdiction(collection: str) -> str:
    return _COLLECTION_JURISDICTIONS.get(str(collection or "").upper(), "")


def expand_collection_aliases(collections: list[str], *, include_legacy_fallback: bool = False) -> list[str]:
    """Expand legacy logical collections into granular physical collections."""
    expanded: list[str] = []
    seen: set[str] = set()
    for collection in collections:
        collection = str(collection or "").upper()
        targets = COLLECTION_ALIAS_MAP.get(collection, [collection])
        if include_legacy_fallback and collection not in targets:
            targets = list(targets) + [collection]
        for target in targets:
            if target not in seen:
                seen.add(target)
                expanded.append(target)
    return expanded


def _country_constraints(labels: list[str]) -> set[str]:
    allowed: set[str] = set()
    for label in labels:
        key = str(label or "").lower()
        for collection in _COUNTRY_ROUTE_LABELS.get(key, []):
            jurisdiction = _collection_jurisdiction(collection)
            if jurisdiction:
                allowed.add(jurisdiction)
    return allowed


def _drop_domestic_case_law_without_country(collections: list[str], issue_labels: list[str]) -> list[str]:
    normalized = {str(label or "").lower() for label in issue_labels}
    if "named_case" in normalized or _country_constraints(issue_labels):
        return collections
    return [
        collection
        for collection in collections
        if collection == COLLECTION_CASE_LAW_GLOBAL or collection not in CASE_LAW_COLLECTIONS
    ]


def _candidate_allowed_for_query(query: str, candidate: dict[str, Any], allowed_countries: set[str]) -> bool:
    metadata = candidate.get("metadata") or {}
    doc_type = str(metadata.get("doc_type", "")).lower()
    source_name = str(metadata.get("source_name", "")).lower()
    collection = str(metadata.get("collection") or "").upper()

    if doc_type == "source_catalog" and not _is_source_discovery_query(query):
        return False

    if not any(noise in query.lower() for noise in _NOISE_SOURCE_NAMES):
        if any(noise in source_name for noise in _NOISE_SOURCE_NAMES):
            return False

    if not allowed_countries:
        return True

    allowed = set(allowed_countries) | {"international"}
    collection_jurisdiction = _collection_jurisdiction(collection)
    metadata_jurisdiction = _normalize_jurisdiction(metadata.get("jurisdiction"))
    effective_jurisdiction = metadata_jurisdiction or collection_jurisdiction

    if collection in {
        COLLECTION_NATIONAL_IN,
        COLLECTION_NATIONAL_US,
        COLLECTION_NATIONAL_UK,
        COLLECTION_NATIONAL_EU,
        COLLECTION_NATIONAL_RU,
        COLLECTION_NATIONAL_IL,
        COLLECTION_STATUTES_IN,
        COLLECTION_STATUTES_US,
        COLLECTION_STATUTES_UK,
        COLLECTION_STATUTES_EU,
        COLLECTION_STATUTES_RU,
        COLLECTION_STATUTES_IL,
    }:
        return collection_jurisdiction in allowed

    if collection == COLLECTION_CASE_LAW or collection in CASE_LAW_COLLECTIONS:
        return effective_jurisdiction in allowed

    return effective_jurisdiction in allowed if effective_jurisdiction else True


def _query_anchor_terms(query: str) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", query.lower()):
        if len(token) <= 2 or token in _ANCHOR_STOP_TERMS:
            continue
        if token not in seen:
            seen.add(token)
            anchors.append(token)
    return anchors[:8]


def _candidate_anchor_hits(anchors: list[str], candidate: dict[str, Any]) -> int:
    metadata = candidate.get("metadata") or {}
    haystack = " ".join(
        str(part or "")
        for part in [
            metadata.get("source_name"),
            metadata.get("citation"),
            metadata.get("doc_type"),
            metadata.get("collection"),
            candidate.get("text"),
        ]
    ).lower()
    return sum(1 for term in anchors if term in haystack)


def _filter_by_anchor_terms(query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    anchors = _query_anchor_terms(query)
    if not anchors or len(candidates) <= 1:
        return candidates
    scored = [(candidate, _candidate_anchor_hits(anchors, candidate)) for candidate in candidates]
    max_hits = max((hits for _, hits in scored), default=0)
    if max_hits >= 2:
        anchored = [candidate for candidate, hits in scored if hits >= 2]
    else:
        anchored = [candidate for candidate, hits in scored if hits > 0]
    return anchored or candidates


def _diversify_by_collection(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
    preferred_order: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Round-robin final results by collection so one source class cannot dominate."""
    if len(candidates) <= 2:
        return candidates[:limit]
    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    preferred = [str(col or "").upper() for col in (preferred_order or [])]
    for candidate in candidates:
        collection = str((candidate.get("metadata") or {}).get("collection") or "UNKNOWN").upper()
        if collection not in buckets:
            buckets[collection] = []
            order.append(collection)
        buckets[collection].append(candidate)

    if preferred:
        ordered_preferred = [col for col in preferred if col in buckets]
        order = ordered_preferred + [col for col in order if col not in set(ordered_preferred)]

    diversified: list[dict[str, Any]] = []
    seen: set[str] = set()
    while len(diversified) < min(limit, len(candidates)):
        added_this_round = False
        for collection in order:
            bucket = buckets[collection]
            while bucket:
                item = bucket.pop(0)
                key = item.get("text", "")[:120]
                if key in seen:
                    continue
                diversified.append(item)
                seen.add(key)
                added_this_round = True
                break
            if len(diversified) >= min(limit, len(candidates)):
                break
        if not added_this_round:
            break

    if len(diversified) < min(limit, len(candidates)):
        for item in candidates:
            key = item.get("text", "")[:120]
            if key not in seen:
                diversified.append(item)
                seen.add(key)
            if len(diversified) >= min(limit, len(candidates)):
                break
    return diversified


# Patterns that signal a named case, arbitration, or award is the subject of the query.
_NAMED_CASE_PATTERNS = [
    re.compile(r"\b[A-Z][A-Za-z\s]{2,40}(?:Arbitration|Award|Affair)\b"),
    re.compile(r"\b[A-Z][A-Za-z]+\s+v\.?\s+[A-Z][A-Za-z]+\b"),
    re.compile(
        r"\b(?:[A-Z](?:\.[A-Z])?\.?\s*)?[A-Z][A-Za-z.'-]+"
        r"(?:\s+[A-Z][A-Za-z.'-]+){0,4}\s+(?:case|Case)\b"
    ),
    re.compile(
        r"\b(?:Tinoco|Alabama Claims|Island of Palmas|Clipperton Island|Trail Smelter"
        r"|Corfu Channel|Nicaragua|Oil Platforms|Caroline|Lotus|Barcelona Traction"
        r"|Nottebohm|Chorzow Factory|DRC v\. Uganda)\b",
        re.IGNORECASE,
    ),
]

_COUNTRY_REFERENCE_PATTERNS = {
    "india": [
        re.compile(
            r"\b(?:"
            r"maneka\s+gandhi|"
            r"(?:justice\s+)?k\.?\s*s\.?\s+puttaswamy|puttaswamy|"
            r"kesavananda(?:\s+bharati)?|vishaka|"
            r"navtej(?:\s+singh\s+johar)?|shreya\s+singhal|"
            r"a\.?\s*k\.?\s+gopalan|minerva\s+mills|"
            r"information\s+technology\s+act|it\s+act|section\s+66a"
            r")\b",
            re.IGNORECASE,
        ),
    ],
}


def _query_names_a_case(query: str) -> bool:
    return any(pat.search(query) for pat in _NAMED_CASE_PATTERNS)


def _route_labels_from_query(query: str) -> list[str]:
    lowered = query.lower()
    labels: list[str] = []
    for label in _COUNTRY_ROUTE_LABELS:
        if len(label) == 2:
            # Avoid treating ordinary words such as "in" or "us" as ISO codes.
            matched = re.search(rf"\b{re.escape(label.upper())}\b", query)
        else:
            matched = re.search(rf"\b{re.escape(label)}\b", lowered)
        if matched:
            labels.append(label)
    for label, patterns in _COUNTRY_REFERENCE_PATTERNS.items():
        if label not in labels and any(pattern.search(query) for pattern in patterns):
            labels.append(label)
    if _is_source_discovery_query(query):
        labels.append("source_catalog")
    # When the query explicitly names a legal case or arbitration, inject a
    # sentinel label so route_to_collections always includes CASE_LAW and
    # SHAW_PRIVATE regardless of what issue labels are inferred.
    if _query_names_a_case(query):
        labels.append("named_case")
    return labels


def route_labels_from_query(query: str) -> list[str]:
    """Infer routing-only labels directly from the raw user query."""
    return _route_labels_from_query(query)


def _ensure_transformers_flagembedding_compat() -> None:
    """Shim removed transformers helpers still imported by FlagEmbedding."""
    try:
        import transformers.utils as transformers_utils
        import transformers.utils.import_utils as import_utils

        if not hasattr(import_utils, "is_torch_fx_available"):
            import_utils.is_torch_fx_available = lambda: False  # type: ignore[attr-defined]
        if not hasattr(transformers_utils, "is_torch_fx_available"):
            transformers_utils.is_torch_fx_available = import_utils.is_torch_fx_available  # type: ignore[attr-defined]
    except Exception:
        return


def _hf_model_cache_exists(model_name: str) -> bool:
    cache_root = Path(os.getenv("HF_HOME", Path.home() / ".cache" / "huggingface"))
    return (cache_root / "hub" / f"models--{model_name.replace('/', '--')}").exists()


def _get_reranker():
    global _reranker
    if _reranker is None:
        if not OMNILEGAL_ENABLE_HEAVY_MODELS and not _hf_model_cache_exists(RERANKER_MODEL):
            raise RuntimeError(
                f"{RERANKER_MODEL} is not cached; set OMNILEGAL_ENABLE_HEAVY_MODELS=1 to download it"
            )
        _ensure_transformers_flagembedding_compat()
        from FlagEmbedding import FlagReranker
        devices = preferred_torch_devices()
        batch_size = int(os.getenv("OMNILEGAL_RERANK_BATCH_SIZE", "8" if devices else "32"))
        _reranker = FlagReranker(
            RERANKER_MODEL,
            use_fp16=bool(devices),
            devices=devices,
            batch_size=batch_size,
        )
        _patch_prepare_for_model(getattr(_reranker, "tokenizer", None))
    return _reranker


def _patch_prepare_for_model(tokenizer: Any) -> None:
    """Restore the tokenizer helper removed in Transformers 5 for FlagEmbedding."""
    if tokenizer is None or hasattr(tokenizer, "prepare_for_model"):
        return

    def prepare_for_model(
        ids: list[int],
        pair_ids: list[int] | None = None,
        *,
        truncation: str | bool = False,
        max_length: int | None = None,
        padding: bool | str = False,
        **_kwargs: Any,
    ) -> dict[str, list[int]]:
        left = list(ids)
        right = list(pair_ids or [])
        if max_length:
            special = tokenizer.num_special_tokens_to_add(pair=bool(right))
            while len(left) + len(right) + special > max_length:
                if right and truncation in {"only_second", True, "longest_first"}:
                    right.pop()
                elif left:
                    left.pop()
                else:
                    break
        if hasattr(tokenizer, "build_inputs_with_special_tokens"):
            input_ids = tokenizer.build_inputs_with_special_tokens(left, right if pair_ids is not None else None)
        else:
            cls_id = tokenizer.cls_token_id if tokenizer.cls_token_id is not None else tokenizer.bos_token_id
            sep_id = tokenizer.sep_token_id if tokenizer.sep_token_id is not None else tokenizer.eos_token_id
            input_ids = ([cls_id] if cls_id is not None else []) + left
            if sep_id is not None:
                input_ids.append(sep_id)
            if pair_ids is not None:
                if sep_id is not None:
                    input_ids.append(sep_id)
                input_ids.extend(right)
                if sep_id is not None:
                    input_ids.append(sep_id)
        return {"input_ids": input_ids}

    setattr(tokenizer, "prepare_for_model", prepare_for_model)


class _TransformersReranker:
    def __init__(self, model_name: str):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name)
        if self.torch.cuda.is_available():
            self.model.to("cuda")
        self.model.eval()

    def compute_score(self, pairs: list[list[str]], normalize: bool = True) -> list[float]:
        scores: list[float] = []
        with self.torch.no_grad():
            for start in range(0, len(pairs), 8):
                batch = pairs[start : start + 8]
                encoded = self.tokenizer(
                    [pair[0] for pair in batch],
                    [pair[1] for pair in batch],
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                if self.torch.cuda.is_available():
                    encoded = {key: value.to("cuda") for key, value in encoded.items()}
                outputs = self.model(**encoded)
                logits = outputs.logits
                if logits.shape[-1] == 1:
                    batch_scores = logits.squeeze(-1)
                    if normalize:
                        batch_scores = self.torch.sigmoid(batch_scores)
                else:
                    batch_scores = self.torch.softmax(logits, dim=-1)[:, -1]
                scores.extend(float(value) for value in batch_scores.cpu().tolist())
        return scores


def _get_transformers_reranker() -> _TransformersReranker:
    global _transformers_reranker
    if _transformers_reranker is None:
        if not OMNILEGAL_ENABLE_HEAVY_MODELS and not _hf_model_cache_exists(RERANKER_MODEL):
            raise RuntimeError(f"{RERANKER_MODEL} is not cached")
        _transformers_reranker = _TransformersReranker(RERANKER_MODEL)
    return _transformers_reranker


def _embed_query(query: str) -> tuple[list[float], dict[int, float]]:
    """Returns (dense_vec, sparse_weights) for a query, using a simple in-memory cache."""
    # Use a simple module-level cache since EmbeddingCache stores numpy, not dicts
    if not hasattr(_embed_query, "_cache"):
        _embed_query._cache = {}  # type: ignore[attr-defined]
    
    cache_key = query.strip().lower()
    if cache_key in _embed_query._cache:  # type: ignore[attr-defined]
        cached = _embed_query._cache[cache_key]  # type: ignore[attr-defined]
        return cached["dense_vec"], cached["sparse_weights"]

    model = get_embed_model()
    out = model.encode(
        [query],
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
    )
    dense = out["dense_vecs"][0].tolist()
    sparse_raw = out["lexical_weights"][0]
    sparse = {int(k): float(v) for k, v in sparse_raw.items()}
    
    _embed_query._cache[cache_key] = {"dense_vec": dense, "sparse_weights": sparse}  # type: ignore[attr-defined]
    
    return dense, sparse


def hybrid_search(
    query: str,
    collection: str,
    *,
    k: int = RETRIEVAL_TOP_K_CANDIDATES,
) -> list[dict[str, Any]]:
    """
    Prefetch dense + sparse → RRF fusion → top-k results via Abstract Vector Store.
    Returns list of {text, score, metadata} dicts.
    """
    if not _USE_DENSE_RETRIEVAL:
        return _lexical_qdrant_search(query, collection, k=k)
    try:
        dense_vec, sparse_weights = _embed_query(query)
        store = get_store()
        return store.hybrid_search(
            query=query,
            dense_vec=dense_vec,
            sparse_weights=sparse_weights,
            collection=collection,
            k=k
        )
    except Exception as exc:
        print(f"Warning: hybrid search unavailable for {collection} ({exc}); using lexical fallback")
        return _lexical_qdrant_search(query, collection, k=k)


def _qdrant_request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    # Deprecated fallback requests
    url = f"{QDRANT_URL.rstrip('/')}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=_QDRANT_REST_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def _existing_collections() -> set[str]:
    global _collection_cache
    now = time.time()
    if _collection_cache and now - _collection_cache[0] < 15:
        return set(_collection_cache[1])
    try:
        collections = get_store().available_collections()
        _collection_cache = (now, set(collections))
        return set(collections)
    except Exception:
        _collection_cache = (now, set())
        return set()


def _lexical_qdrant_search(query: str, collection: str, *, k: int = RETRIEVAL_TOP_K_CANDIDATES) -> list[dict[str, Any]]:
    if collection not in _existing_collections():
        return []

    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in {"the", "and", "for", "about", "tell", "what", "how", "does"}
    }
    try:
        return get_store().lexical_search(query=query, query_terms=query_terms, collection=collection, k=k)
    except Exception as exc:
        print(f"Warning: lexical fallback failed for {collection}: {exc}")
        return []


_SEED_CASES: list[dict[str, Any]] | None = None


def _load_seed_cases() -> list[dict[str, Any]]:
    global _SEED_CASES
    if _SEED_CASES is not None:
        return _SEED_CASES
    path = OMNILEGAL_DIR / "configs" / "seed_cases.jsonl"
    cases: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    cases.append(json.loads(line))
                except Exception:
                    pass
    _SEED_CASES = cases
    return cases


def seed_case_search(query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    """Keyword search over the seed_cases.jsonl fallback corpus.

    Returns passages in the standard {text, score, metadata} format so they
    can be merged with Qdrant results.  Called when primary retrieval returns
    fewer than 3 case-law hits for a named-case query.
    """
    cases = _load_seed_cases()
    if not cases:
        return []

    query_terms = {
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in {
            "the", "and", "for", "about", "tell", "what", "how", "does",
            "case", "law", "legal", "court",
        }
    }
    hits: list[dict[str, Any]] = []
    for entry in cases:
        text = entry.get("text", "")
        meta = entry.get("metadata", {})
        haystack = (text + " " + meta.get("source_name", "") + " " + meta.get("citation", "")).lower()
        # Count matching terms; give bonus for source name exact match.
        term_hits = sum(1 for t in query_terms if t in haystack)
        source_bonus = 2.0 if any(t in meta.get("source_name", "").lower() for t in query_terms) else 0.0
        score = float(term_hits) + source_bonus
        if score > 0:
            hits.append({
                "text": text,
                "score": score,
                "metadata": {**meta, "from_seed": True},
            })

    return sorted(hits, key=lambda h: h["score"], reverse=True)[:top_k]


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    *,
    top_n: int = RERANK_TOP_N,
    query_intent: dict[str, Any] | None = None,
    iso_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Cross-encoder reranking.

    By the time candidates reach this function, hard filtering has already
    happened upstream (wrong jurisdictions discarded, noise sources removed,
    collections restricted).  Rerank only scores and sorts — no soft penalties.

    Collection weights are already baked into candidate scores via
    multiplicative application in retriever_node.
    """
    if not candidates:
        return []

    if not OMNILEGAL_ENABLE_HEAVY_MODELS:
        for candidate in candidates:
            candidate["rerank_score"] = _fallback_rerank_score(query, candidate)
    else:
        try:
            reranker = _get_reranker()
            pairs = [[query, c["text"]] for c in candidates]
            try:
                scores = reranker.compute_score(pairs, normalize=True)
            except Exception as primary_exc:
                if not OMNILEGAL_ENABLE_HEAVY_MODELS:
                    raise primary_exc
                print(f"Warning: FlagEmbedding reranker failed ({primary_exc}); trying transformers reranker")
                scores = _get_transformers_reranker().compute_score(pairs, normalize=True)
            if isinstance(scores, float):
                scores = [scores]
            for i, c in enumerate(candidates):
                c["rerank_score"] = float(scores[i])
        except Exception as exc:
            print(f"Warning: reranking failed ({exc}), using fallback score")
            for candidate in candidates:
                candidate["rerank_score"] = _fallback_rerank_score(query, candidate)

    # Apply collection_weight as a multiplier (set upstream in retriever_node)
    for c in candidates:
        weight = c.get("collection_weight", 1.0)
        metadata = c.get("metadata") or {}
        tier = infer_authority_tier(metadata)
        metadata["authority_tier"] = tier
        try:
            importance_score = max(0.0, min(1.0, float(metadata.get("importance_score") or 0.0)))
        except (TypeError, ValueError):
            importance_score = 0.0
        importance_multiplier = 1.0 + (0.25 * importance_score)
        authority_multiplier = authority_weight(tier)
        c["importance_multiplier"] = importance_multiplier
        c["authority_multiplier"] = authority_multiplier
        c["rerank_score"] = c.get("rerank_score", 0.0) * weight * importance_multiplier * authority_multiplier

    return sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)[:top_n]


def _hit_from_point(point: Any, *, score: float = 0.05) -> dict[str, Any]:
    payload = dict(getattr(point, "payload", None) or {})
    payload.pop("index_text", None)
    text = payload.pop("raw_text", "") or payload.pop("text", "") or payload.get("content", "")
    return {"text": text, "score": score, "metadata": payload}


def _scroll_payload_matches(collection: str, key: str, value: Any, *, limit: int = 2) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []
    return get_store().scroll_payload_matches(collection, key, value, limit)


def _article_references(text: str) -> list[str]:
    seen: set[str] = set()
    refs: list[str] = []
    for match in re.finditer(r"\bArticle\s+(\d+[A-Za-z0-9()\-./]*)", text or "", flags=re.IGNORECASE):
        article = match.group(1).strip(" .")
        if article not in seen:
            seen.add(article)
            refs.append(article)
    return refs[:4]


def _same_source_metadata(left: dict[str, Any], right: dict[str, Any]) -> bool:
    for key in ("source_name", "citation", "source_url", "title"):
        left_value = str(left.get(key) or "").strip().lower()
        right_value = str(right.get(key) or "").strip().lower()
        if left_value and right_value and left_value == right_value:
            return True
    return False


def expand_linked_passages(passages: list[dict[str, Any]], *, max_results: int) -> list[dict[str, Any]]:
    """Parent, footnote-sibling, and article cross-reference expansion."""
    expanded: list[dict[str, Any]] = []
    seen_text: set[str] = set()

    def add(hit: dict[str, Any]) -> None:
        text = " ".join((hit.get("text") or "").split())
        if not text or text[:180] in seen_text or len(expanded) >= max_results:
            return
        seen_text.add(text[:180])
        expanded.append(hit)

    for passage in passages:
        add(passage)
        if len(expanded) >= max_results:
            break
        meta = passage.get("metadata") or {}
        collection = meta.get("collection")
        if not collection:
            continue

        parent_id = meta.get("parent_id")
        if parent_id:
            for linked in _scroll_payload_matches(collection, "parent_id", parent_id, limit=2):
                linked["score"] = min(float(passage.get("score", 0.0)), 0.2)
                linked["metadata"]["expansion_reason"] = "parent_sibling"
                add(linked)
                if len(expanded) >= max_results:
                    break

        for footnote_id in (meta.get("footnote_ids") or [])[:2]:
            for linked in _scroll_payload_matches(collection, "parent_id", footnote_id, limit=1):
                linked["score"] = min(float(passage.get("score", 0.0)), 0.2)
                linked["metadata"]["expansion_reason"] = "footnote_sibling"
                add(linked)
                if len(expanded) >= max_results:
                    break

        for article in _article_references(passage.get("text", "")):
            for linked in _scroll_payload_matches(collection, "article_number", article, limit=4):
                linked_metadata = linked.setdefault("metadata", {})
                if not isinstance(linked_metadata, dict) or not _same_source_metadata(meta, linked_metadata):
                    continue
                linked["score"] = min(float(passage.get("score", 0.0)), 0.2)
                linked_metadata["expansion_reason"] = "article_cross_reference"
                add(linked)
                if len(expanded) >= max_results:
                    break

    return expanded[:max_results]


def _fallback_rerank_score(query: str, candidate: dict[str, Any]) -> float:
    """Cheap deterministic ordering used when the cross-encoder is unavailable."""
    metadata = candidate.get("metadata") or {}
    haystack = " ".join(
        str(part or "")
        for part in [
            metadata.get("source_name"),
            metadata.get("citation"),
            metadata.get("doc_type"),
            metadata.get("collection"),
            candidate.get("text"),
        ]
    ).lower()
    terms = [
        token for token in re.findall(r"[a-z0-9]+", query.lower())
        if len(token) > 2 and token not in {"tell", "about", "what", "case", "law", "legal"}
    ]
    lexical_hits = sum(1 for term in terms if term in haystack)
    # Dense cosine score is in [0, 1]. Lexical bonuses must stay sub-dominant
    # so a bag-of-words match on common stems ("fundamental", "right") cannot
    # outrank a true semantic hit. Cap total lexical contribution at ~0.2.
    score = float(candidate.get("score", 0.0)) + min(0.05 * lexical_hits, 0.2)
    collection = str(metadata.get("collection", "")).upper()
    if "case" in query.lower() and (
        str(metadata.get("doc_type", "")).lower() == "case_law"
        or collection == "CASE_LAW"
        or collection in CASE_LAW_COLLECTIONS
    ):
        score += 0.75
    # Strong boost when the query names a specific case/arbitration and the
    # passage metadata or text contains those same tokens (exact case match).
    if _query_names_a_case(query) and (
        str(metadata.get("doc_type", "")).lower() == "case_law"
        or collection == "CASE_LAW"
        or collection in CASE_LAW_COLLECTIONS
    ):
        score += 1.5
    if str(metadata.get("doc_type", "")).lower() == "source_catalog":
        score += 2.0 if _is_source_discovery_query(query) else -1.5
    return score


def route_to_collections(issue_labels: list[str]) -> list[str]:
    """Map issue labels to relevant Qdrant collections."""
    normalized_labels = [str(label or "").lower() for label in issue_labels]
    if "source_catalog" in normalized_labels:
        source_country_collections: list[str] = []
        seen_source_countries: set[str] = set()
        for key in normalized_labels:
            for col in _COUNTRY_ROUTE_LABELS.get(key, []):
                if col not in seen_source_countries:
                    seen_source_countries.add(col)
                    source_country_collections.append(col)
        if source_country_collections:
            return source_country_collections

    country_collections: list[str] = []
    seen_country_collections: set[str] = set()
    for key in normalized_labels:
        for col in _COUNTRY_ROUTE_LABELS.get(key, []):
            if col not in seen_country_collections:
                seen_country_collections.add(col)
                country_collections.append(col)

    if country_collections and "named_case" in normalized_labels:
        # A named case with an explicit/inferred country should search that
        # country's law first. Expanding generic CASE_LAW first makes unrelated
        # global cases win the final collection-diversity pass.
        country_case_law = [col for col in country_collections if col in CASE_LAW_COLLECTIONS]
        country_non_case_law = [col for col in country_collections if col not in set(country_case_law)]
        result = country_case_law + country_non_case_law
        seen_named_country = set(result)
        for col in (
            COLLECTION_CASE_LAW_GLOBAL,
            COLLECTION_SHAW_PRIVATE,
            COLLECTION_COMMENTARY,
            COLLECTION_INTL_TREATIES,
        ):
            if col not in seen_named_country:
                seen_named_country.add(col)
                result.append(col)
        return result

    if country_collections and "named_case" not in normalized_labels:
        # Intent-first fallback for legacy callers: once a country is present,
        # do not let broad issue labels inject global CASE_LAW.
        result = list(country_collections)
        for col in (COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY, COLLECTION_SHAW_PRIVATE):
            if col not in seen_country_collections:
                seen_country_collections.add(col)
                result.append(col)
        return result

    # Resolve named-case sentinel first so CASE_LAW + SHAW_PRIVATE lead the list.
    named_case_cols: list[str] = []
    if "named_case" in normalized_labels:
        named_case_cols = list(ISSUE_COLLECTION_MAP["named_case"])

    collections: list[str] = list(named_case_cols)
    seen: set[str] = set(named_case_cols)
    for label in issue_labels:
        key = str(label or "").lower()
        if key == "named_case":
            continue  # already handled above
        if key in _COUNTRY_ROUTE_LABELS:
            # Country labels are hard-routing signals. Do not add global
            # CASE_LAW here; country-specific case law should come through the
            # national collection unless the query explicitly has named_case.
            candidates = _COUNTRY_ROUTE_LABELS[key] + [COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY]
        else:
            candidates = ISSUE_COLLECTION_MAP.get(label, ISSUE_COLLECTION_MAP.get(key, ISSUE_COLLECTION_MAP["default"]))
        for col in candidates:
            if col not in seen:
                seen.add(col)
                collections.append(col)
    if not collections:
        return ISSUE_COLLECTION_MAP["default"]
    return collections


def _rrf_merge(
    results_per_collection: dict[str, list[dict[str, Any]]],
    *,
    c: int = RRF_K,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion across multiple collections."""
    scores: dict[str, float] = {}
    docs: dict[str, dict[str, Any]] = {}

    for col_results in results_per_collection.values():
        for rank, hit in enumerate(col_results):
            key = hit["text"][:120]
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank + c)
            docs[key] = hit

    return sorted(docs.values(), key=lambda h: scores[h["text"][:120]], reverse=True)


def multi_collection_retrieve(
    query: str,
    issue_labels: list[str],
    *,
    k: int = RERANK_TOP_N,
) -> list[dict[str, Any]]:
    """
    Fan-out hybrid search across routed collections → RRF merge → rerank.
    Returns top-k passages ready for the LLM.
    """
    collections = expand_collection_aliases(route_to_collections(issue_labels))
    collections = _drop_domestic_case_law_without_country(collections, issue_labels)
    existing = _existing_collections()
    if existing:
        collections = [col for col in collections if col in existing]
    allowed_countries = _country_constraints(issue_labels)
    results_per_col: dict[str, list[dict[str, Any]]] = {}

    start_time = time.time()
    for col in collections:
        if time.time() - start_time > OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS:
            print("Retrieval hard deadline exceeded, returning partial results.")
            break
        try:
            hits = hybrid_search(query, col, k=RETRIEVAL_TOP_K_CANDIDATES)
            if hits:
                filtered: list[dict[str, Any]] = []
                for hit in hits:
                    metadata = hit.setdefault("metadata", {})
                    if isinstance(metadata, dict):
                        metadata.setdefault("collection", col)
                    if _candidate_allowed_for_query(query, hit, allowed_countries):
                        filtered.append(hit)
                if filtered:
                    results_per_col[col] = filtered
        except Exception as exc:
            print(f"Warning: search failed for collection {col}: {exc}")

    if not results_per_col:
        return []

    merged = _filter_by_anchor_terms(query, _rrf_merge(results_per_col))
    ranked = rerank(query, merged, top_n=min(len(merged), max(k * 20, k)))
    ranked = _diversify_by_collection(ranked, limit=k, preferred_order=collections)
    expanded = expand_linked_passages(ranked, max_results=max(k * 3, k))
    return _diversify_by_collection(expanded, limit=k, preferred_order=collections)


# ── Backward-compat helpers for existing Streamlit pages / services ──────

def normalize_query_text(query: str) -> str:
    """Normalize query text — strip excess whitespace and lowercase for BM25."""
    import re
    return re.sub(r"\s+", " ", query.strip())


def _matches_filters(doc: Any, filters: dict[str, Any] | None) -> bool:
    """Backward-compatible metadata filter used by older tests/pages."""
    if not filters:
        return True
    metadata = getattr(doc, "metadata", None) or {}
    for key, expected in filters.items():
        actual = metadata.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


class _RetrieverShim:
    """Wraps a retrieval function so it looks like a LangChain Runnable."""
    def __init__(self, fn):
        self._fn = fn

    def invoke(self, query: str):
        return self._fn(query)

    def __call__(self, query: str):
        return self._fn(query)

    def __bool__(self):
        return True


def search_documents(
    query: str,
    jurisdiction: str | None = None,
    k: int = 5,
    *,
    collections: list[str] | None = None,
    **_kwargs: Any,
) -> list[dict[str, Any]]:
    issue_labels = ([jurisdiction] if jurisdiction else []) + _route_labels_from_query(query)
    explicit_collections = collections is not None
    target_cols = expand_collection_aliases(collections or route_to_collections(issue_labels) or ALL_COLLECTIONS)
    if not explicit_collections:
        target_cols = _drop_domestic_case_law_without_country(target_cols, issue_labels)
    allowed_countries = _country_constraints(issue_labels)
    existing = _existing_collections()
    if existing:
        target_cols = [col for col in target_cols if col in existing]
    results_per_col: dict[str, list[dict[str, Any]]] = {}
    
    start_time = time.time()
    for col in target_cols:
        if time.time() - start_time > OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS:
            print("Retrieval hard deadline exceeded, returning partial results.")
            break
        try:
            hits = hybrid_search(query, col, k=RETRIEVAL_TOP_K_CANDIDATES)
            if hits:
                filtered: list[dict[str, Any]] = []
                for hit in hits:
                    metadata = hit.setdefault("metadata", {})
                    if isinstance(metadata, dict):
                        metadata.setdefault("collection", col)
                    if _candidate_allowed_for_query(query, hit, allowed_countries):
                        filtered.append(hit)
                if filtered:
                    results_per_col[col] = filtered
        except Exception as exc:
            print(f"Warning: search failed for {col}: {exc}")
    if not results_per_col:
        return []
    merged = _filter_by_anchor_terms(query, _rrf_merge(results_per_col))
    ranked = rerank(query, merged, top_n=min(len(merged), max(k * 20, k)))
    ranked = _diversify_by_collection(ranked, limit=k, preferred_order=target_cols)
    expanded = expand_linked_passages(ranked, max_results=max(k * 3, k))
    return _diversify_by_collection(expanded, limit=k, preferred_order=target_cols)


def get_hybrid_retriever(
    k: int = 5,
    *,
    collections: list[str] | None = None,
    **_kwargs: Any,
) -> _RetrieverShim:
    """Returns a shim with .invoke() that mimics the old FAISS retriever API."""
    def _retrieve(query: str) -> list[dict[str, Any]]:
        return search_documents(query, k=k, collections=collections)
    return _RetrieverShim(_retrieve)
