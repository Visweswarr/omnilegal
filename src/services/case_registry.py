"""Canonical-case alias resolver.

Loads ``configs/landmark_registry.yaml`` and ``configs/seed_cases.jsonl`` once
and exposes a :func:`resolve` that maps user-typed strings (e.g. "Albania vs
UK", "Corfu Channel Case") to a single :class:`CaseEntry` carrying the
canonical name, court, year, jurisdiction, tags and a short summary.

The Citation Graph (Pillar 07) uses this so that "Albania vs UK" no longer
becomes a free-floating topic node disconnected from the actual Corfu Channel
material in the corpus.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger("omnilegal.case_registry")

_CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "configs"
_LANDMARK_PATH = _CONFIG_DIR / "landmark_registry.yaml"
_SEED_CASES_PATH = _CONFIG_DIR / "seed_cases.jsonl"


@dataclass(frozen=True)
class CaseEntry:
    canonical_name: str
    aliases: tuple[str, ...] = ()
    court: str = ""
    year: int | None = None
    jurisdiction: str = ""
    tags: tuple[str, ...] = ()
    summary: str = ""
    citation: str = ""

    @property
    def display_label(self) -> str:
        bits = [self.canonical_name]
        if self.court:
            bits.append(self.court)
        if self.year:
            bits.append(str(self.year))
        return " · ".join(bits)


_PARTY_SHORTHAND = {
    "uk": "united kingdom",
    "us": "united states",
    "usa": "united states",
    "drc": "democratic republic of the congo",
    "ussr": "soviet union",
}


def _normalise(text: str) -> str:
    """Lowercase, collapse whitespace, normalise v/v./vs/vs. and party shorthand."""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r"\s+", " ", s)
    # Unify the versus separator: 'v', 'v.', 'vs', 'vs.' all become ' v '
    s = re.sub(r"\bvs?\.?\b", "v", s)
    # Drop trailing "case" / "arbitration" / "advisory opinion"
    s = re.sub(r"\b(case|arbitration|advisory opinion)\b", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .,-—")
    # Expand jurisdiction shorthand around the v separator
    parts = [p.strip() for p in s.split(" v ")]
    parts = [_PARTY_SHORTHAND.get(p, p) for p in parts]
    s = " v ".join(p for p in parts if p)
    return s


def _swap_parties(normalised: str) -> str | None:
    """If the form is 'A v B', return 'B v A'; else None."""
    if " v " not in normalised:
        return None
    a, _, b = normalised.partition(" v ")
    a, b = a.strip(), b.strip()
    if not a or not b:
        return None
    return f"{b} v {a}"


@dataclass
class _Index:
    by_key: dict[str, CaseEntry] = field(default_factory=dict)
    entries: list[CaseEntry] = field(default_factory=list)


_INDEX: _Index | None = None


def _iter_alias_keys(canonical: str, aliases: Iterable[str]) -> Iterable[str]:
    seen: set[str] = set()
    for raw in (canonical, *aliases):
        key = _normalise(raw)
        if key and key not in seen:
            seen.add(key)
            yield key
        swapped = _swap_parties(key) if key else None
        if swapped and swapped not in seen:
            seen.add(swapped)
            yield swapped


def _load_landmark_yaml() -> list[dict]:
    if not _LANDMARK_PATH.exists():
        log.warning("landmark_registry.yaml missing at %s", _LANDMARK_PATH)
        return []
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        log.warning("pyyaml not available — case registry will be empty")
        return []
    with _LANDMARK_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return list(data.get("landmarks") or [])


def _load_seed_cases() -> list[dict]:
    if not _SEED_CASES_PATH.exists():
        return []
    rows: list[dict] = []
    with _SEED_CASES_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _build_index() -> _Index:
    idx = _Index()
    seen_canonicals: dict[str, CaseEntry] = {}

    for raw in _load_landmark_yaml():
        canonical = (raw.get("canonical_name") or "").strip()
        if not canonical:
            continue
        aliases = tuple(raw.get("aliases") or [])
        entry = CaseEntry(
            canonical_name=canonical,
            aliases=aliases,
            court=(raw.get("court") or "").strip(),
            year=raw.get("year"),
            tags=tuple(raw.get("tags") or []),
            summary=(raw.get("summary") or "").strip(),
        )
        seen_canonicals[_normalise(canonical)] = entry
        idx.entries.append(entry)
        for key in _iter_alias_keys(canonical, aliases):
            idx.by_key.setdefault(key, entry)

    # Layer seed_cases.jsonl on top — adds jurisdiction / citation / summary
    # to landmarks already loaded, and registers any case missing from the YAML.
    for row in _load_seed_cases():
        meta = row.get("metadata") or {}
        canonical = (meta.get("source_name") or "").strip()
        if not canonical:
            continue
        norm_key = _normalise(canonical)
        existing = seen_canonicals.get(norm_key)
        merged = CaseEntry(
            canonical_name=existing.canonical_name if existing else canonical,
            aliases=tuple(existing.aliases) if existing else (),
            court=(existing.court if existing and existing.court else (meta.get("court") or "")),
            year=(existing.year if existing and existing.year else meta.get("year")),
            jurisdiction=(meta.get("jurisdiction") or "").strip(),
            tags=tuple(existing.tags) if existing and existing.tags else tuple(meta.get("tags") or []),
            summary=existing.summary if existing and existing.summary else (row.get("text") or "")[:600],
            citation=(meta.get("citation") or "").strip(),
        )
        seen_canonicals[norm_key] = merged
        if existing:
            try:
                pos = idx.entries.index(existing)
                idx.entries[pos] = merged
            except ValueError:
                idx.entries.append(merged)
        else:
            idx.entries.append(merged)
        for key in _iter_alias_keys(merged.canonical_name, merged.aliases):
            idx.by_key[key] = merged
        # Citation strings often look like "United Kingdom v. Albania, ICJ Reports 1949"
        # — register the leading clause (before the comma) as another alias key.
        if merged.citation:
            head = merged.citation.split(",", 1)[0]
            for key in _iter_alias_keys(head, ()):
                idx.by_key.setdefault(key, merged)

    log.info(
        "case_registry loaded: %d canonical entries, %d alias keys",
        len(idx.entries),
        len(idx.by_key),
    )
    return idx


def _index() -> _Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    return _INDEX


def reload() -> None:
    """Force-reload the registry (useful in tests / after config edits)."""
    global _INDEX
    _INDEX = None
    _index()


def resolve(text: str) -> CaseEntry | None:
    """Return the canonical :class:`CaseEntry` for ``text`` or ``None``.

    Tries (1) exact normalised match, (2) party-swapped normalised match,
    (3) substring containment of any registered alias inside ``text``.
    """
    if not text or not text.strip():
        return None
    idx = _index()
    norm = _normalise(text)
    if not norm:
        return None
    if norm in idx.by_key:
        return idx.by_key[norm]
    swapped = _swap_parties(norm)
    if swapped and swapped in idx.by_key:
        return idx.by_key[swapped]
    # Substring containment — handles "look up Corfu Channel for me" style input.
    # Prefer the longest-matching key so "nicaragua v united states" wins over "nicaragua".
    candidates = [k for k in idx.by_key if k and k in norm]
    if candidates:
        candidates.sort(key=len, reverse=True)
        return idx.by_key[candidates[0]]
    return None


def all_aliases_for(entry: CaseEntry) -> list[str]:
    """Return the canonical name plus every registered alias."""
    out: list[str] = [entry.canonical_name]
    for a in entry.aliases:
        if a and a not in out:
            out.append(a)
    return out


def passage_anchors_case(passage_text: str, entry: CaseEntry) -> bool:
    """True if ``passage_text`` mentions the canonical case (or any alias)."""
    if not passage_text:
        return False
    haystack = passage_text.lower()
    for label in all_aliases_for(entry):
        norm = label.lower().strip()
        if not norm:
            continue
        if norm in haystack:
            return True
    # Also match the normalised v/vs form, in case the corpus writes "UK v Albania".
    norm_hay = _normalise(passage_text)
    for label in all_aliases_for(entry):
        nl = _normalise(label)
        if nl and nl in norm_hay:
            return True
    return False
