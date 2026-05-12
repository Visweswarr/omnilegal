from __future__ import annotations


def test_citation_graph_missing_kuzu_is_safe(monkeypatch):
    import src.services.citation_graph as citation_graph

    monkeypatch.setattr(citation_graph, "kuzu", None)
    stats = citation_graph.graph_stats()
    assert stats["documents"] == 0
    assert stats["edges"] == 0
    assert stats["available"] is False

    build = citation_graph.build_from_chunks([{"text": "A cites AIR 1950 SC 1.", "metadata": {"chunk_id": "x"}}])
    assert build["documents"] == 0
    assert build["edges"] == 0
    assert build["available"] is False


def test_phase_5_and_legifrance_aliases_are_declared():
    from src.config import INGESTION_PHASES, SOURCE_ALIASES

    assert 5 in INGESTION_PHASES
    assert "multi_legal_pile_hf" in INGESTION_PHASES[5]
    assert SOURCE_ALIASES["legifrance"] == "legifrance_piste"


def test_multi_legal_pile_routes_new_configs():
    from src.services.adapters.multi_legal_pile import _DATASET_ID, _collection_for_row

    assert _DATASET_ID == "joelniklaus/MultiLegalPile_Wikipedia_Filtered"
    assert _collection_for_row("fr_legislation", {"language": "fr", "type": "legislation", "jurisdiction": "fr"}) == (
        "STATUTES_EU",
        "statute",
        "fr",
    )
    assert _collection_for_row("en_caselaw", {"language": "en", "type": "caselaw", "jurisdiction": "us"}) == (
        "CASE_LAW_US",
        "case_law",
        "us",
    )


def test_eurlex_consumer_protection_fallback(monkeypatch):
    import src.services.live_authority_service as live

    monkeypatch.setattr(live, "_http_json", lambda *args, **kwargs: None)
    hits = live._eurlex("consumer protection", 3)
    assert hits
    assert any("consumer" in hit["title"].lower() for hit in hits)


def test_legifrance_catalog_requires_piste_credentials(monkeypatch):
    import src.services.remote_sources as remote_sources

    for env in ["PISTE_API_KEY", "PISTE_CLIENT_ID", "PISTE_CLIENT_SECRET"]:
        monkeypatch.setitem(remote_sources._ENV_VALUES, env, "")

    records = [record for record in remote_sources.load_source_catalog() if "legifrance" in record.name.lower()]
    assert records
    plan = remote_sources.plan_for_record(records[0])
    assert plan.adapter == "legifrance_piste"
    assert plan.action == "credential_required"
    assert set(plan.required_env) == {"PISTE_API_KEY", "PISTE_CLIENT_ID", "PISTE_CLIENT_SECRET"}


def test_legifrance_adapter_missing_credentials_is_clear(monkeypatch, tmp_path):
    from types import SimpleNamespace

    import src.services.adapters.legifrance as legifrance

    for env in ["PISTE_API_KEY", "PISTE_CLIENT_ID", "PISTE_CLIENT_SECRET"]:
        monkeypatch.delenv(env, raising=False)
        monkeypatch.setattr(legifrance, env, "")

    chunks, events = legifrance.fetch(
        SimpleNamespace(),
        SimpleNamespace(),
        root=tmp_path,
        budget=SimpleNamespace(),
    )
    assert chunks == []
    assert events[0]["status"] == "error"
    assert "PISTE_API_KEY" in events[0]["reason"]
