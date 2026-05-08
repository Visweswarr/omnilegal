"""OmniLegal v2 backend API smoke tests.

These tests hit the public preview URL to validate the FastAPI sidecar that
fronts the Chainlit-powered RAG console.

Note: /api/conflict/analyze and /api/ingestion/status spawn subprocesses
(`scripts/run_conflict.py`, `scripts/print_status.py`) that try to open the
embedded Qdrant store at /app/data/qdrant_embedded. When Chainlit is running
(production state), Chainlit holds the embedded Qdrant lock, and the
subprocess falls back to an empty SQLite store, so corpus-dependent fields
will be 0 / empty even though the endpoints themselves return 200.
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://b76f2c97-40e5-4b67-bcd2-eac077eac1a3.preview.emergentagent.com",
).rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- /api/health ---------------------------------------------------------
def test_health_ok(client):
    r = client.get(f"{BASE_URL}/api/health", timeout=30)
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["emergent_llm_configured"] is True
    assert data["gemini_configured"] is True
    assert data["groq_configured"] is True


# --- /api/ingestion/status ----------------------------------------------
def test_ingestion_status_corpus_size(client):
    """Expect total_points > 7000 across the ingested corpus."""
    r = client.get(f"{BASE_URL}/api/ingestion/status", timeout=90)
    assert r.status_code == 200
    data = r.json()
    assert "total_points" in data
    # Per review request: total_points > 7000
    assert data["total_points"] > 7000, (
        f"Subprocess can't access Qdrant while Chainlit is running. "
        f"Got total_points={data['total_points']}"
    )
    cols = {c["name"]: c["points"] for c in data.get("collections", [])}
    for k in ["STATUTES_IN", "COMMENTARY_GLOBAL", "STATUTES_IL",
              "STATUTES_RU", "STATUTES_US",
              "INTL_TREATIES", "NATIONAL_IN", "SHAW_PRIVATE"]:
        assert cols.get(k, 0) > 0, f"{k} expected >0 points, got {cols.get(k, 0)}"


# --- /api/debug/retrieve ------------------------------------------------
def test_debug_retrieve_indian_statutes(client):
    r = client.get(
        f"{BASE_URL}/api/debug/retrieve",
        params={"query": "arbitration enforcement",
                "collections": "STATUTES_IN", "k": 4},
        timeout=120,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["passage_count"] >= 1, (
        "STATUTES_IN retrieved 0 passages — Qdrant subprocess lock contention"
    )


# --- /api/conflict/analyze ----------------------------------------------
def test_conflict_israel_us(client):
    r = client.post(
        f"{BASE_URL}/api/conflict/analyze",
        json={"query": "occupation Palestinian territories settlement legality",
              "domestic_jurisdictions": ["israel", "us"]},
        timeout=240,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["verdict"] in {
        "alignment", "qualified_alignment", "conflict", "neutral_or_unknown",
    }
    assert len(data["per_jurisdiction"]) >= 2
    # At least one entry should have domestic_passages > 0
    has_passages = any(
        len(p.get("domestic_passages", [])) > 0 for p in data["per_jurisdiction"]
    )
    assert has_passages, (
        "All per_jurisdiction entries had domestic_passages=0 — "
        "subprocess can't access the corpus while Chainlit holds Qdrant lock"
    )


def test_conflict_india_us_structure(client):
    r = client.post(
        f"{BASE_URL}/api/conflict/analyze",
        json={"query": "death penalty for foreign nationals",
              "domestic_jurisdictions": ["india", "us"]},
        timeout=240,
    )
    assert r.status_code == 200
    data = r.json()
    assert len(data["per_jurisdiction"]) >= 2
    assert "verdict" in data
