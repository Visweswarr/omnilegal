"""OmniLegal v4 SOTA + regression backend tests.

Covers the 5 new SOTA endpoints (adversarial, arbitrage, drift, sentinel,
stress) plus regression tests over diff/redteam/doctrine/graph/live/reading
/reports/voice. Hits the public preview URL via REACT_APP_BACKEND_URL.

LLM-heavy endpoints are slow — timeouts are intentionally generous.
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get(
    "REACT_APP_BACKEND_URL",
    "https://rag-source-refined.preview.emergentagent.com",
).rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------------- 1. Adversarial Case Finder ----------------
def test_adversarial_find(client):
    payload = {
        "claim": (
            "My client published a critical article about a sitting politician. "
            "Section 499 IPC defamation should not apply because journalism is "
            "protected under Article 19(1)(a)."
        )
    }
    t0 = time.time()
    r = client.post(f"{API}/adversarial/find", json=payload, timeout=180)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"adversarial elapsed={elapsed:.1f}s keys={list(j.keys())}")
    assert "kill_thesis" in j
    assert j.get("kill_thesis")
    counter = j.get("counter_precedents") or []
    assert len(counter) >= 1, f"expected >=1 counter_precedents, got {len(counter)}"
    candidates = j.get("candidates_retrieved")
    assert candidates is not None and candidates > 0, f"candidates_retrieved={candidates}"
    assert j.get("summary")


# ---------------- 2. Jurisdiction Arbitrage ----------------
def test_arbitrage_scan(client):
    payload = {
        "scenario": (
            "Run a crypto exchange offering stablecoin swaps to retail users in "
            "EU, India, and US."
        )
    }
    t0 = time.time()
    r = client.post(f"{API}/arbitrage/scan", json=payload, timeout=240)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"arbitrage elapsed={elapsed:.1f}s keys={list(j.keys())}")
    matrix = j.get("matrix") or j.get("jurisdictions") or []
    assert len(matrix) >= 3, f"expected >=3 jurisdictions, got {len(matrix)}"
    valid_postures = {"favorable", "neutral", "hostile", "no_data"}
    for entry in matrix:
        verdict = entry.get("verdict") or {}
        posture = (verdict.get("posture") or "").lower()
        assert posture in valid_postures, (
            f"jurisdiction {entry.get('jurisdiction')} posture={posture} "
            f"not in {valid_postures}"
        )


# ---------------- 3. Authority Drift Tracker ----------------
def test_drift_analyze(client):
    payload = {"query": "right to privacy"}
    t0 = time.time()
    r = client.post(f"{API}/drift/analyze", json=payload, timeout=90)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"drift elapsed={elapsed:.1f}s keys={list(j.keys())}")
    valid_verdicts = {"strengthening", "fading", "overruled", "emerging", "stable", "no_data"}
    verdict = (j.get("verdict") or "").lower()
    assert verdict in valid_verdicts, f"verdict={verdict} not in {valid_verdicts}"
    total_hits = j.get("total_hits") or 0
    assert total_hits >= 100, f"total_hits={total_hits} expected >=100"
    buckets = j.get("buckets") or j.get("decade_buckets") or []
    assert len(buckets) == 7, f"expected exactly 7 buckets (1960s-2020s), got {len(buckets)}"


# ---------------- 4. Compliance Sentinel ----------------
def test_sentinel_scan(client):
    payload = {
        "text": (
            "This Privacy Policy applies to data collected by Acme Inc. We may "
            "transfer personal data outside India to US-based servers operated by "
            "AWS. By using the service users grant blanket consent for any purpose. "
            "We use AI-driven automated decision making for hiring decisions. "
            "Section 124A of the IPC may apply to user content. We process facial "
            "recognition data for security."
        )
    }
    t0 = time.time()
    r = client.post(f"{API}/sentinel/scan", json=payload, timeout=180)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"sentinel elapsed={elapsed:.1f}s keys={list(j.keys())}")
    rules_checked = j.get("rules_checked")
    assert rules_checked == 17, f"rules_checked={rules_checked} expected 17"
    confirmed = j.get("confirmed_findings")
    if confirmed is None:
        findings = j.get("findings") or []
        confirmed = sum(1 for f in findings if f.get("confirmed"))
    assert confirmed >= 4, f"confirmed_findings={confirmed} expected >=4"
    risk_score = j.get("risk_score") or 0
    assert risk_score > 0.3, f"risk_score={risk_score} expected >0.3"
    sev = j.get("severity_counts") or {}
    high = sev.get("high") or 0
    assert high >= 3, f"severity_counts.high={high} expected >=3"


def test_sentinel_rules(client):
    r = client.get(f"{API}/sentinel/rules", timeout=20)
    assert r.status_code == 200, r.text
    j = r.json()
    count = j.get("count")
    rules = j.get("rules") or []
    assert count == 17 or len(rules) == 17, f"rules count={count} len(rules)={len(rules)}"
    sample = rules[0] if rules else {}
    required = ["rule_id", "title", "jurisdiction", "effective_date", "severity", "url", "remediation"]
    missing = [k for k in required if k not in sample]
    assert not missing, f"rule missing keys: {missing}; sample={sample}"


# ---------------- 5. Statute Stress Test ----------------
def test_stress_test(client):
    payload = {
        "clause": (
            "Section 66A. Punishment for sending offensive messages through "
            "communication service, etc. Any person who sends, by means of a "
            "computer resource, any information that is grossly offensive or has "
            "menacing character shall be punishable with imprisonment for a term "
            "which may extend to three years and with fine."
        )
    }
    t0 = time.time()
    r = client.post(f"{API}/stress/test", json=payload, timeout=180)
    elapsed = time.time() - t0
    assert r.status_code == 200, r.text
    j = r.json()
    print(f"stress elapsed={elapsed:.1f}s keys={list(j.keys())}")
    hyp_count = j.get("hypothetical_count")
    if hyp_count is None:
        hyp_count = len(j.get("hypotheticals") or [])
    assert hyp_count >= 6, f"hypothetical_count={hyp_count} expected >=6"
    flaws = j.get("drafting_flaws") or []
    if isinstance(flaws, int):
        assert flaws >= 2
    else:
        assert len(flaws) >= 2, f"drafting_flaws len={len(flaws)} expected >=2"
    cov = j.get("coverage_distribution") or {}
    assert isinstance(cov, dict) and len(cov) > 0, f"coverage_distribution={cov}"


# ---------------- Regression: Diff ----------------
def test_diff_compare(client):
    payload = {
        "left": "Section 124A. Whoever brings the Government into hatred shall be punished.",
        "right": "Section 152. Whoever endangers sovereignty shall be punished.",
        "left_label": "IPC 124A",
        "right_label": "BNS 152",
    }
    r = client.post(f"{API}/diff/compare", json=payload, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    chunks = j.get("diff_chunks") or []
    assert len(chunks) >= 1
    reworded = [c for c in chunks if (c.get("kind") or c.get("type") or "").lower() in ("reworded", "modified", "changed")]
    # Either explicit reworded or just non-empty
    assert chunks, "no diff_chunks returned"
    assert "counts" in j
    impact = j.get("impact") or {}
    assert impact.get("summary")
    assert j.get("used_model")


# ---------------- Regression: Redteam ----------------
def test_redteam_analyze(client):
    payload = {"text": "All users explicitly waive any right to a jury trial.", "mode": "contract"}
    r = client.post(f"{API}/redteam/analyze", json=payload, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    weak = j.get("weak_points") or []
    counter = j.get("counter_arguments") or []
    assert len(weak) >= 3, f"weak_points={len(weak)}"
    assert len(counter) == 5, f"counter_arguments={len(counter)} expected 5"


# ---------------- Regression: Doctrine ----------------
def test_doctrine_track(client):
    payload = {"doctrine": "basic structure", "jurisdiction": "India"}
    r = client.post(f"{API}/doctrine/track", json=payload, timeout=180)
    assert r.status_code == 200, r.text
    j = r.json()
    milestones = j.get("milestones") or []
    print(f"doctrine milestones={len(milestones)}")
    assert len(milestones) >= 4, f"milestones={len(milestones)} expected >=4"


# ---------------- Regression: Graph ----------------
def test_graph_build(client):
    payload = {"seed": "sedition India", "max_nodes": 15}
    r = client.post(f"{API}/graph/build", json=payload, timeout=120)
    assert r.status_code == 200, r.text
    j = r.json()
    stats = j.get("stats") or {}
    nc = stats.get("node_count") or 0
    if nc == 0:
        nc = len(j.get("nodes") or [])
    print(f"graph node_count={nc}")
    assert nc >= 5, f"node_count={nc} expected >=5"


# ---------------- Regression: Live search (4 sources) ----------------
def test_live_search_four_sources(client):
    payload = {
        "query": "data protection",
        "sources": ["eurlex", "indian_kanoon", "courtlistener", "hudoc"],
        "max_items": 3,
    }
    r = client.post(f"{API}/live/search", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    total = j.get("total")
    by_source = j.get("by_source") or {}
    if not total:
        total = sum(len(v) if isinstance(v, list) else 0 for v in by_source.values())
    print(f"live total={total} by_source={ {k: (len(v) if isinstance(v,list) else v) for k,v in by_source.items()} }")
    assert total >= 6, f"total={total} expected >=6 across 4 sources"


# ---------------- Regression: Reading annotate ----------------
def test_reading_annotate(client):
    payload = {
        "text": (
            "The doctrine of mens rea requires proof beyond reasonable doubt. "
            "Section 124A of the IPC criminalised sedition."
        )
    }
    r = client.post(f"{API}/reading/annotate", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    stats = j.get("stats") or {}
    tc = stats.get("term_count") or 0
    cc = stats.get("citation_count") or 0
    assert tc >= 2, f"term_count={tc}"
    assert cc >= 1, f"citation_count={cc}"


# ---------------- Regression: Reports save+list ----------------
def test_reports_save_and_list(client):
    payload = {
        "kind": "diff",
        "title": "Test Report",
        "payload": {"summary": "x"},
    }
    r = client.post(f"{API}/reports", json=payload, timeout=30)
    assert r.status_code in (200, 201), r.text
    j = r.json()
    rid = j.get("id") or j.get("report_id")
    token = j.get("share_token")
    assert rid, f"no id in response: {j}"
    assert token, f"no share_token in response: {j}"

    r2 = client.get(f"{API}/reports", timeout=30)
    assert r2.status_code == 200, r2.text
    j2 = r2.json()
    items = j2.get("items") or j2.get("reports") or j2
    if isinstance(items, dict):
        items = items.get("items") or []
    ids = [it.get("id") or it.get("report_id") for it in items]
    assert rid in ids, f"saved id {rid} not in list ids={ids[:10]}..."


# ---------------- Regression: Voice verify_chunk ----------------
def test_voice_verify_chunk(client):
    payload = {"text": "In Roe v. Wade the court held abortion was protected."}
    r = client.post(f"{API}/voice/verify_chunk", json=payload, timeout=60)
    assert r.status_code == 200, r.text
    j = r.json()
    assert "trust_score" in j
    assert "verdict" in j
    claims = j.get("claims") or []
    assert len(claims) >= 1, f"claims len={len(claims)}"
