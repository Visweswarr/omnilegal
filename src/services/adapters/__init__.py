"""Adapter registry: maps adapter labels → fetcher functions.

Each adapter function has the signature:

    def fetch(
        record: SourceRecord,
        plan: SourcePlan,
        *,
        root: Path,
        budget: BudgetManager,
        max_items: int,
        max_bytes: int,
        mode: str,
        checkpoint: dict[str, dict[str, Any]],
        resume: bool,
        ingest: bool,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        '''Returns (chunks, events).'''
"""
from __future__ import annotations

from typing import Any, Callable
from pathlib import Path

# Lazy imports to avoid circular dependency at module level
_ADAPTER_REGISTRY: dict[str, Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]]] | None = None


def _build_registry() -> dict[str, Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]]]:
    from src.services.adapters.courtlistener import fetch as courtlistener_fetch
    from src.services.adapters.congress import fetch as congress_fetch
    from src.services.adapters.cd_icj import fetch as cd_icj_fetch
    from src.services.adapters.govinfo import fetch as govinfo_fetch
    from src.services.adapters.federal_register import fetch as federal_register_fetch
    from src.services.adapters.ecfr import fetch as ecfr_fetch
    from src.services.adapters.sec_edgar import fetch as sec_edgar_fetch
    from src.services.adapters.eurlex_cellar import fetch as eurlex_fetch
    from src.services.adapters.eurlex_soap import fetch as eurlex_soap_fetch
    from src.services.adapters.hudoc import fetch as hudoc_fetch
    from src.services.adapters.un_digital_library import fetch as un_dl_fetch
    from src.services.adapters.un_treaties import fetch as un_treaties_fetch
    from src.services.adapters.icrc_ihl import fetch as icrc_ihl_fetch
    from src.services.adapters.wipolex import fetch as wipolex_fetch
    from src.services.adapters.ilo_natlex import fetch as ilo_natlex_fetch
    from src.services.adapters.faolex import fetch as faolex_fetch
    from src.services.adapters.uk_find_caselaw import fetch as uk_caselaw_fetch
    from src.services.adapters.uk_legislation import fetch as uk_legislation_fetch
    from src.services.adapters.bailii_stub import fetch as bailii_fetch
    from src.services.adapters.india_aws_sc import fetch as india_sc_fetch
    from src.services.adapters.india_code import fetch as india_code_fetch
    from src.services.adapters.indian_kanoon import fetch as indian_kanoon_fetch
    from src.services.adapters.ruslawod import fetch as ruslawod_fetch
    from src.services.adapters.israel_versa import fetch as israel_versa_fetch
    from src.services.adapters.opennyai import fetch as opennyai_fetch
    from src.services.adapters.canlii import fetch as canlii_fetch
    from src.services.adapters.au_legislation import fetch as au_legislation_fetch
    from src.services.adapters.nz_legislation import fetch as nz_legislation_fetch
    from src.services.adapters.saflii_stub import fetch as saflii_fetch
    from src.services.adapters.legifrance import fetch as legifrance_fetch
    from src.services.adapters.boe import fetch as boe_fetch
    from src.services.adapters.de_open_legal import fetch as de_open_legal_fetch
    from src.services.adapters.nl_wetten import fetch as nl_wetten_fetch
    from src.services.adapters.pile_of_law import fetch as pile_of_law_fetch
    from src.services.adapters.multi_legal_pile import fetch as multi_legal_pile_fetch
    from src.services.adapters.openalex import fetch as openalex_fetch
    from src.services.adapters.core_api import fetch as core_api_fetch
    from src.services.adapters.semantic_scholar import fetch as semantic_scholar_fetch
    from src.services.adapters.doaj import fetch as doaj_fetch
    from src.services.adapters.arxiv_legal import fetch as arxiv_legal_fetch
    from src.services.adapters.tn_ogd import fetch as tn_ogd_fetch

    return {
        # United States
        "courtlistener_api": courtlistener_fetch,
        "congress_api": congress_fetch,
        "govinfo_api": govinfo_fetch,
        "federal_register_api": federal_register_fetch,
        "ecfr_api": ecfr_fetch,
        "sec_edgar_api": sec_edgar_fetch,
        # European Union / Europe
        "cd_icj": cd_icj_fetch,
        "eurlex_cellar": eurlex_fetch,
        "eurlex_soap": eurlex_soap_fetch,
        "hudoc_api": hudoc_fetch,
        # International
        "un_digital_library": un_dl_fetch,
        "oai_pmh": un_dl_fetch,  # alias
        "un_treaty_collection": un_treaties_fetch,
        "icrc_ihl": icrc_ihl_fetch,
        "wipolex": wipolex_fetch,
        "ilo_natlex": ilo_natlex_fetch,
        "faolex": faolex_fetch,
        # United Kingdom
        "uk_find_caselaw": uk_caselaw_fetch,
        "uk_legislation_api": uk_legislation_fetch,
        "bailii_terms_gated": bailii_fetch,
        # India
        "indian_kanoon_api": indian_kanoon_fetch,
        "india_code_api": india_code_fetch,
        "india_aws_sc": india_sc_fetch,
        "open_data_http": india_sc_fetch,  # alias for S3-style open data
        # Other jurisdictions
        "ruslawod": ruslawod_fetch,
        "git_or_hf": ruslawod_fetch,  # alias
        "israel_versa": israel_versa_fetch,
        "opennyai": opennyai_fetch,
        "canlii_api": canlii_fetch,
        "au_federal_register": au_legislation_fetch,
        "nz_legislation_api": nz_legislation_fetch,
        "saflii_terms_gated": saflii_fetch,
        "legifrance_piste": legifrance_fetch,
        "boe_open_data": boe_fetch,
        "de_open_legal_data": de_open_legal_fetch,
        "nl_wetten_overheid": nl_wetten_fetch,
        # T1 Open Datasets — Phase 5
        "pile_of_law_hf": pile_of_law_fetch,
        "multi_legal_pile_hf": multi_legal_pile_fetch,
        # Scholarly / Academic
        "openalex_api": openalex_fetch,
        "core_api": core_api_fetch,
        "semantic_scholar_api": semantic_scholar_fetch,
        "doaj_api": doaj_fetch,
        "arxiv_legal_api": arxiv_legal_fetch,
        # India — Tamil Nadu OGD
        "tn_ogd_ckan": tn_ogd_fetch,
    }


def get_adapter_registry() -> dict[str, Callable[..., tuple[list[dict[str, Any]], list[dict[str, Any]]]]]:
    global _ADAPTER_REGISTRY
    if _ADAPTER_REGISTRY is None:
        _ADAPTER_REGISTRY = _build_registry()
    return _ADAPTER_REGISTRY


def has_adapter(label: str) -> bool:
    """Check if an adapter exists without triggering full import."""
    known = {
        # US
        "courtlistener_api", "congress_api", "govinfo_api",
        "federal_register_api", "ecfr_api", "sec_edgar_api",
        # EU / Europe
        "cd_icj", "eurlex_cellar", "eurlex_soap", "hudoc_api",
        # International
        "un_digital_library", "oai_pmh", "un_treaty_collection",
        "icrc_ihl", "wipolex", "ilo_natlex", "faolex",
        # UK
        "uk_find_caselaw", "uk_legislation_api", "bailii_terms_gated",
        # India
        "indian_kanoon_api", "india_code_api", "india_aws_sc", "open_data_http",
        # Other
        "ruslawod", "git_or_hf", "israel_versa", "opennyai",
        "canlii_api", "au_federal_register", "nz_legislation_api",
        "saflii_terms_gated", "legifrance_piste", "boe_open_data",
        "de_open_legal_data", "nl_wetten_overheid",
        # T1 Open Datasets (Phase 5)
        "pile_of_law_hf", "multi_legal_pile_hf",
        # Scholarly / Academic
        "openalex_api", "core_api", "semantic_scholar_api",
        "doaj_api", "arxiv_legal_api",
        # India — Tamil Nadu OGD
        "tn_ogd_ckan",
    }
    return label in known
