"""Source Availability Registry — evidence-first gate.

Loads ``configs/source_registry.yaml`` and checks Qdrant collections for
the *existence* of required sources before retrieval is attempted.

This module is the single source of truth for what must be indexed per
recognised topic.  If a required source bundle is absent the pipeline
fails early with a clear message rather than hallucinating an answer.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SourceRequirement:
    role: str
    source_pattern: str
    collection: str
    description: str
    required: bool = True


@dataclass
class TopicSourceMap:
    topic: str
    required: list[SourceRequirement] = field(default_factory=list)
    optional: list[SourceRequirement] = field(default_factory=list)


@dataclass(frozen=True)
class AvailabilityResult:
    ok: bool
    missing: list[str] = field(default_factory=list)
    present: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Topic detection (mirrors simple_legal_runtime logic, kept deterministic)
# ---------------------------------------------------------------------------

_TOPIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("diplomatic_immunity", re.compile(
        r"\b(diplomatic\s+immun\w*|vienna\s+convention\s+on\s+diplomatic|arrest\s+warrant)\b", re.I)),
    ("driving_india_russia", re.compile(
        r"\b(driv(?:e|ing)|licen[cs]e|permit|road\s+traffic|vehicle)\b", re.I)),
    ("bns_69", re.compile(
        r"\b(bns|bharatiya\s+nyaya|section\s*69|deceitful\s+means)\b", re.I)),
    ("murder_sentencing", re.compile(
        r"\b(murder|homicide|life\s+imprisonment|death\s+penalty|sentencing)\b", re.I)),
    ("tinoco", re.compile(
        r"\b(tinoco|great\s+britain\s+v\s+costa\s+rica)\b", re.I)),
    ("wall", re.compile(
        r"\b(wall\s+advisory|construction\s+of\s+a\s+wall|occupied\s+palestinian)\b", re.I)),
    ("travel_india_russia", re.compile(
        r"\b(travel|visa|e-?visa|passport|tourist|entry)\b", re.I)),
]

_COUNTRY_RE: dict[str, re.Pattern[str]] = {
    "india":  re.compile(r"\b(india|indian)\b", re.I),
    "russia": re.compile(r"\b(russia|russian)\b", re.I),
}


def detect_topics(query: str) -> list[str]:
    """Return recognised topic keys from user query text."""
    lowered = query.lower()
    hits: list[str] = []
    for topic, pattern in _TOPIC_RULES:
        if pattern.search(lowered):
            # driving_india_russia requires both countries mentioned
            if topic == "driving_india_russia":
                if _COUNTRY_RE["india"].search(lowered) and _COUNTRY_RE["russia"].search(lowered):
                    hits.append(topic)
                # else: skip — single-country driving goes to default
            elif topic == "travel_india_russia":
                if _COUNTRY_RE["india"].search(lowered) and _COUNTRY_RE["russia"].search(lowered):
                    hits.append(topic)
            else:
                hits.append(topic)
    return hits or ["default"]


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

def _load_registry_yaml() -> dict[str, TopicSourceMap]:
    """Parse ``configs/source_registry.yaml`` into TopicSourceMap objects."""
    yaml_path = _PROJECT_ROOT / "configs" / "source_registry.yaml"
    if not yaml_path.exists():
        print(f"Warning: source registry not found at {yaml_path}")
        return {}

    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        # Fallback: minimal YAML-like parse (only for simple structure)
        return _fallback_parse(yaml_path)

    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    registry: dict[str, TopicSourceMap] = {}
    for topic_key, topic_data in (data.get("topics") or {}).items():
        tsm = TopicSourceMap(topic=topic_key)
        for req in topic_data.get("required") or []:
            tsm.required.append(SourceRequirement(
                role=req["role"],
                source_pattern=req.get("source_pattern", ""),
                collection=req.get("collection", ""),
                description=req.get("description", ""),
                required=True,
            ))
        for opt in topic_data.get("optional") or []:
            tsm.optional.append(SourceRequirement(
                role=opt["role"],
                source_pattern=opt.get("source_pattern", ""),
                collection=opt.get("collection", ""),
                description=opt.get("description", ""),
                required=False,
            ))
        registry[topic_key] = tsm

    # default topic
    default_data = data.get("default") or {}
    default_tsm = TopicSourceMap(topic="default")
    for opt in default_data.get("optional") or []:
        default_tsm.optional.append(SourceRequirement(
            role=opt["role"],
            source_pattern=opt.get("source_pattern", ""),
            collection=opt.get("collection", ""),
            description=opt.get("description", ""),
            required=False,
        ))
    registry["default"] = default_tsm
    return registry


def _fallback_parse(yaml_path: Path) -> dict[str, TopicSourceMap]:
    """Minimal parse when PyYAML is unavailable — returns empty."""
    print("Warning: PyYAML not installed; source registry not loaded.")
    return {"default": TopicSourceMap(topic="default")}


# ---------------------------------------------------------------------------
# Registry class
# ---------------------------------------------------------------------------

_CACHED_REGISTRY: dict[str, TopicSourceMap] | None = None


def _get_registry() -> dict[str, TopicSourceMap]:
    global _CACHED_REGISTRY
    if _CACHED_REGISTRY is None:
        _CACHED_REGISTRY = _load_registry_yaml()
    return _CACHED_REGISTRY


def reload_registry() -> None:
    """Force reload of the YAML registry (call after re-seeding)."""
    global _CACHED_REGISTRY
    _CACHED_REGISTRY = None


class IndexedSourcesRegistry:
    """Checks Qdrant collections for existence of required sources."""

    def __init__(self) -> None:
        self._collection_counts: dict[str, int] = {}
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        try:
            from src.rag.vector_store import get_store
            store = get_store()
            for col in store.available_collections():
                try:
                    count = store.collection_point_count(col)
                    self._collection_counts[col] = count
                except Exception:
                    self._collection_counts[col] = 0
        except Exception as exc:
            print(f"Warning: could not load Qdrant collection info: {exc}")
        self._loaded = True

    def collection_has_source(self, collection: str, source_pattern: str) -> bool:
        """Check if a collection has any indexed points.

        The source_pattern is informational — actual content matching
        happens during retrieval.  The gate only checks that the
        collection is non-empty.
        """
        self._ensure_loaded()
        return self._collection_counts.get(collection, 0) > 0

    def check_availability(self, topics: list[str]) -> AvailabilityResult:
        """Check all required sources for the given topics."""
        registry = _get_registry()
        missing: list[str] = []
        present: list[str] = []

        for topic in topics:
            tsm = registry.get(topic, registry.get("default"))
            if tsm is None:
                continue
            for req in tsm.required:
                if self.collection_has_source(req.collection, req.source_pattern):
                    present.append(f"{req.role}:{req.description}")
                else:
                    missing.append(f"Missing required source: {req.role} — {req.description} (collection: {req.collection})")

        return AvailabilityResult(
            ok=len(missing) == 0,
            missing=missing,
            present=present,
        )

    def get_required_roles(self, topics: list[str]) -> list[SourceRequirement]:
        """Return all required SourceRequirements for the given topics."""
        registry = _get_registry()
        requirements: list[SourceRequirement] = []
        seen: set[str] = set()
        for topic in topics:
            tsm = registry.get(topic, registry.get("default"))
            if tsm is None:
                continue
            for req in tsm.required:
                key = f"{req.role}:{req.collection}:{req.source_pattern}"
                if key not in seen:
                    seen.add(key)
                    requirements.append(req)
        return requirements

    def get_target_collections(self, topics: list[str]) -> list[str]:
        """Return the set of Qdrant collections relevant to the topics."""
        registry = _get_registry()
        collections: list[str] = []
        seen: set[str] = set()
        for topic in topics:
            tsm = registry.get(topic, registry.get("default"))
            if tsm is None:
                continue
            for req in tsm.required + tsm.optional:
                if req.collection and req.collection not in seen:
                    seen.add(req.collection)
                    collections.append(req.collection)
        return collections
