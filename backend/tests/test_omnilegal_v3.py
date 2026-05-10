"""OmniLegal v3 backend integration tests.

Hits the public preview URL via REACT_APP_BACKEND_URL.
Covers: health, overview, forensics, atlas, live, council, research, advocacy, CORS.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://rag-source-refined.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- Health & Overview ----------------
def test_sidecar_health(client):
    r = client.get(f"{API}/__sidecar_health", timeout=15)
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health(client):
    r = client.get(f"{API}/health", timeout=15)
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "ok"
    assert j.get("emergent_llm_configured") or j.get("gemini_configured") or j.get("groq_configured")


def test_overview(client):
    r = client.get(f"{API}/overview", timeout=20)
    assert r.status_code == 200
    j = r.json()
    assert j["total_chunks"] > 0
    assert j["collection_count"] > 0
    assert len(j["live_sources"]) == 6
    assert len(j["council_models"]) == 3


def test_cors_header(client):
    r = client.get(f"{API}/health", timeout=15, headers={"Origin": "https://example.com"})
    assert r.status_code == 200
    # Either ACAO present or wildcard
    acao = r.headers.get("access-control-allow-origin") or r.headers.get("Access-Control-Allow-Origin")
    assert acao is not None


# ---------------- Forensics ----------------
def test_forensics_verify(client):
    payload = {
        "text": (
            "In Maneja v. Maneja, 50 U.S. 75 (1957), the court held that sedition under "
            "Section 124A IPC requires intent. Arbitration proceedings under the Arbitration "
            "and Conciliation Act, 1996 are governed by Section 11."
        )
    }
    r = client.post(f"{API}/forensics/verify", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "annotated_segments" in j or "segments" in j
    assert "claims" in j
    assert "summary" in j
    assert "overall_grade" in j
    assert j["overall_grade"] is not None


# ---------------- Atlas ----------------
def test_atlas_analyze(client):
    payload = {"topic": "arbitration", "include_ai_inferred": False}
    t0 = time.time()
    r = client.post(f"{API}/atlas/analyze", json=payload, timeout=90)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 90
    j = r.json()
    countries = j.get("countries") or j.get("entries") or j.get("results") or []
    assert len(countries) >= 6, f"expected >=6 countries, got {len(countries)}"
    # at least one with verdict legal/restricted/illegal
    valid = {"legal", "restricted", "illegal", "permitted", "prohibited"}
    found = any((c.get("verdict") or "").lower() in valid for c in countries)
    assert found, f"No grounded verdict found in countries: {[c.get('verdict') for c in countries]}"


# ---------------- Live search ----------------
def test_live_search(client):
    payload = {"query": "freedom of expression"}
    t0 = time.time()
    r = client.post(f"{API}/live/search", json=payload, timeout=30)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 25
    j = r.json()
    total = j.get("total") or 0
    by_source = j.get("by_source") or {}
    if total < 5:
        # tally manually
        total = sum(len(v) if isinstance(v, list) else 0 for v in by_source.values())
    assert total >= 5, f"expected >=5 hits, got {total}"


# ---------------- Council ----------------
def test_council_debate(client):
    payload = {"query": "Is anticipatory self-defense lawful under the UN Charter?"}
    t0 = time.time()
    r = client.post(f"{API}/council/debate", json=payload, timeout=120)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 100
    j = r.json()
    answers = j.get("answers") or []
    assert len(answers) == 3, f"expected 3 answers, got {len(answers)}"
    assert "judge" in j
    judge = j["judge"]
    assert "verdict" in judge or "agreements" in judge or "disagreements" in judge
    assert "passages" in j


# ---------------- Research ----------------
def test_research_ask(client):
    payload = {"query": "What are the key principles of arbitration in India?", "persona": "researcher"}
    t0 = time.time()
    r = client.post(f"{API}/research/ask", json=payload, timeout=60)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 45
    j = r.json()
    assert j.get("answer")
    assert "citations" in j
    assert "passages" in j
    assert j.get("used_model")


# ---------------- Advocacy ----------------
def test_advocacy_generate(client):
    payload = {
        "country_key": "india",
        "country_name": "India",
        "topic": "detention without trial",
        "position": "AGAINST",
        "include_conflict": False,
    }
    t0 = time.time()
    r = client.post(f"{API}/advocacy/generate", json=payload, timeout=180)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    assert elapsed < 150
    j = r.json()
    packet = j.get("packet") or j
    assert packet.get("position_paper")
    assert packet.get("opening_speech")
    assert packet.get("rebuttal_cards")
    assert packet.get("leverage_cards")
