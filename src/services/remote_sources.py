"""Remote source cataloging and bounded ingestion for OmniLegal.

The catalog files in ``omnilegal/caselaws`` describe sources, not always raw
documents. This module turns each entry into a searchable manifest row and, when
allowed by source terms and local credentials, fetches bounded linked content.
"""
from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from src.config import (
    CASELAWS_DIR,
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
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    CONGRESS_API_KEY,
    COURTLISTENER_TOKEN,
    GOVINFO_API_KEY,
    HF_TOKEN,
    INDIAN_KANOON_API_TOKEN,
    OMNILEGAL_DIR,
    OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE,
    OMNILEGAL_REMOTE_MIN_FREE_GB,
    REMOTE_LICENSE_GATES,
    REMOTE_SOURCES_DIR,
    ROOT_DIR,
    SEC_USER_AGENT,
)
from src.services.legal_chunking import structured_legal_chunks


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    catalog_file: str
    group_index: int
    source_index: int
    jurisdiction: str
    name: str
    url: str
    source_type: str
    coverage: str
    access: str
    source_format: str
    license_note: str
    recommended_for: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourcePlan:
    source_id: str
    collection: str
    tier: int
    adapter: str
    action: str
    metadata_only: bool
    allowed_to_fetch: bool
    blocked_reason: str
    required_env: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)


@dataclass
class BudgetManager:
    root: Path
    budget_bytes: int
    min_free_bytes: int
    used_bytes: int = 0

    def can_store(self, next_bytes: int) -> bool:
        free = shutil.disk_usage(self.root).free
        if free - next_bytes < self.min_free_bytes:
            return False
        return self.used_bytes + next_bytes <= self.budget_bytes

    def reserve(self, size: int) -> bool:
        if not self.can_store(size):
            return False
        self.used_bytes += size
        return True


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        clean = " ".join(html.unescape(data).split())
        if clean:
            self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(self.parts)


_COLLECTION_BY_JURISDICTION = {
    "us": COLLECTION_NATIONAL_US,
    "united states": COLLECTION_NATIONAL_US,
    "uk": COLLECTION_NATIONAL_UK,
    "united kingdom": COLLECTION_NATIONAL_UK,
    "eu": COLLECTION_NATIONAL_EU,
    "european union": COLLECTION_NATIONAL_EU,
    "in": COLLECTION_NATIONAL_IN,
    "india": COLLECTION_NATIONAL_IN,
    "russia": COLLECTION_NATIONAL_RU,
    "russian federation": COLLECTION_NATIONAL_RU,
    "israel": COLLECTION_NATIONAL_IL,
    "international": COLLECTION_COMMENTARY_GLOBAL,
    "international bodies": COLLECTION_COMMENTARY_GLOBAL,
    "huggingface training/benchmark datasets": COLLECTION_COMMENTARY_GLOBAL,
}

_CASE_COLLECTION_BY_JURISDICTION = {
    "international": COLLECTION_CASE_LAW_GLOBAL,
    "international bodies": COLLECTION_CASE_LAW_GLOBAL,
    "us": COLLECTION_CASE_LAW_US,
    "united states": COLLECTION_CASE_LAW_US,
    "uk": COLLECTION_CASE_LAW_UK,
    "united kingdom": COLLECTION_CASE_LAW_UK,
    "eu": COLLECTION_CASE_LAW_EU,
    "european union": COLLECTION_CASE_LAW_EU,
    "in": COLLECTION_CASE_LAW_IN,
    "india": COLLECTION_CASE_LAW_IN,
    "russia": COLLECTION_CASE_LAW_RU,
    "russian federation": COLLECTION_CASE_LAW_RU,
    "israel": COLLECTION_CASE_LAW_IL,
}

_STATUTE_COLLECTION_BY_JURISDICTION = {
    "us": COLLECTION_STATUTES_US,
    "united states": COLLECTION_STATUTES_US,
    "uk": COLLECTION_STATUTES_UK,
    "united kingdom": COLLECTION_STATUTES_UK,
    "eu": COLLECTION_STATUTES_EU,
    "european union": COLLECTION_STATUTES_EU,
    "in": COLLECTION_STATUTES_IN,
    "india": COLLECTION_STATUTES_IN,
    "russia": COLLECTION_STATUTES_RU,
    "russian federation": COLLECTION_STATUTES_RU,
    "israel": COLLECTION_STATUTES_IL,
}

_RECOMMENDED_COLLECTION_ALIASES = {
    "NATIONAL_US": COLLECTION_NATIONAL_US,
    "NATIONAL_UK": COLLECTION_NATIONAL_UK,
    "NATIONAL_EU": COLLECTION_NATIONAL_EU,
    "NATIONAL_IN": COLLECTION_NATIONAL_IN,
    "RUSSIA": COLLECTION_NATIONAL_RU,
    "NATIONAL_RU": COLLECTION_NATIONAL_RU,
    "ISRAEL": COLLECTION_NATIONAL_IL,
    "NATIONAL_IL": COLLECTION_NATIONAL_IL,
    "CASE_LAW": COLLECTION_CASE_LAW,
    "COMMENTARY": COLLECTION_COMMENTARY,
    "COMMENTARY_GLOBAL": COLLECTION_COMMENTARY_GLOBAL,
}

_JURISDICTION_LANGUAGE: dict[str, str] = {
    "russia": "ru",
    "russian federation": "ru",
    "israel": "he",
    "european union": "mul",
    "international bodies": "mul",
    "huggingface training/benchmark datasets": "mul",
    "india": "en",
    "united states": "en",
    "us": "en",
    "united kingdom": "en",
    "uk": "en",
    "in": "en",
}

_TIER3_PATTERNS = [
    ("bailii", "BAILII prohibits bulk download/external indexing."),
    ("jusmundi", "JusMundi is proprietary and not available for open bulk ingestion."),
    ("justia", "Justia large-scale scraping is risky under site terms."),
    ("n-lex", "N-Lex is a gateway and does not host ingestible content."),
    ("parallel history project", "Parallel History Project is defunct; keep metadata only."),
    ("captcha", "CAPTCHA-only sources are not ingested automatically."),
    ("cloudflare", "Cloudflare/CAPTCHA protected endpoints are not ingested automatically."),
    ("robots.txt disallows", "Robots.txt or terms disallow automated crawling."),
    ("bulk scraping is prohibited", "Source terms prohibit bulk scraping."),
    ("tos prohibit", "Source terms prohibit bulk access."),
]

_PERMISSION_GATES = [
    ("find case law", "UK_FIND_CASE_LAW_LICENSE_CONFIRMED"),
    ("itlos", "ITLOS_PERMISSION_CONFIRMED"),
    ("icrc", "ICRC_PERMISSION_CONFIRMED"),
    ("pca", "PCA_PERMISSION_CONFIRMED"),
    ("hudoc", "HUDOC_PERMISSION_CONFIRMED"),
    ("ecthr", "HUDOC_PERMISSION_CONFIRMED"),
    ("icc legal tools", "ICC_LEGAL_TOOLS_PERMISSION_CONFIRMED"),
    ("legal-tools", "ICC_LEGAL_TOOLS_PERMISSION_CONFIRMED"),
    ("israel supreme court", "ISRAEL_SUPREME_COURT_BULK_CONFIRMED"),
]

_CREDENTIAL_GATES = [
    ("courtlistener", "COURTLISTENER_TOKEN"),
    ("recap", "COURTLISTENER_TOKEN"),
    ("govinfo", "GOVINFO_API_KEY"),
    ("congress.gov", "CONGRESS_API_KEY"),
    ("indian kanoon", "INDIAN_KANOON_API_TOKEN"),
    ("sec edgar", "SEC_USER_AGENT"),
    ("huggingface", "HF_TOKEN"),
    ("hugging face", "HF_TOKEN"),
]

_ENV_VALUES = {
    "COURTLISTENER_TOKEN": COURTLISTENER_TOKEN,
    "GOVINFO_API_KEY": GOVINFO_API_KEY,
    "CONGRESS_API_KEY": CONGRESS_API_KEY,
    "INDIAN_KANOON_API_TOKEN": INDIAN_KANOON_API_TOKEN,
    "SEC_USER_AGENT": SEC_USER_AGENT,
    "HF_TOKEN": HF_TOKEN,
    **REMOTE_LICENSE_GATES,
}


def _slug(value: str, *, limit: int = 96) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:limit].strip("-") or "source"


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def _normalise_recommended(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,;/]", str(value)) if part.strip()]


def resolve_catalog_path(catalog: str | Path | None) -> Path:
    if catalog is None:
        return CASELAWS_DIR
    path = Path(catalog)
    if path.is_absolute() and path.exists():
        return path
    candidates = [
        Path.cwd() / path,
        ROOT_DIR / path,
        OMNILEGAL_DIR / path,
    ]
    if path.parts and path.parts[0].lower() == "omnilegal":
        candidates.append(ROOT_DIR / path)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def extract_urls(value: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"https?://[^\s,;)\]\}]+", value or ""):
        url = match.group(0).rstrip(".,")
        if url not in urls:
            urls.append(url)
    return urls


def load_source_catalog(catalog: str | Path | None = None) -> list[SourceRecord]:
    path = resolve_catalog_path(catalog)
    files = sorted(path.glob("*.json")) if path.is_dir() else [path]
    records: list[SourceRecord] = []
    for file_path in files:
        raw_text = file_path.read_text(encoding="utf-8-sig", errors="replace")
        if not raw_text.strip():
            continue
        data = json.loads(raw_text)
        groups = data if isinstance(data, list) else [data]
        for group_idx, group in enumerate(groups):
            if not isinstance(group, dict):
                continue
            jurisdiction = str(group.get("jurisdiction") or file_path.stem).strip()
            sources = group.get("sources") or []
            for source_idx, source in enumerate(sources):
                if not isinstance(source, dict):
                    continue
                name = str(source.get("name") or f"{jurisdiction} source {source_idx + 1}").strip()
                source_id = _slug(f"{file_path.stem}-{group_idx}-{source_idx}-{jurisdiction}-{name}")
                records.append(SourceRecord(
                    source_id=source_id,
                    catalog_file=file_path.name,
                    group_index=group_idx,
                    source_index=source_idx,
                    jurisdiction=jurisdiction,
                    name=name,
                    url=str(source.get("url") or "").strip(),
                    source_type=str(source.get("type") or "").strip(),
                    coverage=str(source.get("coverage") or "").strip(),
                    access=str(source.get("access") or "").strip(),
                    source_format=str(source.get("format") or "").strip(),
                    license_note=str(source.get("license") or "").strip(),
                    recommended_for=_normalise_recommended(source.get("recommended_for")),
                    raw=source,
                ))
    return records


def _record_legal_type(record: SourceRecord) -> str:
    text = _combined_text(record)
    if any(term in text for term in ["case", "judgment", "judgement", "court", "opinion", "decision", "arbitration"]):
        return "case_law"
    if any(term in text for term in ["statute", "legislation", "code", "regulation", "cfr", "gazette", "official journal", "act "]):
        return "statute"
    if any(term in text for term in ["treaty", "convention", "charter", "protocol"]):
        return "treaty"
    if any(term in text for term in ["commentary", "report", "academic", "textbook", "ilc", "prs india"]):
        return "commentary"
    return "remote_source_content"


def _case_collection_for_jurisdiction(jurisdiction: str) -> str:
    return _CASE_COLLECTION_BY_JURISDICTION.get(jurisdiction.lower(), COLLECTION_CASE_LAW_GLOBAL)


def _statute_collection_for_jurisdiction(jurisdiction: str) -> str:
    return _STATUTE_COLLECTION_BY_JURISDICTION.get(jurisdiction.lower(), COLLECTION_COMMENTARY_GLOBAL)


def _physical_collection_for_record(record: SourceRecord, requested: str | None = None) -> str:
    legal_type = _record_legal_type(record)
    jurisdiction = record.jurisdiction.lower()
    if requested == COLLECTION_COMMENTARY:
        return COLLECTION_COMMENTARY_GLOBAL
    if legal_type == "case_law" or requested == COLLECTION_CASE_LAW:
        return _case_collection_for_jurisdiction(jurisdiction)
    if legal_type in {"statute", "treaty"} and jurisdiction not in {"international", "international bodies"}:
        return _statute_collection_for_jurisdiction(jurisdiction)
    if legal_type == "commentary":
        return COLLECTION_COMMENTARY_GLOBAL
    if requested in COLLECTION_ALIAS_MAP:
        targets = COLLECTION_ALIAS_MAP[requested]
        return targets[0] if targets else requested
    return requested or _COLLECTION_BY_JURISDICTION.get(jurisdiction, COLLECTION_COMMENTARY_GLOBAL)


def collection_for_record(record: SourceRecord) -> str:
    requested_collection: str | None = None
    for item in record.recommended_for:
        normalised = re.sub(r"\s*\(.*?\)", "", item).strip().upper()
        if normalised in _RECOMMENDED_COLLECTION_ALIASES:
            requested_collection = _RECOMMENDED_COLLECTION_ALIASES[normalised]
            if requested_collection == COLLECTION_CASE_LAW:
                return _case_collection_for_jurisdiction(record.jurisdiction)
            break
    return _physical_collection_for_record(record, requested_collection)


def _combined_text(record: SourceRecord) -> str:
    return " ".join([
        record.name,
        record.url,
        record.source_type,
        record.coverage,
        record.access,
        record.source_format,
        record.license_note,
        " ".join(record.recommended_for),
    ]).lower()


def _env_is_true(name: str) -> bool:
    return str(_ENV_VALUES.get(name, "")).lower() in {"1", "true", "yes", "y"}


def _env_present(name: str) -> bool:
    return bool(str(_ENV_VALUES.get(name, "")).strip())


def adapter_for_record(record: SourceRecord) -> str:
    text = _combined_text(record)
    name = record.name.strip().lower()
    if "cd-icj" in text or "corpus of decisions: icj" in text or "10.5281/zenodo.3826444" in text or "zenodo.3826444" in text:
        return "cd_icj"
    if "un digital library" in text or "digitallibrary.un.org" in text:
        return "un_digital_library"
    if "find case law" in text or "caselaw.nationalarchives.gov.uk" in text:
        return "uk_find_caselaw"
    if "ruslawod" in text:
        return "ruslawod"
    if "versa" in text or "cardozo israeli supreme court" in text:
        return "israel_versa"
    if (
        ("supreme court of india" in text or "e-scr" in text or "indian supreme court" in text)
        and ("s3" in text or "aws" in text or "open data" in text)
    ):
        return "india_aws_sc"
    if "huggingface.co/datasets" in text or "hf datasets" in text:
        return "huggingface_stream"
    if "oai-pmh" in text or "oai2d" in text:
        return "oai_pmh"
    if "congress.gov" in text:
        return "congress_api"
    if "sec edgar" in text or "data.sec.gov" in text:
        return "sec_api"
    if "govinfo" in name or "govinfo.gov" in text:
        return "govinfo_api"
    if "federal register" in name or "federalregister.gov" in text:
        return "federal_register_api"
    if "ecfr" in name or "www.ecfr.gov" in text or "gpo bulk data" in name:
        return "ecfr_api"
    if "courtlistener" in text or "recap" in text:
        return "courtlistener_api"
    if "data.gov.il" in text:
        return "ckan_api"
    if "cellar" in text or "eur-lex" in text:
        return "eurlex_cellar"
    if "legislation.gov.uk" in text:
        return "uk_legislation_api"
    if "s3" in text or "aws open data" in text:
        return "open_data_http"
    return "http"


def plan_for_record(record: SourceRecord, *, mode: str = "licensed") -> SourcePlan:
    text = _combined_text(record)
    urls = extract_urls(record.url)
    collection = collection_for_record(record)

    if record.name.strip().lower() == "pacer":
        return SourcePlan(
            source_id=record.source_id,
            collection=collection,
            tier=3,
            adapter="metadata",
            action="metadata_only",
            metadata_only=True,
            allowed_to_fetch=False,
            blocked_reason="Direct PACER bulk harvesting is excluded; prefer RECAP/CourtListener.",
            required_env=[],
            urls=urls,
        )

    for needle, reason in _TIER3_PATTERNS:
        if needle in text:
            return SourcePlan(
                source_id=record.source_id,
                collection=collection,
                tier=3,
                adapter="metadata",
                action="metadata_only",
                metadata_only=True,
                allowed_to_fetch=False,
                blocked_reason=reason,
                urls=urls,
            )

    permission_envs = [env for needle, env in _PERMISSION_GATES if needle in text]
    if permission_envs:
        missing = [env for env in permission_envs if not _env_is_true(env)]
        if mode != "licensed" or missing:
            return SourcePlan(
                source_id=record.source_id,
                collection=collection,
                tier=2,
                adapter="metadata",
                action="permission_required",
                metadata_only=True,
                allowed_to_fetch=False,
                blocked_reason="Permission/license confirmation required before bulk ingestion.",
                required_env=missing or permission_envs,
                urls=urls,
            )

    credential_envs = [env for needle, env in _CREDENTIAL_GATES if needle in text]
    missing_credentials = [env for env in credential_envs if not _env_present(env)]
    if missing_credentials:
        return SourcePlan(
            source_id=record.source_id,
            collection=collection,
            tier=1,
            adapter=adapter_for_record(record),
            action="credential_required",
            metadata_only=True,
            allowed_to_fetch=False,
            blocked_reason="Credential or required API identity is missing.",
            required_env=missing_credentials,
            urls=urls,
        )

    if not urls and adapter_for_record(record) == "http":
        return SourcePlan(
            source_id=record.source_id,
            collection=collection,
            tier=1,
            adapter="metadata",
            action="metadata_only",
            metadata_only=True,
            allowed_to_fetch=False,
            blocked_reason="No usable URL was present in the catalog record.",
            urls=[],
        )

    return SourcePlan(
        source_id=record.source_id,
        collection=collection,
        tier=2 if permission_envs else 1,
        adapter=adapter_for_record(record),
        action="fetch",
        metadata_only=False,
        allowed_to_fetch=True,
        blocked_reason="",
        required_env=permission_envs + credential_envs,
        urls=urls,
    )


def audit_sources(catalog: str | Path | None = None, *, mode: str = "licensed") -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in load_source_catalog(catalog):
        plan = plan_for_record(record, mode=mode)
        rows.append({
            "record": asdict(record),
            "plan": asdict(plan),
        })
    return rows


def _collection_filter_matches(filter_collection: str | None, actual_collection: str) -> bool:
    if filter_collection is None:
        return True
    if filter_collection == actual_collection:
        return True
    return actual_collection in COLLECTION_ALIAS_MAP.get(filter_collection, [])


def write_json_artifact(name: str, payload: dict[str, Any], *, root: Path | None = None) -> Path:
    root = root or REMOTE_SOURCES_DIR / "manifests"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{stamp}_{name}.json"
    path.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    latest = root / f"latest_{name}.json"
    latest.write_text(json.dumps(_jsonable(payload), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def source_audit_summary(catalog: str | Path | None = None, *, mode: str = "licensed") -> dict[str, Any]:
    rows = audit_sources(catalog, mode=mode)
    summary = {
        "total_sources": len(rows),
        "fetchable": sum(1 for row in rows if row["plan"]["allowed_to_fetch"]),
        "metadata_only": sum(1 for row in rows if row["plan"]["metadata_only"]),
        "permission_required": sum(1 for row in rows if row["plan"]["action"] == "permission_required"),
        "credential_required": sum(1 for row in rows if row["plan"]["action"] == "credential_required"),
        "tier3_blocked": sum(1 for row in rows if row["plan"]["tier"] == 3),
        "collections": {},
        "missing_env": sorted({
            env
            for row in rows
            for env in row["plan"].get("required_env", [])
            if not _env_present(env) and not _env_is_true(env)
        }),
    }
    collections: dict[str, int] = {}
    for row in rows:
        collection = row["plan"]["collection"]
        collections[collection] = collections.get(collection, 0) + 1
    summary["collections"] = collections
    return {"summary": summary, "sources": rows}


def source_catalog_chunks_for_collection(
    collection: str | None = None,
    *,
    catalog: str | Path | None = None,
    mode: str = "licensed",
    adapter_filter: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    adapter_filter_set = set(adapter_filter or [])
    for record in load_source_catalog(catalog):
        plan = plan_for_record(record, mode=mode)
        if adapter_filter_set and plan.adapter not in adapter_filter_set:
            continue
        commentary_manifest = (
            collection in {COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL}
            and plan.metadata_only
            and plan.collection not in {COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL}
        )
        if collection is not None and not _collection_filter_matches(collection, plan.collection) and not commentary_manifest:
            continue
        target_collection = COLLECTION_COMMENTARY_GLOBAL if commentary_manifest else plan.collection
        text = "\n".join([
            f"Source catalog entry: {record.name}",
            f"Jurisdiction: {record.jurisdiction}",
            f"URL: {record.url or 'not listed'}",
            f"Type: {record.source_type}",
            f"Coverage: {record.coverage}",
            f"Access: {record.access}",
            f"Format: {record.source_format}",
            f"License: {record.license_note}",
            f"Recommended for: {', '.join(record.recommended_for) or 'not specified'}",
            f"Ingestion action: {plan.action}",
            f"Blocked reason: {plan.blocked_reason or 'none'}",
        ])
        metadata = {
            "source_name": record.name,
            "collection": target_collection,
            "jurisdiction": _jurisdiction_code(record),
            "language": _language_for_record(record),
            "translation_status": "original_only",
            "original_source_url": record.url,
            "doc_type": "source_catalog",
            "legal_type": "source_catalog",
            "year": None,
            "article_number": None,
            "page": None,
            "citation": record.name,
            "parent_id": None,
            "footnote_ids": [],
            "chunk_index": record.source_index,
            "context_prefix": "",
            "license_note": record.license_note,
            "private_public": "public",
            "source_id": record.source_id,
            "source_url": record.url,
            "canonical_doc_id": f"catalog:{record.source_id}",
            "doc_hash": _doc_hash(text),
            "source_fingerprint": _source_fingerprint(record, title=record.name),
            "source_version": "catalog",
            "version_date": "catalog",
            "source_catalog_file": record.catalog_file,
            "source_type": record.source_type,
            "source_access": record.access,
            "source_format": record.source_format,
            "recommended_for": record.recommended_for,
            "remote_tier": plan.tier,
            "remote_adapter": plan.adapter,
            "remote_action": plan.action,
            "intended_collection": plan.collection,
            "bulk_ingest_allowed": plan.allowed_to_fetch,
            "metadata_only": plan.metadata_only,
            "not_legal_authority": True,
            "authority_tier": "official_source_catalog",
            "importance_score": 0.1,
            "importance_reason": "source catalog metadata is not legal authority",
            "importance_signals": ["source_catalog"],
            "blocked_reason": plan.blocked_reason,
            "required_env": plan.required_env,
            "chunk_id": f"catalog:{record.source_id}",
        }
        chunks.append({"text": text, "metadata": metadata})
    return chunks


def _text_from_html(raw: bytes) -> str:
    parser = _TextExtractor()
    parser.feed(raw.decode("utf-8", errors="replace"))
    return parser.text()


def _text_from_json(raw: bytes) -> str:
    data = json.loads(raw.decode("utf-8-sig", errors="replace"))
    return json.dumps(data, ensure_ascii=False, indent=2)


def _text_from_xml(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    # Extract content from known legal XML schemas (Akoma Ntoso, CLML, Formex)
    # before falling back to tag-stripping.
    body_match = re.search(
        r"<(?:[a-zA-Z0-9_:-]*:)?(?:body|mainBody|Body)\b[^>]*>(.*?)</(?:[a-zA-Z0-9_:-]*:)?(?:body|mainBody|Body)>",
        text, re.DOTALL | re.IGNORECASE,
    )
    if body_match:
        text = body_match.group(1)
    # Remove XML declarations, processing instructions, and CDATA wrappers.
    text = re.sub(r"<\?[^>]+\?>", " ", text)
    text = re.sub(r"<!\[CDATA\[(.*?)]]>", r" \1 ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


def _text_from_csv(raw: bytes) -> str:
    try:
        text = raw.decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        rows = ["\t".join(row) for row in reader if any(cell.strip() for cell in row)]
        return "\n".join(rows)
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _text_from_xlsx(raw: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        parts: list[str] = []
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) if c is not None else "" for c in row]
                line = "\t".join(cells).strip()
                if line:
                    parts.append(line)
        return "\n".join(parts)
    except ImportError:
        # openpyxl not installed; treat as binary text (won't parse well but won't crash)
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return raw.decode("utf-8", errors="replace")


def _language_for_record(record: SourceRecord) -> str:
    return _JURISDICTION_LANGUAGE.get(record.jurisdiction.lower(), "en")


def _jurisdiction_code(record: SourceRecord) -> str:
    return {
        "united states": "us",
        "us": "us",
        "united kingdom": "uk",
        "uk": "uk",
        "european union": "eu",
        "eu": "eu",
        "india": "in",
        "in": "in",
        "russia": "ru",
        "russian federation": "ru",
        "israel": "il",
        "international bodies": "international",
        "international": "international",
    }.get(record.jurisdiction.lower(), record.jurisdiction.lower())


_BAD_CONTENT_PATTERNS = [
    "use another email",
    "sign in",
    "login",
    "cookie policy",
    "enable javascript",
    "github.com",
    "skip to main content",
    "api documentation",
    "swagger",
    "openapi",
    "developer guide",
    "devsecops",
]

_LEGAL_SIGNAL_TERMS = {
    "article", "section", "court", "judgment", "judgement", "opinion",
    "statute", "regulation", "treaty", "convention", "constitution",
    "held", "applicant", "respondent", "claimant", "defendant", "tribunal",
    "rights", "obligation", "jurisdiction", "liability", "decree",
}

_LANDMARK_TERMS = {
    "corfu channel",
    "nicaragua",
    "barcelona traction",
    "nottebohm",
    "lotus",
    "chorzow factory",
    "gabčíkovo",
    "gabcikovo",
    "kosovo",
    "oil platforms",
    "military and paramilitary activities",
    "kesavananda bharati",
    "maneka gandhi",
    "golaknath",
    "brown v board",
    "marbury",
}


def _normalise_document_text(text: str) -> str:
    cleaned = html.unescape(text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _doc_hash(text: str) -> str:
    return _stable_hash(_normalise_document_text(text))


def _source_fingerprint(record: SourceRecord, *, title: str, date: str = "", court_or_body: str = "") -> str:
    seed = "|".join([
        title.strip().lower(),
        date.strip().lower(),
        court_or_body.strip().lower(),
        record.jurisdiction.strip().lower(),
    ])
    return _stable_hash(seed)


def _canonical_doc_id(record: SourceRecord, fingerprint: str) -> str:
    return f"remote:{record.source_id}:{fingerprint[:24]}"


def _version_date(text: str) -> str:
    match = re.search(r"\b(18|19|20)\d{2}(?:-[01]\d-[0-3]\d)?\b", text or "")
    if not match:
        return "undated"
    value = match.group(0)
    return value if len(value) == 10 else f"{value}-01-01"


def _quality_rejection_reason(text: str, record: SourceRecord, *, quality_gate: str = "standard") -> str:
    if not text or len(text.strip()) < 40:
        return "too little extracted text"
    lowered = text.lower()
    for pattern in _BAD_CONTENT_PATTERNS:
        if pattern in lowered:
            return f"non-legal/web-boilerplate pattern: {pattern}"
    if quality_gate == "strict":
        tokens = re.findall(r"[a-zA-Z]{3,}", lowered)
        if len(tokens) < 20:
            return "strict gate: too few lexical tokens"
        legal_hits = sum(1 for term in _LEGAL_SIGNAL_TERMS if term in lowered)
        if legal_hits < 2 and _record_legal_type(record) != "commentary":
            return "strict gate: insufficient legal terminology"
    return ""


def _importance_for_record(record: SourceRecord, text: str, legal_type: str) -> tuple[float, str, list[str]]:
    haystack = " ".join([record.name, record.source_type, record.coverage, text[:3000]]).lower()
    signals: list[str] = []
    if any(term in haystack for term in _LANDMARK_TERMS):
        signals.append("landmark_registry_match")
        return 1.0, "landmark or leading authority match", signals
    if legal_type == "treaty" or any(term in haystack for term in ["un charter", "article 2(4)", "article 51", "iccpr"]):
        signals.append("major_treaty_or_primary_text")
        return 1.0, "major treaty or primary legal text", signals
    if any(term in haystack for term in ["supreme court", "constitutional court", "grand chamber", "court of justice", "icj"]):
        signals.append("apex_or_international_court")
        return 0.8, "apex, constitutional, international, or grand chamber authority", signals
    if legal_type == "case_law" and any(term in haystack for term in ["court of appeal", "high court", "appellate"]):
        signals.append("appellate_court")
        return 0.6, "appellate or high court authority", signals
    if legal_type == "case_law":
        signals.append("ordinary_case")
        return 0.3, "ordinary case-law authority", signals
    if legal_type in {"statute", "commentary"}:
        signals.append(legal_type)
        return 0.6, f"{legal_type} authority", signals
    return 0.2, "unclassified remote legal source", ["unclassified"]


def _authority_tier_for_legal_type(legal_type: str) -> str:
    if legal_type == "case_law":
        return "case_law"
    if legal_type in {"statute", "treaty"}:
        return "primary_authority"
    if legal_type == "source_catalog":
        return "official_source_catalog"
    return "reference_dataset"


def parse_downloaded_content(raw: bytes, *, url: str, content_type: str = "") -> str:
    lowered = f"{url} {content_type}".lower()
    url_lower = url.lower()
    if url_lower.endswith(".xlsx") or "spreadsheetml" in lowered:
        return _text_from_xlsx(raw)
    if url_lower.endswith(".csv") or "text/csv" in lowered:
        return _text_from_csv(raw)
    if "json" in lowered or url_lower.endswith(".json") or url_lower.endswith(".jsonl"):
        try:
            return _text_from_json(raw)
        except Exception:
            return raw.decode("utf-8", errors="replace")
    if "html" in lowered or "<html" in raw[:500].decode("utf-8", errors="ignore").lower():
        return _text_from_html(raw)
    if "xml" in lowered or url_lower.endswith((".xml", ".feed", ".akn")):
        return _text_from_xml(raw)
    return raw.decode("utf-8", errors="replace")


def chunk_remote_text(
    record: SourceRecord,
    plan: SourcePlan,
    text: str,
    *,
    url: str,
    checksum: str,
    language: str | None = None,
    download_key: str | None = None,
    raw_path: str | None = None,
    quality_gate: str = "standard",
) -> list[dict[str, Any]]:
    rejection_reason = _quality_rejection_reason(text, record, quality_gate=quality_gate)
    if rejection_reason:
        return []
    language_value = language or _language_for_record(record)
    legal_type = _record_legal_type(record)
    normalized_hash = _doc_hash(text)
    version_date = _version_date(text)
    fingerprint = _source_fingerprint(record, title=record.name, date=version_date, court_or_body=record.source_type)
    canonical_id = _canonical_doc_id(record, fingerprint)
    importance_score, importance_reason, importance_signals = _importance_for_record(record, text, legal_type)
    base_metadata = {
        "source_name": record.name,
        "collection": plan.collection,
        "jurisdiction": _jurisdiction_code(record),
        "language": language_value,
        "translation_status": "original_only",
        "original_source_url": url,
        "doc_type": "remote_source_content",
        "legal_type": legal_type,
        "canonical_doc_id": canonical_id,
        "doc_hash": normalized_hash,
        "source_fingerprint": fingerprint,
        "source_version": version_date,
        "version_date": version_date,
        "source_updated_at": version_date if version_date != "undated" else None,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "court_or_body": record.source_type,
        "authority_tier": _authority_tier_for_legal_type(legal_type),
        "importance_score": importance_score,
        "importance_reason": importance_reason,
        "importance_signals": importance_signals,
        "year": int(version_date[:4]) if re.match(r"^\d{4}", version_date) else None,
        "article_number": None,
        "page": None,
        "citation": record.name,
        "parent_id": record.source_id,
        "footnote_ids": [],
        "context_prefix": "",
        "license_note": record.license_note,
        "private_public": "public",
        "source_id": record.source_id,
        "source_url": url,
        "source_catalog_file": record.catalog_file,
        "source_type": record.source_type,
        "source_access": record.access,
        "source_format": record.source_format,
        "remote_tier": plan.tier,
        "remote_adapter": plan.adapter,
        "download_key": download_key,
        "content_sha256": checksum,
        "raw_path": raw_path,
    }
    structured = structured_legal_chunks(
        text,
        base_metadata=base_metadata,
        doc_type=legal_type,
        source_type=f"{record.source_type} {record.source_format}",
        max_words=700,
    )
    chunks: list[dict[str, Any]] = []
    for idx, chunk in enumerate(structured):
        chunk_text = chunk.get("text", "")
        if not chunk_text.strip():
            continue
        chunk_seed = f"{canonical_id}:{version_date}:{url}:{checksum}:{idx}"
        metadata = dict(chunk.get("metadata") or {})
        metadata.update({
            "source_name": record.name,
            "collection": plan.collection,
            "jurisdiction": _jurisdiction_code(record),
            "language": language_value,
            "translation_status": "original_only",
            "original_source_url": url,
            "doc_type": "remote_source_content",
            "legal_type": legal_type,
            "canonical_doc_id": canonical_id,
            "doc_hash": normalized_hash,
            "source_fingerprint": fingerprint,
            "source_version": version_date,
            "version_date": version_date,
            "source_updated_at": version_date if version_date != "undated" else None,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "court_or_body": record.source_type,
            "authority_tier": _authority_tier_for_legal_type(legal_type),
            "importance_score": importance_score,
            "importance_reason": importance_reason,
            "importance_signals": importance_signals,
            "license_note": record.license_note,
            "private_public": "public",
            "source_id": record.source_id,
            "source_url": url,
            "source_catalog_file": record.catalog_file,
            "source_type": record.source_type,
            "source_access": record.access,
            "source_format": record.source_format,
            "remote_tier": plan.tier,
            "remote_adapter": plan.adapter,
            "download_key": download_key,
            "content_sha256": checksum,
            "raw_path": raw_path,
            "chunk_index": idx,
            "chunk_id": f"remote:{_stable_hash(chunk_seed)[:32]}",
        })
        metadata.setdefault("citation", record.name)
        metadata.setdefault("parent_id", record.source_id)
        metadata.setdefault("footnote_ids", [])
        metadata.setdefault("context_prefix", "")
        metadata.setdefault("year", int(version_date[:4]) if re.match(r"^\d{4}", version_date) else None)
        metadata.setdefault("article_number", None)
        metadata.setdefault("page", None)
        chunks.append({
            "text": chunk_text,
            "metadata": metadata,
        })
    return chunks


def _headers_for(record: SourceRecord) -> dict[str, str]:
    headers = {
        "User-Agent": SEC_USER_AGENT or "OmniLegalResearchAssistant/1.0 (local research ingestion; contact: local)",
        "Accept": "application/json,text/html,application/xml,text/xml,text/plain,*/*",
    }
    text = _combined_text(record)
    if "courtlistener" in text and COURTLISTENER_TOKEN:
        headers["Authorization"] = f"Token {COURTLISTENER_TOKEN}"
    return headers


def _candidate_urls(record: SourceRecord, plan: SourcePlan) -> list[str]:
    text = _combined_text(record)
    urls = list(plan.urls)
    if plan.adapter == "federal_register_api":
        urls.insert(0, "https://www.federalregister.gov/api/v1/articles.json?per_page=5")
    elif plan.adapter == "ecfr_api":
        urls.insert(0, "https://www.ecfr.gov/api/versioner/v1/titles.json")
    elif plan.adapter == "sec_api":
        urls.insert(0, "https://www.sec.gov/files/company_tickers.json")
    elif plan.adapter == "govinfo_api" and GOVINFO_API_KEY:
        urls.insert(0, f"https://api.govinfo.gov/collections?api_key={urllib.parse.quote(GOVINFO_API_KEY)}")
    elif plan.adapter == "congress_api" and CONGRESS_API_KEY:
        urls.insert(0, f"https://api.congress.gov/v3/bill?limit=5&api_key={urllib.parse.quote(CONGRESS_API_KEY)}")
    elif plan.adapter == "courtlistener_api":
        urls.insert(0, "https://www.courtlistener.com/api/rest/v4/search/?q=international%20law&type=o")
    elif plan.adapter == "oai_pmh":
        urls.insert(0, "https://digitallibrary.un.org/oai2d?verb=Identify")
    elif plan.adapter == "ckan_api":
        urls.insert(0, "https://data.gov.il/api/3/action/package_search?rows=5&q=law")
    elif plan.adapter == "uk_legislation_api":
        urls.insert(0, "https://www.legislation.gov.uk/ukpga/data.feed")
    elif plan.adapter == "eurlex_cellar":
        urls.insert(0, "https://op.europa.eu/en/web/cellar/cellar-data")
    if "prsindia" in text and "https://prsindia.org" not in urls:
        urls.insert(0, "https://prsindia.org")
    deduped: list[str] = []
    for url in urls:
        if url and url not in deduped:
            deduped.append(url)
    return deduped


def _extract_hf_dataset_id(record: SourceRecord) -> str | None:
    for url in extract_urls(record.url):
        marker = "huggingface.co/datasets/"
        if marker in url:
            return url.split(marker, 1)[1].strip("/").split("?")[0]
    match = re.search(r"\b([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\b", record.name)
    return match.group(1) if match else None


def _write_raw(root: Path, record: SourceRecord, url: str, raw: bytes, suffix: str) -> Path:
    target_dir = root / "raw" / record.source_id
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(raw).hexdigest()
    path = target_dir / f"{digest[:20]}{suffix}"
    if not path.exists():
        path.write_bytes(raw)
    return path


def _download_key(record: SourceRecord, plan: SourcePlan, *, mode: str, identifier: str) -> str:
    return _stable_hash("|".join([record.source_id, plan.adapter, mode, identifier]))


def _checkpoint_entry_valid(entry: dict[str, Any], *, require_raw: bool = False) -> bool:
    if entry.get("status") != "completed":
        return False
    if require_raw:
        raw_path = entry.get("raw_path")
        return bool(raw_path and Path(str(raw_path)).exists())
    return True


def _rehydrate_http_checkpoint(
    record: SourceRecord,
    plan: SourcePlan,
    entry: dict[str, Any],
    *,
    download_key: str,
) -> list[dict[str, Any]]:
    raw_path = Path(str(entry.get("raw_path") or ""))
    raw = raw_path.read_bytes()
    url = str(entry.get("url") or entry.get("identifier") or record.url)
    content_type = str(entry.get("content_type") or "")
    checksum = str(entry.get("content_sha256") or hashlib.sha256(raw).hexdigest())
    text = parse_downloaded_content(raw, url=url, content_type=content_type)
    return chunk_remote_text(
        record,
        plan,
        text,
        url=url,
        checksum=checksum,
        download_key=download_key,
        raw_path=str(raw_path),
    )


def _download_http(
    record: SourceRecord,
    plan: SourcePlan,
    *,
    root: Path,
    budget: BudgetManager,
    max_bytes: int,
    mode: str,
    checkpoint: dict[str, dict[str, Any]],
    resume: bool,
    ingest: bool,
    quality_gate: str = "standard",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for url in _candidate_urls(record, plan):
        download_key = _download_key(record, plan, mode=mode, identifier=url)
        entry = checkpoint.get(download_key) or {}
        if resume and _checkpoint_entry_valid(entry, require_raw=True):
            made: list[dict[str, Any]] = []
            if ingest:
                try:
                    made = _rehydrate_http_checkpoint(record, plan, entry, download_key=download_key)
                    chunks.extend(made)
                    status = "checkpoint_rehydrated"
                except Exception as exc:
                    events.append({
                        "url": url,
                        "status": "checkpoint_rehydrate_failed",
                        "download_key": download_key,
                        "reason": f"{type(exc).__name__}: {exc}",
                    })
                    status = ""
                if status:
                    events.append({
                        "url": url,
                        "status": status,
                        "download_key": download_key,
                        "raw_path": entry.get("raw_path"),
                        "chunks": len(made),
                    })
                    continue
            else:
                events.append({
                    "url": url,
                    "status": "checkpoint_skipped",
                    "download_key": download_key,
                    "raw_path": entry.get("raw_path"),
                    "chunks": 0,
                })
                continue
        try:
            req = urllib.request.Request(url, headers=_headers_for(record))
            with urllib.request.urlopen(req, timeout=30) as response:
                content_length = int(response.headers.get("Content-Length") or 0)
                if content_length and content_length > max_bytes:
                    events.append({"url": url, "status": "skipped", "reason": f"content length {content_length} exceeds per-item cap"})
                    continue
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    events.append({"url": url, "status": "skipped", "reason": "response exceeded per-item cap"})
                    continue
                if not budget.reserve(len(raw)):
                    events.append({"url": url, "status": "budget_exhausted"})
                    break
                content_type = response.headers.get("Content-Type", "")
            checksum = hashlib.sha256(raw).hexdigest()
            suffix = ".json" if "json" in content_type.lower() else ".xml" if "xml" in content_type.lower() else ".html"
            raw_path = _write_raw(root, record, url, raw, suffix)
            text = parse_downloaded_content(raw, url=url, content_type=content_type)
            made = chunk_remote_text(
                record,
                plan,
                text,
                url=url,
                checksum=checksum,
                download_key=download_key,
                raw_path=str(raw_path),
                quality_gate=quality_gate,
            )
            chunks.extend(made)
            checkpoint[download_key] = {
                "status": "completed",
                "source_id": record.source_id,
                "source_name": record.name,
                "adapter": plan.adapter,
                "mode": mode,
                "identifier": url,
                "url": url,
                "raw_path": str(raw_path),
                "content_type": content_type,
                "content_sha256": checksum,
                "bytes": len(raw),
                "chunks": len(made),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
            _save_checkpoint(root, checkpoint)
            events.append({
                "url": url,
                "status": "downloaded",
                "download_key": download_key,
                "bytes": len(raw),
                "sha256": checksum,
                "raw_path": str(raw_path),
                "chunks": len(made),
            })
        except urllib.error.HTTPError as exc:
            events.append({"url": url, "status": "http_error", "code": exc.code, "reason": str(exc)})
        except Exception as exc:
            events.append({"url": url, "status": "error", "reason": f"{type(exc).__name__}: {exc}"})
        time.sleep(0.25)
    return chunks, events


def _download_huggingface(
    record: SourceRecord,
    plan: SourcePlan,
    *,
    root: Path,
    max_items: int,
    max_bytes: int,
    budget: BudgetManager,
    mode: str,
    checkpoint: dict[str, dict[str, Any]],
    resume: bool,
    quality_gate: str = "standard",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dataset_id = _extract_hf_dataset_id(record)
    if not dataset_id:
        return [], [{"status": "error", "reason": "could not infer Hugging Face dataset id"}]
    dataset_url = f"hf://datasets/{dataset_id}"
    download_key = _download_key(record, plan, mode=mode, identifier=dataset_url)
    entry = checkpoint.get(download_key) or {}
    if resume and _checkpoint_entry_valid(entry):
        return [], [{
            "status": "checkpoint_skipped",
            "dataset": dataset_id,
            "download_key": download_key,
            "chunks": 0,
        }]
    try:
        from datasets import load_dataset
        dataset = load_dataset(dataset_id, split="train", streaming=True, token=HF_TOKEN or None)
        chunks: list[dict[str, Any]] = []
        events: list[dict[str, Any]] = []
        checksums: list[str] = []
        items_seen = 0
        for idx, row in enumerate(dataset):
            if max_items > 0 and idx >= max_items:
                break
            items_seen += 1
            text = json.dumps(row, ensure_ascii=False)
            raw_bytes = text.encode("utf-8", errors="ignore")
            if len(raw_bytes) > max_bytes:
                events.append({
                    "status": "skipped",
                    "dataset": dataset_id,
                    "reason": "item exceeded max-bytes-per-item",
                    "item_index": idx,
                    "bytes": len(raw_bytes),
                })
                continue
            if not budget.reserve(len(raw_bytes)):
                events.append({
                    "status": "budget_exhausted",
                    "dataset": dataset_id,
                    "item_index": idx,
                    "bytes": len(raw_bytes),
                })
                break
            checksum = _stable_hash(text)
            checksums.append(checksum)
            chunks.extend(chunk_remote_text(
                record,
                plan,
                text,
                url=dataset_url,
                checksum=checksum,
                download_key=download_key,
                quality_gate=quality_gate,
            ))
        checkpoint[download_key] = {
            "status": "completed",
            "source_id": record.source_id,
            "source_name": record.name,
            "adapter": plan.adapter,
            "mode": mode,
            "identifier": dataset_url,
            "dataset": dataset_id,
            "content_sha256": _stable_hash("|".join(checksums)),
            "items": items_seen,
            "chunks": len(chunks),
            "max_items": max_items,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        _save_checkpoint(root, checkpoint)
        events.append({
            "status": "streamed",
            "dataset": dataset_id,
            "download_key": download_key,
            "items": items_seen,
            "chunks": len(chunks),
            "max_items": max_items,
        })
        return chunks, events
    except Exception as exc:
        return [], [{"status": "error", "dataset": dataset_id, "reason": f"{type(exc).__name__}: {exc}"}]


def _checkpoint_path(root: Path) -> Path:
    return root / "checkpoints" / "ingest_checkpoint.json"


def _load_checkpoint(root: Path) -> dict[str, dict[str, Any]]:
    path = _checkpoint_path(root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data.get("entries"), dict):
            return {
                str(key): value
                for key, value in data["entries"].items()
                if isinstance(value, dict)
            }
        return {
            f"legacy:{source_id}": {
                "status": "completed",
                "source_id": str(source_id),
                "legacy_source_completed": True,
            }
            for source_id in data.get("processed_source_ids", [])
        }
    except Exception:
        return {}


def _save_checkpoint(root: Path, entries: dict[str, dict[str, Any]]) -> None:
    path = _checkpoint_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 2,
        "entries": entries,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _legacy_source_completed(checkpoint: dict[str, dict[str, Any]], source_id: str) -> bool:
    return any(
        entry.get("legacy_source_completed") and entry.get("source_id") == source_id
        for entry in checkpoint.values()
    )


def _collection_in_target_group(collection: str, target_group: str) -> bool:
    if target_group == "all":
        return True
    collection = str(collection or "").upper()
    if target_group == "case_law":
        return collection.startswith("CASE_LAW")
    if target_group == "statutes":
        return collection.startswith("STATUTES") or collection in {
            COLLECTION_NATIONAL_IN,
            COLLECTION_NATIONAL_US,
            COLLECTION_NATIONAL_UK,
            COLLECTION_NATIONAL_EU,
            COLLECTION_NATIONAL_RU,
            COLLECTION_NATIONAL_IL,
        }
    if target_group == "commentary":
        return collection in {COLLECTION_COMMENTARY, COLLECTION_COMMENTARY_GLOBAL, "SHAW_PRIVATE"}
    return True


def _quality_filter_chunks(chunks: list[dict[str, Any]], *, quality_gate: str) -> tuple[list[dict[str, Any]], int]:
    if quality_gate not in {"strict", "standard"}:
        return chunks, 0
    kept: list[dict[str, Any]] = []
    rejected = 0
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        if meta.get("not_legal_authority") or meta.get("doc_type") == "source_catalog":
            kept.append(chunk)
            continue
        text = chunk.get("text") or ""
        if any(pattern in text.lower() for pattern in _BAD_CONTENT_PATTERNS):
            rejected += 1
            continue
        kept.append(chunk)
    return kept, rejected


def _dedupe_chunks(chunks: list[dict[str, Any]], *, mode: str) -> tuple[list[dict[str, Any]], int, dict[str, list[str]]]:
    if mode != "strict":
        return chunks, 0, {}
    kept: list[dict[str, Any]] = []
    seen_doc_hash: dict[str, dict[str, Any]] = {}
    duplicate_sources: dict[str, list[str]] = {}
    skipped = 0
    source_priority = {
        "govinfo_api": 100,
        "eurlex_cellar": 100,
        "uk_legislation_api": 100,
        "un_digital_library": 95,
        "cd_icj": 95,
        "courtlistener_api": 85,
        "huggingface_stream": 60,
        "http": 20,
    }
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        doc_hash = str(meta.get("doc_hash") or "")
        if not doc_hash or meta.get("doc_type") == "source_catalog":
            kept.append(chunk)
            continue
        previous = seen_doc_hash.get(doc_hash)
        if not previous:
            seen_doc_hash[doc_hash] = chunk
            kept.append(chunk)
            continue
        prev_meta = previous.get("metadata") or {}
        current_priority = source_priority.get(str(meta.get("remote_adapter")), 0)
        previous_priority = source_priority.get(str(prev_meta.get("remote_adapter")), 0)
        duplicate_sources.setdefault(doc_hash, []).append(str(meta.get("source_name") or "unknown"))
        skipped += 1
        if current_priority > previous_priority:
            try:
                kept.remove(previous)
            except ValueError:
                pass
            seen_doc_hash[doc_hash] = chunk
            kept.append(chunk)
    return kept, skipped, duplicate_sources


def run_remote_ingestion(
    *,
    catalog: str | Path | None = None,
    budget_gb: float = 50,
    mode: str = "licensed",
    download: bool = False,
    ingest: bool = False,
    max_items_per_source: int = OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE,
    max_bytes_per_item: int = 10 * 1024 * 1024,
    resume: bool = True,
    reset_checkpoint: bool = False,
    adapter_filter: Iterable[str] | None = None,
    full_source: bool = False,
    target_collection_group: str = "all",
    quality_gate: str = "standard",
    update_mode: str = "overwrite_same_source_version",
    dedupe: str = "off",
    importance_ranking: bool = True,
    lexical_only: bool | None = None,
) -> dict[str, Any]:
    root = REMOTE_SOURCES_DIR
    root.mkdir(parents=True, exist_ok=True)
    if full_source:
        max_items_per_source = 0
    checkpoint_path = _checkpoint_path(root)
    if reset_checkpoint and checkpoint_path.exists():
        checkpoint_path.unlink()
    checkpoint = _load_checkpoint(root) if resume else {}
    checkpoint_entries_before = len(checkpoint)
    records = load_source_catalog(catalog)
    audit = source_audit_summary(catalog, mode=mode)
    budget = BudgetManager(
        root=root,
        budget_bytes=int(budget_gb * 1024 * 1024 * 1024),
        min_free_bytes=int(OMNILEGAL_REMOTE_MIN_FREE_GB * 1024 * 1024 * 1024),
    )
    adapter_filter_set = set(adapter_filter or [])
    all_chunks = source_catalog_chunks_for_collection(
        None,
        catalog=catalog,
        mode=mode,
        adapter_filter=adapter_filter_set or None,
    )
    all_chunks = [
        chunk for chunk in all_chunks
        if _collection_in_target_group((chunk.get("metadata") or {}).get("collection", ""), target_collection_group)
    ]
    remote_chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    skipped_from_checkpoint = 0
    rehydrated_chunk_count = 0

    if download:
        for record in records:
            plan = plan_for_record(record, mode=mode)
            if not _collection_in_target_group(plan.collection, target_collection_group):
                events.append({
                    "source_id": record.source_id,
                    "source_name": record.name,
                    "adapter": plan.adapter,
                    "collection": plan.collection,
                    "status": "target_group_skipped",
                    "reason": f"outside target collection group: {target_collection_group}",
                })
                continue
            if adapter_filter_set and plan.adapter not in adapter_filter_set:
                events.append({
                    "source_id": record.source_id,
                    "source_name": record.name,
                    "adapter": plan.adapter,
                    "collection": plan.collection,
                    "status": "phase_skipped",
                    "reason": "adapter outside requested ingestion phase",
                })
                continue
            if not plan.allowed_to_fetch:
                events.append({"source_id": record.source_id, "source_name": record.name, "status": plan.action, "reason": plan.blocked_reason})
                continue
            if resume and _legacy_source_completed(checkpoint, record.source_id):
                skipped_from_checkpoint += 1
                events.append({
                    "source_id": record.source_id,
                    "source_name": record.name,
                    "status": "checkpoint_skipped_legacy",
                    "reason": "legacy source-level checkpoint entry",
                    "chunks": 0,
                })
                continue
            # Dispatch to registered API-specific adapters first
            from src.services.adapters import has_adapter
            if has_adapter(plan.adapter):
                try:
                    from src.services.adapters import get_adapter_registry
                    adapter_fn = get_adapter_registry()[plan.adapter]
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Running adapter: {plan.adapter} for {record.name}...")
                    chunks, source_events = adapter_fn(
                        record,
                        plan,
                        root=root,
                        budget=budget,
                        max_items=max_items_per_source,
                        max_bytes=max_bytes_per_item,
                        mode=mode,
                        checkpoint=checkpoint,
                        resume=resume,
                        ingest=ingest,
                        quality_gate=quality_gate,
                    )
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Finished {plan.adapter}: {len(chunks)} chunks")
                except Exception as exc:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Error in {plan.adapter}: {exc}")
                    chunks, source_events = [], [{
                        "status": "adapter_error",
                        "adapter": plan.adapter,
                        "reason": f"{type(exc).__name__}: {exc}",
                    }]
            elif plan.adapter == "huggingface_stream":
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Running huggingface_stream for {record.name}...")
                chunks, source_events = _download_huggingface(
                    record,
                    plan,
                    root=root,
                    max_items=max_items_per_source,
                    max_bytes=max_bytes_per_item,
                    budget=budget,
                    mode=mode,
                    checkpoint=checkpoint,
                    resume=resume,
                    quality_gate=quality_gate,
                )
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] Running HTTP download for {record.name}...")
                chunks, source_events = _download_http(
                    record,
                    plan,
                    root=root,
                    budget=budget,
                    max_bytes=max_bytes_per_item,
                    mode=mode,
                    checkpoint=checkpoint,
                    resume=resume,
                    ingest=ingest,
                    quality_gate=quality_gate,
                )
            remote_chunks.extend(chunks)
            skipped_from_checkpoint += sum(
                1 for event in source_events
                if event.get("status") in {"checkpoint_skipped", "checkpoint_rehydrated"}
            )
            rehydrated_chunk_count += sum(
                int(event.get("chunks") or 0) for event in source_events
                if event.get("status") == "checkpoint_rehydrated"
            )
            events.append({
                "source_id": record.source_id,
                "source_name": record.name,
                "adapter": plan.adapter,
                "collection": plan.collection,
                "events": source_events,
                "chunks": len(chunks),
            })

    remote_chunks, quality_rejected_count = _quality_filter_chunks(remote_chunks, quality_gate=quality_gate)
    remote_chunks, dedupe_skipped_count, duplicate_sources = _dedupe_chunks(remote_chunks, mode=dedupe)
    all_chunks.extend(remote_chunks)

    upserted_by_collection: dict[str, int] = {}
    lexical_only = (
        bool(lexical_only)
        if lexical_only is not None
        else os.getenv("OMNILEGAL_REMOTE_LEXICAL_ONLY", "0").lower() in {"1", "true", "yes"}
    )
    if ingest and all_chunks:
        from src.rag.vector_store import upsert_chunks, upsert_chunks_lexical_only
        grouped: dict[str, list[dict[str, Any]]] = {}
        for chunk in all_chunks:
            collection_name = chunk["metadata"]["collection"]
            grouped.setdefault(collection_name, []).append(chunk)
        for collection_name, chunks in grouped.items():
            if lexical_only:
                upserted_by_collection[collection_name] = upsert_chunks_lexical_only(collection_name, chunks, batch_size=64)
            else:
                upserted_by_collection[collection_name] = upsert_chunks(collection_name, chunks, batch_size=16)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "catalog": str(resolve_catalog_path(catalog)),
        "mode": mode,
        "download_requested": download,
        "ingest_requested": ingest,
        "resume": resume,
        "reset_checkpoint": reset_checkpoint,
        "adapter_filter": sorted(adapter_filter_set),
        "full_source": full_source,
        "target_collection_group": target_collection_group,
        "quality_gate": quality_gate,
        "quality_rejected_count": quality_rejected_count,
        "update_mode": update_mode,
        "dedupe": dedupe,
        "dedupe_skipped_count": dedupe_skipped_count,
        "duplicate_sources": duplicate_sources,
        "importance_ranking": importance_ranking,
        "lexical_only": lexical_only,
        "budget_gb": budget_gb,
        "budget_used_bytes": budget.used_bytes,
        "source_count": len(records),
        "catalog_chunks": len(all_chunks) - len(remote_chunks),
        "remote_chunks": len(remote_chunks),
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_entries_before": checkpoint_entries_before,
        "checkpoint_entries_after": len(checkpoint),
        "skipped_from_checkpoint": skipped_from_checkpoint,
        "rehydrated_chunk_count": rehydrated_chunk_count,
        "upserted_by_collection": upserted_by_collection,
        "audit_summary": audit["summary"],
        "events": events,
    }
    manifest_path = write_json_artifact("remote_ingest_manifest", manifest)
    audit_path = write_json_artifact("source_audit", audit)
    manifest["manifest_path"] = str(manifest_path)
    manifest["audit_path"] = str(audit_path)
    return manifest


def remote_status() -> dict[str, Any]:
    manifest_dir = REMOTE_SOURCES_DIR / "manifests"
    latest_manifest = manifest_dir / "latest_remote_ingest_manifest.json"
    latest_audit = manifest_dir / "latest_source_audit.json"
    checkpoint_path = _checkpoint_path(REMOTE_SOURCES_DIR)
    checkpoint = _load_checkpoint(REMOTE_SOURCES_DIR)
    latest_content_manifest: Path | None = None
    for candidate in sorted(manifest_dir.glob("*_remote_ingest_manifest.json"), reverse=True):
        if candidate.name.startswith("latest_"):
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("download_requested") and int(data.get("remote_chunks") or 0) > 0:
            latest_content_manifest = candidate
            break
    status: dict[str, Any] = {
        "root": str(REMOTE_SOURCES_DIR),
        "latest_manifest": str(latest_manifest) if latest_manifest.exists() else None,
        "latest_content_manifest": str(latest_content_manifest) if latest_content_manifest else None,
        "latest_audit": str(latest_audit) if latest_audit.exists() else None,
        "has_manifest": latest_manifest.exists(),
        "has_content_manifest": latest_content_manifest is not None,
        "has_audit": latest_audit.exists(),
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_exists": checkpoint_path.exists(),
        "checkpoint_entries": len(checkpoint),
    }
    if latest_manifest.exists():
        try:
            data = json.loads(latest_manifest.read_text(encoding="utf-8"))
            status["last_remote_chunks"] = data.get("remote_chunks", 0)
            status["last_catalog_chunks"] = data.get("catalog_chunks", 0)
            status["last_upserted_by_collection"] = data.get("upserted_by_collection", {})
        except Exception as exc:
            status["manifest_error"] = f"{type(exc).__name__}: {exc}"
    if latest_content_manifest:
        try:
            data = json.loads(latest_content_manifest.read_text(encoding="utf-8"))
            status["last_content_remote_chunks"] = data.get("remote_chunks", 0)
            status["last_content_catalog_chunks"] = data.get("catalog_chunks", 0)
            status["last_content_budget_used_bytes"] = data.get("budget_used_bytes", 0)
            status["last_content_upserted_by_collection"] = data.get("upserted_by_collection", {})
        except Exception as exc:
            status["content_manifest_error"] = f"{type(exc).__name__}: {exc}"
    if latest_audit.exists():
        try:
            data = json.loads(latest_audit.read_text(encoding="utf-8"))
            status["audit_summary"] = data.get("summary", {})
        except Exception as exc:
            status["audit_error"] = f"{type(exc).__name__}: {exc}"
    return status
