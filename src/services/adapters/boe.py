"""BOE (Boletín Oficial del Estado) adapter — Spanish official gazette and legislation."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from src.config import COLLECTION_COMMENTARY_GLOBAL, OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP

_SUMARIO_URL = "https://www.boe.es/boe/dias/{year}/{month:02d}/{day:02d}/index.json"
_BUSCAR_URL = "https://www.boe.es/buscar/json/consulta.php"

_SEED_LAWS = [
    ("Constitución Española 1978", "CE", "constitution"),
    ("Código Penal", "LO 10/1995", "criminal_code"),
    ("Código Civil", "Real Decreto de 24 de julio de 1889", "civil_code"),
    ("Ley de Enjuiciamiento Criminal", "LECrim", "criminal_procedure"),
    ("Estatuto de los Trabajadores", "RDL 2/2015", "labour_code"),
]


def _search_boe(query: str, limit: int = 5) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode({
        "campo[0]": "TITLE",
        "dato[0]": query,
        "operador[0]": "and",
        "accion": "buscar",
        "rows": str(limit),
    })
    url = f"{_BUSCAR_URL}?{params}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "OmniLegalResearchAssistant/1.0"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("response") or data.get("results") or []
    if isinstance(results, dict):
        results = results.get("result") or []
    return list(results)[:limit]


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
    """Fetch Spanish legislation seed records from BOE open data."""
    effective_max = max_items if max_items > 0 else min(OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP, 50)
    chunks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen: set[str] = set()

    from src.services.remote_sources import chunk_remote_text

    for title, citation, doc_type in _SEED_LAWS[:effective_max]:
        if title in seen:
            continue
        seen.add(title)
        source_url = f"https://www.boe.es/buscar/act.php?id=BOE-A-{citation.replace(' ', '-')}"
        text = (
            f"BOE — Legislación española\n"
            f"Título: {title}\n"
            f"Referencia: {citation}\n"
            f"Portal oficial: https://www.boe.es/"
        ).strip()
        # Try a live search to enrich the seed
        try:
            results = _search_boe(title, limit=3)
            for r in results:
                item_title = str(r.get("title") or r.get("titulo") or "").strip()
                item_url = str(r.get("url_pdf") or r.get("url") or "").strip()
                if item_title:
                    text += f"\nDocument: {item_title} {item_url}"
        except Exception:
            pass
        checksum = hashlib.sha256(text.encode()).hexdigest()
        doc_chunks = chunk_remote_text(
            record, plan, text,
            url=source_url, checksum=checksum,
            download_key=f"boe:{citation.replace(' ', '_')[:30]}:{checksum[:16]}",
        )
        for chunk in doc_chunks:
            chunk["metadata"].update({
                "doc_type": doc_type,
                "source_name": f"BOE: {title}",
                "jurisdiction": "es",
                "citation": citation,
                "source_url": source_url,
                "license_note": "BOE open data; reutilización sin restricciones",
                "language": "es",
            })
        chunks.extend(doc_chunks)
        time.sleep(0.1)

    events.append({"source": "BOE", "status": "completed", "chunks": len(chunks)})
    return chunks, events
