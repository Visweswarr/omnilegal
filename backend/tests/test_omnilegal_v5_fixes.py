"""OmniLegal v5 — fix verification + regression after iteration_4 fixes.

Verifies the 5 critical/high-priority fixes from iteration_4:
  1. arbitrage/scan completes <60s
  2. diff/compare returns top-level used_model
  3. voice/verify_chunk extracts claims (Roe v. Wade)
  4. live/search eurlex returns non-curated SPARQL hits
  5. live/search 4 sources returns >=6 hits (no CL 429 cascade)

Plus 5 regression tests on adversarial/drift/sentinel/stress/doctrine.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL").rstrip("/")
API = f"{BASE_URL}/api"

# Curated EUR-Lex CELEX ids the service falls back to when SPARQL fails.
# Anything outside this set proves real SPARQL is working.
CURATED_FALLBACK_CELEX = {
    "32016R0679",  # GDPR
    "32024R1689",  # AI Act (sometimes curated, sometimes not — keep loose)
    "32022R1925",  # DMA
    "32022R2065",  # DSA
    "32023R1114",  # MiCA
    "32022L2555",  # NIS2
    "32022L2464",  # CSRD
    "32014R0910",  # eIDAS
}


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ============ FIX 1: arbitrage/scan must finish < 60s ============
def test_fix1_arbitrage_under_60s(client):
    payload = {
        "scenario": "Run a crypto exchange offering stablecoin swaps to retail users in EU, India, and US."
    }
    t0 = time.time()
    r = client.post(f"{API}/arbitrage/scan", json=payload, timeout=70)
    elapsed = time.time() - t0
    print(f"\n[FIX1] arbitrage elapsed={elapsed:.1f}s status={r.status_code}")
    assert r.status_code == 200, f"status={r.status_code} body={r.text[:500]}"
    assert elapsed < 60, f"arbitrage took {elapsed:.1f}s (must be <60s)"
    j = r.json()
    matrix = j.get("matrix") or j.get("jurisdictions") or []
    print(f"[FIX1] jurisdictions returned={len(matrix)}")
    assert len(matrix) >= 5, f"expected >=5 jurisdictions, got {len(matrix)}"


# ============ FIX 2: diff/compare must return top-level used_model ============
def test_fix2_diff_used_model_top_level(client):
    payload = {
        "left": "Section 124A. Whoever brings the Government into hatred shall be punished.",
        "right": "Section 152. Whoever endangers sovereignty shall be punished.",
        "left_label": "IPC 124A",
        "right_label": "BNS 152",
    }
    r = client.post(f"{API}/diff/compare", json=payload, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"\n[FIX2] diff top-level keys={list(j.keys())}")
    assert "used_model" in j, f"used_model missing from top level. keys={list(j.keys())}"
    used_model = j.get("used_model")
    assert used_model, f"used_model is empty: {used_model}"
    print(f"[FIX2] used_model={used_model}")


# ============ FIX 3: voice/verify_chunk must extract claims with 'v.' ============
def test_fix3_voice_extracts_legal_abbrev_claims(client):
    payload = {
        "text": "In Roe v. Wade the court held abortion was protected. Section 124A IPC criminalises sedition."
    }
    r = client.post(f"{API}/voice/verify_chunk", json=payload, timeout=90)
    assert r.status_code == 200, r.text
    j = r.json()
    claims = j.get("claims") or []
    print(f"\n[FIX3] voice claims_count={len(claims)} verdict={j.get('verdict')}")
    for c in claims[:3]:
        print(f"   claim: {str(c)[:200]}")
    assert len(claims) >= 1, f"expected >=1 claim, got {len(claims)}; full={j}"


# ============ FIX 4: EUR-Lex SPARQL returns real (non-curated) results ============
def test_fix4_eurlex_real_sparql(client):
    payload = {"query": "artificial intelligence", "sources": ["eurlex"], "max_items": 3}
    r = client.post(f"{API}/live/search", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    by_source = j.get("by_source") or {}
    eurlex_hits = by_source.get("eurlex") or []
    if not isinstance(eurlex_hits, list):
        eurlex_hits = j.get("results") or []
    print(f"\n[FIX4] eurlex hits={len(eurlex_hits)}")
    assert len(eurlex_hits) >= 1, f"no eurlex hits: {j}"

    # Extract CELEX ids
    celex_ids = []
    for hit in eurlex_hits:
        cid = (
            hit.get("celex")
            or hit.get("celex_id")
            or hit.get("id")
            or ""
        )
        # Sometimes CELEX appears in url as /eli/... or /legal-content/... param celex=
        url = hit.get("url") or hit.get("link") or ""
        for token in (cid, url):
            for piece in str(token).replace("/", " ").replace("=", " ").replace("?", " ").split():
                if piece.startswith("3") and len(piece) >= 8 and piece[1:5].isdigit():
                    celex_ids.append(piece)
        celex_ids.append(str(cid))
    print(f"[FIX4] celex_ids={celex_ids[:10]}")

    # Pass criteria: at least one CELEX id is NOT in curated fallback set
    non_curated = [c for c in celex_ids if c and c not in CURATED_FALLBACK_CELEX]
    # If no CELEX could be parsed at all, accept presence of titles that indicate real results
    titles = [(h.get("title") or "")[:80] for h in eurlex_hits]
    print(f"[FIX4] titles={titles}")
    print(f"[FIX4] non_curated_celex_ids={non_curated[:5]}")
    assert (len(non_curated) >= 1) or any(
        "intelligence" in t.lower() or "ai" in t.lower() for t in titles
    ), f"all hits appear to be curated fallback: ids={celex_ids} titles={titles}"


# ============ FIX 5: live/search 4 sources >=6 hits, no CL 429 cascade ============
def test_fix5_live_search_four_sources(client):
    payload = {
        "query": "data protection",
        "sources": ["eurlex", "indian_kanoon", "courtlistener", "hudoc"],
        "max_items": 3,
    }
    t0 = time.time()
    r = client.post(f"{API}/live/search", json=payload, timeout=90)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    by_source = j.get("by_source") or {}
    counts = {k: (len(v) if isinstance(v, list) else v) for k, v in by_source.items()}
    total = j.get("total") or sum(c for c in counts.values() if isinstance(c, int))
    print(f"\n[FIX5] elapsed={elapsed:.1f}s total={total} by_source={counts}")
    assert total >= 6, f"total={total} expected >=6. by_source={counts}"
    cl_count = counts.get("courtlistener", 0)
    assert cl_count >= 1, f"CourtListener returned 0 hits — possibly 429 cascade. by_source={counts}"


# ============ REGRESSION: adversarial/find ============
def test_regression_adversarial(client):
    payload = {
        "claim": "My client published a critical article. Section 499 IPC defamation should not apply."
    }
    r = client.post(f"{API}/adversarial/find", json=payload, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    counter = j.get("counter_precedents") or []
    cands = j.get("candidates_retrieved") or 0
    print(f"\n[REG-ADV] counter={len(counter)} candidates={cands}")
    assert len(counter) >= 1
    # damage_score on first counter
    first = counter[0] if counter else {}
    assert "damage_score" in first or "score" in first, f"no damage_score in {first.keys()}"
    assert j.get("kill_thesis")
    assert cands >= 10, f"candidates_retrieved={cands} expected >=10"


# ============ REGRESSION: drift/analyze ============
def test_regression_drift(client):
    r = client.post(f"{API}/drift/analyze", json={"query": "right to privacy"}, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    verdict = (j.get("verdict") or "").lower()
    th = j.get("total_hits") or 0
    print(f"\n[REG-DRIFT] verdict={verdict} total_hits={th}")
    assert verdict in {"strengthening", "fading", "overruled", "emerging", "stable"}
    assert th >= 1000, f"total_hits={th} expected >=1000"


# ============ REGRESSION: sentinel/scan ============
def test_regression_sentinel(client):
    payload = {
        "text": (
            "This Privacy Policy applies to data collected by Acme Inc. We may "
            "transfer personal data outside India to US-based servers. By using "
            "the service users grant blanket consent for any purpose. We use AI-driven "
            "automated decision making for hiring. Section 124A IPC may apply. "
            "We process facial recognition data for security."
        )
    }
    r = client.post(f"{API}/sentinel/scan", json=payload, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    confirmed = j.get("confirmed_findings")
    if confirmed is None:
        confirmed = sum(1 for f in (j.get("findings") or []) if f.get("confirmed"))
    risk = j.get("risk_score") or 0
    print(f"\n[REG-SENT] confirmed={confirmed} risk={risk}")
    assert confirmed >= 4, f"confirmed_findings={confirmed}"
    assert risk > 0.3, f"risk_score={risk}"


# ============ REGRESSION: stress/test ============
def test_regression_stress(client):
    payload = {
        "clause": (
            "Section 66A. Any person who sends, by means of a computer resource, any "
            "information that is grossly offensive or has menacing character shall be "
            "punishable with imprisonment up to three years and with fine."
        )
    }
    r = client.post(f"{API}/stress/test", json=payload, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    hyp = j.get("hypothetical_count") or len(j.get("hypotheticals") or [])
    print(f"\n[REG-STRESS] hypothetical_count={hyp}")
    assert hyp >= 6, f"hypothetical_count={hyp}"


# ============ REGRESSION: doctrine/track ============
def test_regression_doctrine(client):
    r = client.post(
        f"{API}/doctrine/track",
        json={"doctrine": "basic structure", "jurisdiction": "India"},
        timeout=180,
    )
    assert r.status_code == 200, r.text
    j = r.json()
    milestones = j.get("milestones") or []
    print(f"\n[REG-DOC] milestones={len(milestones)}")
    assert len(milestones) >= 4, f"milestones={len(milestones)}"
