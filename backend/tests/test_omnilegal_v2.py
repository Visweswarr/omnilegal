"""OmniLegal v3 backend API tests against the public preview URL.

Architecture: Chainlit on :3000 hosts FastAPI; backend on :8001 is a thin
httpx proxy to it. The OmniLegal API router is mounted on Chainlit's app so
the embedded Qdrant client is shared in-process (no subprocess / no lock
contention).
"""
from __future__ import annotations

import os
import requests
import pytest

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://rag-source-refined.preview.emergentagent.com",
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


# --- /api/ingestion/status ----------------------------------------------
def test_ingestion_status_corpus_size(client):
    r = client.get(f"{BASE_URL}/api/ingestion/status", timeout=90)
    assert r.status_code == 200
    data = r.json()
    assert data["total_points"] >= 9000, f"got total_points={data['total_points']}"
    cols = {c["name"]: c["points"] for c in data.get("collections", [])}
    assert cols.get("STATUTES_IN", 0) > 3000
    assert cols.get("COMMENTARY_GLOBAL", 0) > 3000
    for k in ["STATUTES_IL", "STATUTES_RU", "STATUTES_US",
              "INTL_TREATIES", "NATIONAL_IN", "SHAW_PRIVATE"]:
        assert cols.get(k, 0) > 0, f"{k} expected >0, got {cols.get(k, 0)}"


# --- /api/debug/retrieve ------------------------------------------------
def test_debug_retrieve_indian_statutes(client):
    r = client.get(
        f"{BASE_URL}/api/debug/retrieve",
        params={"query": "arbitration enforcement",
                "collections": "STATUTES_IN", "k": 4},
        timeout=90,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["passage_count"] >= 1
    src = (data["passages"][0].get("source_name") or "").lower()
    assert "arbitration" in src


# --- /api/conflict/analyze ----------------------------------------------
def test_conflict_india_us_death_penalty(client):
    r = requests.post(
        f"{BASE_URL}/api/conflict/analyze",
        json={"query": "death penalty for foreign nationals charged with drug trafficking",
              "domestic_jurisdictions": ["india", "us"]},
        timeout=240,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["verdict"] in {
        "alignment", "qualified_alignment", "conflict", "neutral_or_unknown",
    }
    assert isinstance(data.get("label_counts"), dict)
    assert len(data["per_jurisdiction"]) == 2
    for entry in data["per_jurisdiction"]:
        assert len(entry.get("domestic_passages", [])) >= 1, \
            f"{entry.get('jurisdiction')} had no domestic passages"
    # used_model should reference claude-sonnet-4-5
    used_model = (data.get("used_model") or "").lower()
    assert "anthropic/claude-sonnet-4-5" in used_model or "claude-sonnet-4-5" in used_model
    # at least one entry should have a non-neutral label
    labels = [e.get("label") for e in data["per_jurisdiction"]]
    assert any(lbl and lbl != "neutral" for lbl in labels), f"all labels neutral: {labels}"


# --- /api/irac/analyze --------------------------------------------------
def test_irac_anticipatory_self_defense(client):
    r = requests.post(
        f"{BASE_URL}/api/irac/analyze",
        json={"query": "is anticipatory self-defense lawful under international law?",
              "domestic_jurisdictions": ["us", "uk"]},
        timeout=240,
    )
    assert r.status_code == 200
    data = r.json()
    intl = data.get("international_irac", {})
    assert (intl.get("rule") or "").strip(), "international_irac.rule empty"
    assert (intl.get("conclusion") or "").strip(), "international_irac.conclusion empty"
    assert len(data.get("domestic_iracs", [])) == 2
    syn = data.get("synthesis", {})
    assert "agreements" in syn and "disagreements" in syn
    table = data.get("comparison_table_markdown", "")
    assert table.lstrip().startswith("| Jurisdiction"), f"table head: {table[:80]!r}"
