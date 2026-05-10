"""Tests for Comparative Answer mode (Pillar 19)"""
import pytest
import requests
import os
import time

BASE_URL = "https://jurisdiction-compare-1.preview.emergentagent.com"

class TestCompareJurisdictions:
    """GET /api/compare/jurisdictions"""
    
    def test_jurisdictions_returns_5(self):
        r = requests.get(f"{BASE_URL}/api/compare/jurisdictions")
        assert r.status_code == 200
        data = r.json()
        assert "jurisdictions" in data
        assert len(data["jurisdictions"]) == 5
        print("PASS: 5 jurisdictions returned")

    def test_jurisdiction_keys(self):
        r = requests.get(f"{BASE_URL}/api/compare/jurisdictions")
        data = r.json()
        keys = [j["key"] for j in data["jurisdictions"]]
        assert "india" in keys
        assert "us" in keys
        assert "uk" in keys
        assert "eu" in keys
        assert "international" in keys
        print("PASS: all expected jurisdiction keys present")


class TestCompareAnalyze:
    """POST /api/compare/analyze"""

    def test_analyze_privacy_india_us_uk(self):
        """This test takes 60-90s per the agent notes"""
        payload = {
            "query": "Compare the right to privacy under constitutional law",
            "jurisdictions": ["india", "us", "uk"]
        }
        print("Sending compare/analyze request (may take 60-120s)...")
        r = requests.post(f"{BASE_URL}/api/compare/analyze", json=payload, timeout=180)
        assert r.status_code == 200, f"Got {r.status_code}: {r.text[:300]}"
        data = r.json()
        
        # Check top-level structure
        assert "irac_blocks" in data, "Missing irac_blocks"
        assert "synthesis" in data, "Missing synthesis"
        assert "cross_citations" in data, "Missing cross_citations"
        
        irac_blocks = data["irac_blocks"]
        assert len(irac_blocks) == 3, f"Expected 3 IRAC blocks, got {len(irac_blocks)}"
        print(f"PASS: 3 IRAC blocks returned")
        
        # Check IRAC block structure
        for block in irac_blocks:
            assert "jurisdiction" in block, "IRAC block missing jurisdiction"
            assert "issue" in block or "rule" in block, "IRAC block missing issue/rule"
            print(f"  - Block for {block.get('jurisdiction')}: conclusion={block.get('conclusion','N/A')[:50]}")
        
        # Check synthesis
        synthesis = data["synthesis"]
        assert isinstance(synthesis, dict), "synthesis should be a dict"
        print(f"PASS: synthesis present with keys: {list(synthesis.keys())}")
        
        # Check cross_citations
        cross_cites = data["cross_citations"]
        print(f"PASS: cross_citations count: {len(cross_cites)}")
        
        return data

    def test_analyze_empty_query_validation(self):
        r = requests.post(f"{BASE_URL}/api/compare/analyze", json={"query": "   ", "jurisdictions": ["india"]}, timeout=30)
        assert r.status_code == 422, f"Expected 422, got {r.status_code}"
        print("PASS: empty query returns 422")

    def test_analyze_default_jurisdictions(self):
        """Without specifying jurisdictions, defaults to india, us, uk"""
        payload = {"query": "Compare arbitration standards"}
        r = requests.post(f"{BASE_URL}/api/compare/analyze", json=payload, timeout=180)
        assert r.status_code == 200
        data = r.json()
        assert len(data["irac_blocks"]) == 3
        print("PASS: default jurisdictions return 3 IRAC blocks")

