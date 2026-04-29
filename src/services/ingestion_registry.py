"""Formal ingestion source registry for authority-tiered legal data.

Each source has a declared authority tier, license gate, API adapter,
and target Qdrant collection.  The registry enables the retrieval
pipeline to know *which sources are available* and *what they cover*.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Literal

from src.config import (
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    REMOTE_LICENSE_GATES,
)

logger = logging.getLogger(__name__)

AuthorityTier = Literal["primary_binding", "primary_persuasive", "secondary", "background"]
LicenseTier = Literal["open_government", "open_justice", "non_commercial", "commercial", "gated"]


@dataclass
class IngestionSource:
    name: str
    jurisdiction: str  # ISO code
    authority_tier: AuthorityTier
    license_tier: LicenseTier
    adapter: str
    source_id: str = ""
    jurisdiction_iso: str = ""
    legal_domain: list[str] = field(default_factory=list)
    credentials_required: list[str] = field(default_factory=list)
    collection_target: str = ""
    rate_limit: str = ""
    api_url: str = ""
    enabled: bool = True
    license_gate: str = ""  # env var name that must be truthy
    license_policy: str = ""
    freshness: str = ""
    bulk_strategy: str = ""
    runtime_escalation_enabled: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.source_id:
            self.source_id = (
                self.name.lower()
                .replace("&", "and")
                .replace(".", "")
                .replace("/", "_")
                .replace(" ", "_")
            )
        if not self.jurisdiction_iso:
            self.jurisdiction_iso = self.jurisdiction.upper()
        if not self.license_policy:
            self.license_policy = self.license_tier


# ── Pre-populated source definitions ─────────────────────────────────────

SOURCES: list[IngestionSource] = [
    IngestionSource(
        name="CourtListener",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_justice",
        adapter="courtlistener_api",
        source_id="us_courtlistener",
        legal_domain=["case_law", "dockets", "citation_verification"],
        credentials_required=["COURTLISTENER_TOKEN"],
        collection_target=COLLECTION_CASE_LAW_US,
        rate_limit="5000/hr",
        api_url="https://www.courtlistener.com/api/rest/v4/",
        freshness="near_realtime",
        bulk_strategy="deep_pagination_and_bulk_opinion_fetch",
        runtime_escalation_enabled=True,
        notes="US federal and state court opinions via REST API.",
    ),
    IngestionSource(
        name="GovInfo",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="govinfo_api",
        source_id="us_govinfo",
        legal_domain=["statutes", "regulations", "federal_register", "reports"],
        credentials_required=["GOVINFO_API_KEY"],
        collection_target=COLLECTION_STATUTES_US,
        rate_limit="1000/hr",
        api_url="https://api.govinfo.gov/",
        freshness="daily",
        bulk_strategy="collection_packages_and_download_links",
        runtime_escalation_enabled=True,
        notes="US Code, CFR, Federal Register, congressional reports.",
    ),
    IngestionSource(
        name="Congress.gov",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="congress_api",
        source_id="us_congress",
        legal_domain=["bills", "legislative_history", "committee_reports"],
        credentials_required=["CONGRESS_API_KEY"],
        collection_target=COLLECTION_STATUTES_US,
        rate_limit="5000/hr",
        api_url="https://api.congress.gov/v3/",
        freshness="near_realtime",
        bulk_strategy="paginated_endpoint_sync",
        runtime_escalation_enabled=True,
        notes="Bills, amendments, committee reports.",
    ),
    IngestionSource(
        name="Federal Register",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="federal_register_api",
        source_id="us_federal_register",
        legal_domain=["regulations", "notices", "executive_orders"],
        collection_target=COLLECTION_STATUTES_US,
        rate_limit="public",
        api_url="https://www.federalregister.gov/api/v1/",
        freshness="daily",
        bulk_strategy="search_api_by_publication_date",
        runtime_escalation_enabled=True,
        notes="Official daily Federal Register documents and agency rulemaking publications.",
    ),
    IngestionSource(
        name="eCFR",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="ecfr_api",
        source_id="us_ecfr",
        legal_domain=["regulations", "cfr"],
        collection_target=COLLECTION_STATUTES_US,
        rate_limit="public",
        api_url="https://www.ecfr.gov/api/",
        freshness="current",
        bulk_strategy="versioner_api_title_and_part_fetch",
        runtime_escalation_enabled=True,
        notes="Current Code of Federal Regulations text and version metadata.",
    ),
    IngestionSource(
        name="SEC EDGAR",
        jurisdiction="US",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="sec_edgar_api",
        source_id="us_sec_edgar",
        legal_domain=["securities", "corporate_disclosures"],
        credentials_required=["SEC_USER_AGENT"],
        collection_target=COLLECTION_STATUTES_US,
        rate_limit="10/sec recommended",
        api_url="https://www.sec.gov/edgar/sec-api-documentation",
        freshness="near_realtime",
        bulk_strategy="company_submissions_and_archive_fetch",
        runtime_escalation_enabled=False,
        notes="SEC filings and securities-law disclosure corpus; requires compliant User-Agent.",
    ),
    IngestionSource(
        name="UK Find Case Law",
        jurisdiction="GB",
        authority_tier="primary_binding",
        license_tier="gated",
        adapter="uk_find_caselaw",
        source_id="gb_find_case_law",
        legal_domain=["case_law", "tribunals"],
        credentials_required=[],
        collection_target=COLLECTION_CASE_LAW_UK,
        rate_limit="bulk",
        api_url="https://caselaw.nationalarchives.gov.uk/",
        license_gate="UK_FIND_CASE_LAW_LICENSE_CONFIRMED",
        license_policy="Open Justice Licence; computational analysis requires explicit permission.",
        freshness="regular",
        bulk_strategy="licensed_api_or_metadata_only",
        runtime_escalation_enabled=False,
        notes="Requires computational analysis licence from The National Archives. Using metadata-only mode until licensed.",
    ),
    IngestionSource(
        name="Legislation.gov.uk",
        jurisdiction="GB",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="uk_legislation_api",
        source_id="gb_legislation",
        legal_domain=["statutes", "statutory_instruments"],
        credentials_required=[],
        collection_target=COLLECTION_STATUTES_UK,
        rate_limit="unlimited",
        api_url="https://www.legislation.gov.uk/",
        freshness="official_updates",
        bulk_strategy="data_xml_atom_feeds_and_sparql",
        runtime_escalation_enabled=True,
        notes="UK primary and secondary legislation via REST/Atom.",
    ),
    IngestionSource(
        name="BAILII",
        jurisdiction="GB",
        authority_tier="primary_persuasive",
        license_tier="gated",
        adapter="bailii_terms_gated",
        source_id="gb_bailii",
        legal_domain=["case_law"],
        collection_target=COLLECTION_CASE_LAW_UK,
        api_url="https://www.bailii.org/",
        license_policy="Free public access; automated/bulk use must follow BAILII terms.",
        freshness="regular",
        bulk_strategy="disabled_until_terms_confirmed",
        runtime_escalation_enabled=False,
        notes="Terms-gated UK and Ireland case-law fallback; not used for bulk unless permission is confirmed.",
    ),
    IngestionSource(
        name="EUR-Lex CELLAR",
        jurisdiction="EU",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="eurlex_cellar",
        source_id="eu_eurlex_cellar",
        legal_domain=["eu_legislation", "cjeu_case_law", "official_journal"],
        credentials_required=[],
        collection_target=COLLECTION_CASE_LAW_EU,
        rate_limit="bulk",
        api_url="https://publications.europa.eu/webapi/rdf/sparql",
        freshness="official_updates",
        bulk_strategy="sparql_metadata_plus_cellar_rest_content",
        runtime_escalation_enabled=True,
        notes="EU legislation and CJEU case law via SPARQL endpoint.",
    ),
    IngestionSource(
        name="EUR-Lex SOAP",
        jurisdiction="EU",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="eurlex_soap",
        source_id="eu_eurlex_soap",
        legal_domain=["eu_legislation", "cjeu_case_law", "document_search"],
        credentials_required=[],
        collection_target=COLLECTION_STATUTES_EU,
        rate_limit="registered",
        api_url="https://eur-lex.europa.eu/EURLexWebService",
        freshness="official_updates",
        bulk_strategy="search_ids_then_cellar_download",
        runtime_escalation_enabled=False,
        notes="Registered SOAP search service; use CELLAR for bulk document retrieval.",
    ),
    IngestionSource(
        name="HUDOC",
        jurisdiction="EU",
        authority_tier="primary_binding",
        license_tier="open_justice",
        adapter="hudoc_api",
        source_id="coe_hudoc",
        legal_domain=["echr_case_law", "human_rights"],
        collection_target=COLLECTION_CASE_LAW_EU,
        rate_limit="public",
        api_url="https://hudoc.echr.coe.int/",
        freshness="regular",
        bulk_strategy="search_api_with_document_download",
        runtime_escalation_enabled=True,
        notes="European Court of Human Rights case-law database.",
    ),
    IngestionSource(
        name="Indian Kanoon",
        jurisdiction="IN",
        authority_tier="primary_binding",
        license_tier="non_commercial",
        adapter="indian_kanoon_api",
        source_id="in_indian_kanoon",
        legal_domain=["case_law", "tribunals", "statutes"],
        credentials_required=["INDIAN_KANOON_API_TOKEN"],
        collection_target=COLLECTION_CASE_LAW_IN,
        rate_limit="100/day",
        api_url="https://api.indiankanoon.org/",
        freshness="regular",
        bulk_strategy="search_then_document_fragment_fetch",
        runtime_escalation_enabled=True,
        notes="Indian Supreme Court, High Court decisions. Rate-limited API.",
    ),
    IngestionSource(
        name="India Code",
        jurisdiction="IN",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="india_code_api",
        source_id="in_india_code",
        legal_domain=["statutes", "central_acts", "state_acts"],
        credentials_required=[],
        collection_target=COLLECTION_STATUTES_IN,
        rate_limit="unlimited",
        api_url="https://www.indiacode.nic.in/",
        freshness="official_updates",
        bulk_strategy="api_setu_or_portal_document_fetch",
        runtime_escalation_enabled=True,
        notes="India Code portal: BNS, BNSS, BSA, IPC, CrPC, and all central acts.",
    ),
    IngestionSource(
        name="ICJ Case Digests",
        jurisdiction="INTL",
        authority_tier="primary_persuasive",
        license_tier="open_justice",
        adapter="cd_icj",
        source_id="intl_icj",
        legal_domain=["international_case_law", "advisory_opinions"],
        credentials_required=[],
        collection_target=COLLECTION_INTL_TREATIES,
        rate_limit="unlimited",
        api_url="https://www.icj-cij.org/",
        freshness="regular",
        bulk_strategy="case_digest_and_document_fetch",
        runtime_escalation_enabled=True,
        notes="ICJ judgments, advisory opinions, and orders since 1945.",
    ),
    IngestionSource(
        name="UN Digital Library",
        jurisdiction="INTL",
        authority_tier="primary_persuasive",
        license_tier="open_government",
        adapter="un_digital_library",
        source_id="intl_un_digital_library",
        legal_domain=["un_documents", "resolutions", "treaties"],
        credentials_required=[],
        collection_target=COLLECTION_INTL_TREATIES,
        rate_limit="unlimited",
        api_url="https://digitallibrary.un.org/api/",
        freshness="regular",
        bulk_strategy="record_api_and_metadata_search",
        runtime_escalation_enabled=True,
        notes="UNGA and UNSC resolutions, multilateral treaties, treaty series.",
    ),
    IngestionSource(
        name="UN Treaty Collection",
        jurisdiction="INTL",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="un_treaty_collection",
        source_id="intl_un_treaty_collection",
        legal_domain=["treaties", "status", "reservations"],
        collection_target=COLLECTION_INTL_TREATIES,
        api_url="https://treaties.un.org/",
        freshness="official_updates",
        bulk_strategy="treaty_series_and_status_page_fetch",
        runtime_escalation_enabled=True,
        notes="Official UN Treaty Series and multilateral treaty status materials.",
    ),
    IngestionSource(
        name="ICRC IHL Databases",
        jurisdiction="INTL",
        authority_tier="primary_persuasive",
        license_tier="open_justice",
        adapter="icrc_ihl",
        source_id="intl_icrc_ihl",
        legal_domain=["ihl", "geneva_conventions", "customary_ihl"],
        collection_target=COLLECTION_INTL_TREATIES,
        api_url="https://ihl-databases.icrc.org/",
        freshness="regular",
        bulk_strategy="treaty_and_customary_rule_fetch",
        runtime_escalation_enabled=True,
        notes="IHL treaties, commentaries, and customary IHL study materials.",
    ),
    IngestionSource(
        name="WIPO Lex",
        jurisdiction="INTL",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="wipolex",
        source_id="intl_wipolex",
        legal_domain=["intellectual_property", "national_laws", "treaties"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://www.wipo.int/web/wipolex",
        freshness="regular",
        bulk_strategy="document_metadata_and_full_text_links",
        runtime_escalation_enabled=False,
        notes="Open global IP law database covering many jurisdictions.",
    ),
    IngestionSource(
        name="ILO NATLEX/NORMLEX",
        jurisdiction="INTL",
        authority_tier="primary_persuasive",
        license_tier="open_government",
        adapter="ilo_natlex",
        source_id="intl_ilo_natlex",
        legal_domain=["labour", "social_security", "human_rights"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://natlex.ilo.org/",
        freshness="regular",
        bulk_strategy="country_topic_metadata_and_document_links",
        runtime_escalation_enabled=False,
        notes="National labour and social-security legislation plus ILO standards metadata.",
    ),
    IngestionSource(
        name="FAOLEX",
        jurisdiction="INTL",
        authority_tier="primary_persuasive",
        license_tier="open_government",
        adapter="faolex",
        source_id="intl_faolex",
        legal_domain=["food", "agriculture", "environment", "natural_resources"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://www.fao.org/faolex/en/",
        freshness="regular",
        bulk_strategy="open_metadata_and_document_links",
        runtime_escalation_enabled=False,
        notes="Large international database of national laws and policies in FAO domains.",
    ),
    IngestionSource(
        name="OpenNyAI Indian Legal NLP",
        jurisdiction="IN",
        authority_tier="secondary",
        license_tier="open_government",
        adapter="opennyai",
        source_id="in_opennyai",
        legal_domain=["indian_judgment_enrichment", "ner", "rhetorical_roles"],
        credentials_required=["HF_TOKEN"],
        collection_target=COLLECTION_CASE_LAW_IN,
        rate_limit="unlimited",
        api_url="https://huggingface.co/opennyaiorg",
        freshness="model_release",
        bulk_strategy="post_ingestion_enrichment",
        runtime_escalation_enabled=False,
        notes="OpenNyAI HuggingFace datasets for Indian legal NLP. GPU recommended.",
    ),
    IngestionSource(
        name="CanLII",
        jurisdiction="CA",
        authority_tier="primary_persuasive",
        license_tier="gated",
        adapter="canlii_api",
        source_id="ca_canlii",
        legal_domain=["case_law", "legislation"],
        credentials_required=["CANLII_API_KEY"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        rate_limit="api_key",
        api_url="https://api.canlii.org/",
        license_policy="CanLII API terms; official-value limitations apply.",
        freshness="regular",
        bulk_strategy="api_key_search_and_document_fetch",
        runtime_escalation_enabled=False,
        notes="Canadian case law and legislation API where credentials and terms permit.",
    ),
    IngestionSource(
        name="Australian Federal Register of Legislation",
        jurisdiction="AU",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="au_federal_register",
        source_id="au_federal_register",
        legal_domain=["statutes", "legislative_instruments"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://api.prod.legislation.gov.au/v1/",
        freshness="official_updates",
        bulk_strategy="official_api",
        runtime_escalation_enabled=False,
        notes="Authorised whole-of-government source for Australian Commonwealth legislation.",
    ),
    IngestionSource(
        name="New Zealand Legislation API",
        jurisdiction="NZ",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="nz_legislation_api",
        source_id="nz_legislation",
        legal_domain=["statutes", "regulations"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://www.legislation.govt.nz/",
        freshness="official_updates",
        bulk_strategy="official_api_terms",
        runtime_escalation_enabled=False,
        notes="Official New Zealand legislation API subject to published terms.",
    ),
    IngestionSource(
        name="SAFLII",
        jurisdiction="ZA",
        authority_tier="primary_persuasive",
        license_tier="gated",
        adapter="saflii_terms_gated",
        source_id="za_saflii",
        legal_domain=["case_law", "legislation"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://www.saflii.org/",
        license_policy="Free public access; automated/bulk usage must respect SAFLII terms.",
        freshness="regular",
        bulk_strategy="disabled_until_terms_confirmed",
        runtime_escalation_enabled=False,
        notes="Southern African free-access legal materials where terms permit.",
    ),
    IngestionSource(
        name="Legifrance",
        jurisdiction="FR",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="legifrance_piste",
        source_id="fr_legifrance",
        legal_domain=["statutes", "regulations", "case_law"],
        credentials_required=["PISTE_CLIENT_ID", "PISTE_CLIENT_SECRET"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://piste.gouv.fr/",
        freshness="official_updates",
        bulk_strategy="piste_api_or_open_xml_bulk",
        runtime_escalation_enabled=False,
        notes="Official French law API through PISTE / Legifrance open data.",
    ),
    IngestionSource(
        name="BOE",
        jurisdiction="ES",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="boe_open_data",
        source_id="es_boe",
        legal_domain=["gazette", "legislation"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://www.boe.es/",
        freshness="daily",
        bulk_strategy="official_open_data_xml_json",
        runtime_escalation_enabled=False,
        notes="Spain's official gazette and consolidated legislation data.",
    ),
    IngestionSource(
        name="German Open Legal Data",
        jurisdiction="DE",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="de_open_legal_data",
        source_id="de_open_legal_data",
        legal_domain=["statutes", "case_law"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://de.openlegaldata.io/",
        freshness="regular",
        bulk_strategy="api_key_where_required",
        runtime_escalation_enabled=False,
        notes="Open German legal-data access where official or open-data terms permit.",
    ),
    IngestionSource(
        name="Dutch Wetten Overheid",
        jurisdiction="NL",
        authority_tier="primary_binding",
        license_tier="open_government",
        adapter="nl_wetten_overheid",
        source_id="nl_wetten_overheid",
        legal_domain=["statutes", "regulations"],
        collection_target=COLLECTION_COMMENTARY_GLOBAL,
        api_url="https://wetten.overheid.nl/",
        freshness="official_updates",
        bulk_strategy="official_search_and_nlex_routing",
        runtime_escalation_enabled=False,
        notes="Dutch government legislation portal with N-Lex metadata routing.",
    ),
]


_registry_singleton: IngestionRegistry | None = None


def get_registry() -> IngestionRegistry:
    """Return the process-global singleton registry."""
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = IngestionRegistry()
    return _registry_singleton


class IngestionRegistry:
    """Registry of all available ingestion sources."""

    def __init__(self) -> None:
        self._sources: dict[str, IngestionSource] = {}
        for s in SOURCES:
            self._sources[s.name] = s

    def get(self, name: str) -> IngestionSource | None:
        return self._sources.get(name)

    def available(self) -> list[IngestionSource]:
        """Return sources that have all credentials and license gates met."""
        result: list[IngestionSource] = []
        for s in self._sources.values():
            if not s.enabled:
                continue
            if s.license_gate and not REMOTE_LICENSE_GATES.get(s.license_gate):
                continue
            # Check credentials
            missing = [c for c in s.credentials_required if not _credential_available(c)]
            if missing:
                continue
            result.append(s)
        return result

    def by_jurisdiction(self, iso: str) -> list[IngestionSource]:
        return [s for s in self._sources.values() if s.jurisdiction.upper() == iso.upper()]

    def by_tier(self, tier: AuthorityTier) -> list[IngestionSource]:
        return [s for s in self._sources.values() if s.authority_tier == tier]

    def summary(self) -> list[dict[str, Any]]:
        return [
            {
                "name": s.name,
                "jurisdiction": s.jurisdiction,
                "tier": s.authority_tier,
                "enabled": s.enabled,
                "has_credentials": all(
                    _credential_available(c) for c in s.credentials_required
                ) if s.credentials_required else True,
                "license_ok": not s.license_gate or bool(REMOTE_LICENSE_GATES.get(s.license_gate)),
                "runtime_escalation_enabled": s.runtime_escalation_enabled,
                "adapter": s.adapter,
                "source_id": s.source_id,
            }
            for s in self._sources.values()
        ]


_CREDENTIAL_ALIASES = {
    "GOVINFO_API_KEY": ["DATAGOV_API_KEY"],
    "CONGRESS_API_KEY": ["DATAGOV_API_KEY"],
    "INDIAN_KANOON_API_TOKEN": ["INDIAN_KANOON_API_KEY"],
}


def _credential_available(name: str) -> bool:
    import os

    if os.getenv(name):
        return True
    return any(os.getenv(alias) for alias in _CREDENTIAL_ALIASES.get(name, []))


IngestionSourceRegistry = IngestionRegistry
