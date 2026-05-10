"""Tests for Pillar 19 Comparative IRAC — heat map and query expansion features."""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

ERGA_OMNES_QUERY = "Compare how erga omnes is recognized and enforced"
ERGA_OMNES_JURISDICTIONS = ["india", "us", "uk", "international"]


@pytest.fixture(scope="module")
def compare_response():
    """Call compare/analyze once for all tests in this module. Timeout 200s."""
    resp = requests.post(
        f"{BASE_URL}/api/compare/analyze",
        json={"query": ERGA_OMNES_QUERY, "jurisdictions": ERGA_OMNES_JURISDICTIONS},
        timeout=200,
    )
    assert resp.status_code == 200, f"compare/analyze returned {resp.status_code}: {resp.text[:500]}"
    return resp.json()


# ── Feature 1: heat_map field present ─────────────────────────────────────

def test_heat_map_field_present(compare_response):
    """heat_map key must be in response."""
    assert "heat_map" in compare_response, "Missing 'heat_map' key in response"


def test_heat_map_has_dimensions(compare_response):
    hm = compare_response["heat_map"]
    assert "dimensions" in hm, "heat_map missing 'dimensions'"
    assert isinstance(hm["dimensions"], list) and len(hm["dimensions"]) > 0, "heat_map.dimensions is empty"


def test_heat_map_has_cells(compare_response):
    hm = compare_response["heat_map"]
    assert "cells" in hm, "heat_map missing 'cells'"
    assert isinstance(hm["cells"], dict) and len(hm["cells"]) > 0, "heat_map.cells is empty"


def test_heat_map_has_summary_verdict(compare_response):
    hm = compare_response["heat_map"]
    assert "summary_verdict" in hm, "heat_map missing 'summary_verdict'"
    assert isinstance(hm["summary_verdict"], str) and len(hm["summary_verdict"]) > 0


# ── Feature 2: cell values are valid ──────────────────────────────────────

VALID_VALUES = {"full", "partial", "none", "indeterminate"}


def test_heat_map_cell_values_valid(compare_response):
    hm = compare_response["heat_map"]
    dims = hm.get("dimensions", [])
    cells = hm.get("cells", {})
    errors = []
    for jur, dim_map in cells.items():
        for dim in dims:
            val = dim_map.get(dim, "").lower()
            if val not in VALID_VALUES:
                errors.append(f"{jur}.{dim} = '{val}' (expected full|partial|none|indeterminate)")
    assert not errors, f"Invalid cell values: {errors}"


def test_heat_map_cells_cover_all_dimensions(compare_response):
    hm = compare_response["heat_map"]
    dims = hm.get("dimensions", [])
    cells = hm.get("cells", {})
    missing = []
    for jur, dim_map in cells.items():
        for dim in dims:
            if dim not in dim_map:
                missing.append(f"{jur} missing dim '{dim}'")
    assert not missing, f"Missing cells: {missing}"


# ── Feature 3: query expansion — global corpus passages appear ─────────────

def test_irac_blocks_present(compare_response):
    blocks = compare_response.get("irac_blocks", [])
    assert len(blocks) == len(ERGA_OMNES_JURISDICTIONS), (
        f"Expected {len(ERGA_OMNES_JURISDICTIONS)} IRAC blocks, got {len(blocks)}"
    )


def test_irac_key_authorities_populated(compare_response):
    """At least one IRAC block must have non-empty key_authorities."""
    blocks = compare_response.get("irac_blocks", [])
    any_authorities = any(len(b.get("key_authorities", [])) > 0 for b in blocks)
    assert any_authorities, "No IRAC block has key_authorities populated"


def test_irac_no_indeterminate_from_empty_passages(compare_response):
    """With query expansion, erga omnes blocks should NOT be bare 'indeterminate'."""
    blocks = compare_response.get("irac_blocks", [])
    for b in blocks:
        concl = (b.get("conclusion") or "").lower()
        assert concl != "indeterminate", (
            f"Jurisdiction {b.get('jurisdiction')} returned bare 'indeterminate' — "
            "query expansion may not have worked"
        )


# ── Feature 4: IRAC fields correct ────────────────────────────────────────

def test_irac_blocks_have_issue_rule_application(compare_response):
    blocks = compare_response.get("irac_blocks", [])
    for b in blocks:
        jur = b.get("jurisdiction", "?")
        assert b.get("issue"), f"{jur}: missing 'issue'"
        assert b.get("rule"),  f"{jur}: missing 'rule'"
        assert b.get("application"), f"{jur}: missing 'application'"


# ── Feature 5: synthesis ───────────────────────────────────────────────────

def test_synthesis_present(compare_response):
    synth = compare_response.get("synthesis", {})
    assert synth, "synthesis object missing or empty"


def test_synthesis_agreements_or_disagreements(compare_response):
    synth = compare_response.get("synthesis", {})
    has_agreements = len(synth.get("agreements", [])) > 0
    has_disagreements = len(synth.get("disagreements", [])) > 0
    assert has_agreements or has_disagreements, "synthesis has neither agreements nor disagreements"


# ── Feature 6: compare/jurisdictions endpoint ─────────────────────────────

def test_compare_jurisdictions_endpoint():
    resp = requests.get(f"{BASE_URL}/api/compare/jurisdictions", timeout=10)
    assert resp.status_code == 200
    data = resp.json()
    assert "jurisdictions" in data
    assert len(data["jurisdictions"]) > 0
