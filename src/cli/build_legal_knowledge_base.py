"""Build and ingest OmniLegal's jurisdiction foundation corpus.

This command populates the local ``data/corpus`` slots with curated foundational
legal records, ingests the shipped primary PDFs, streams the full local SCOTUS
JSONL into the US case-law collection, and optionally upserts the remote source
catalog rows. It is intentionally source-slot based so the Chainlit app, tests,
and future ingestion runs all use the same corpus layout.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.env import load_environment

load_environment()

from src.config import (
    ALL_COLLECTIONS,
    CASE_LAW_JSONL,
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_IL,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_US,
    COLLECTION_COMMENTARY_GLOBAL,
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_US,
    COLLECTION_REFERENCE_DATASET_EU,
    COLLECTION_REFERENCE_DATASET_GLOBAL,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_IL,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_US,
    CORPUS_DIR,
    DATA_DIR,
)
from src.data.corpus_catalog import iter_reference_dataset_records
from src.rag.ingestion import _chunk_case, _chunk_plain_text, _ingest_directory_slot, ingest_collection
from src.rag.vector_store import (
    collection_point_count,
    create_collection,
    upsert_chunks,
    upsert_chunks_lexical_only,
)
from src.services.remote_sources import run_remote_ingestion

_FOUNDATION_FILENAME = "omnilegal_foundation.jsonl"
_REFERENCE_DATASET_EU_SOURCES = {
    "multi_eurlex_readme",
    "multi_eurlex_eurovoc_concepts",
    "multi_eurlex_eurovoc_descriptors",
}
_TARGETED_REMOTE_ADAPTERS = [
    "govinfo_api",
    "courtlistener_api",
    "uk_find_caselaw",
    "india_aws_sc",
    "ruslawod",
    "israel_versa",
    "un_digital_library",
]
_TARGETED_REMOTE_MAX_ITEMS_PER_SOURCE = 6


def _record(
    *,
    title: str,
    citation: str,
    jurisdiction: str,
    doc_type: str,
    text: str,
    source_url: str = "",
    year: int | None = None,
    legal_type: str | None = None,
) -> dict[str, Any]:
    body = (
        f"Title: {title}\n"
        f"Citation: {citation}\n"
        f"Jurisdiction: {jurisdiction}\n"
        f"Source URL: {source_url or 'verify from official source'}\n\n"
        f"{text.strip()}"
    )
    return {
        "title": title,
        "source_name": title,
        "citation": citation,
        "jurisdiction": jurisdiction,
        "doc_type": doc_type,
        "legal_type": legal_type or ("case_law" if doc_type == "case_law" else "statute"),
        "source_url": source_url,
        "year": year,
        "text": body,
        "source_version": str(year or "undated"),
        "version_date": f"{year}-01-01" if year else "undated",
        "language": "en",
        "translation_status": "original_or_english_reference",
        "importance_score": 0.8 if doc_type == "case_law" else 0.75,
        "importance_reason": "OmniLegal jurisdiction foundation corpus",
        "importance_signals": ["foundation_corpus", jurisdiction.lower().replace(" ", "_")],
    }


STATUTE_RECORDS: dict[str, list[dict[str, Any]]] = {
    COLLECTION_STATUTES_US: [
        _record(title="United States Constitution", citation="U.S. Const.", jurisdiction="us", doc_type="domestic_law", year=1788, source_url="https://constitution.congress.gov/constitution/", text="The Constitution establishes federal legislative, executive, and judicial power, allocates powers between the federal government and the states, and supplies the Supremacy Clause. For legal research it anchors separation of powers, federalism, due process, equal protection, search and seizure, speech, religion, war powers, appointments, and judicial review questions."),
        _record(title="Bill of Rights", citation="U.S. Const. amends. I-X", jurisdiction="us", doc_type="domestic_law", year=1791, source_url="https://constitution.congress.gov/constitution/amendment-1/", text="The first ten amendments protect speech, religion, press, assembly, arms, security from unreasonable searches and seizures, criminal procedure rights, civil jury rights, and reserved powers. They are central to constitutional litigation and are applied against the states through incorporation doctrine under the Fourteenth Amendment."),
        _record(title="Fourteenth Amendment", citation="U.S. Const. amend. XIV", jurisdiction="us", doc_type="domestic_law", year=1868, source_url="https://constitution.congress.gov/constitution/amendment-14/", text="The Fourteenth Amendment contains the Citizenship Clause, Privileges or Immunities Clause, Due Process Clause, and Equal Protection Clause. It is the core federal constitutional source for civil rights, incorporation of rights against states, substantive due process, procedural fairness, and equality review."),
        _record(title="Administrative Procedure Act", citation="5 U.S.C. ss. 551-559, 701-706", jurisdiction="us", doc_type="domestic_law", year=1946, source_url="https://uscode.house.gov/", text="The APA governs federal agency rulemaking and adjudication and provides judicial review standards for agency action. Research issues include notice-and-comment rulemaking, arbitrary and capricious review, substantial evidence, agency discretion, exhaustion, final agency action, and remedies for unlawful agency action."),
        _record(title="Foreign Sovereign Immunities Act", citation="28 U.S.C. ss. 1602-1611", jurisdiction="us", doc_type="domestic_law", year=1976, source_url="https://uscode.house.gov/", text="The FSIA is the primary US statute governing immunity of foreign states and their agencies or instrumentalities in US courts. Key exceptions include waiver, commercial activity, expropriation, torts in the United States, arbitration, terrorism-related exceptions, and rules on attachment and execution."),
        _record(title="Alien Tort Statute", citation="28 U.S.C. s. 1350", jurisdiction="us", doc_type="domestic_law", year=1789, source_url="https://uscode.house.gov/", text="The Alien Tort Statute gives federal district courts jurisdiction over civil actions by aliens for torts committed in violation of the law of nations or a treaty of the United States. Modern research focuses on Sosa, Kiobel, Jesner, Nestle, extraterritoriality, corporate liability, and the narrow class of actionable international norms."),
        _record(title="War Powers Resolution", citation="50 U.S.C. ss. 1541-1550", jurisdiction="us", doc_type="domestic_law", year=1973, source_url="https://uscode.house.gov/", text="The War Powers Resolution regulates presidential introduction of US armed forces into hostilities. It requires consultation, reporting, and withdrawal absent congressional authorization after statutory periods, while leaving contested constitutional questions over commander-in-chief authority and congressional war powers."),
        _record(title="Title VII of the Civil Rights Act", citation="42 U.S.C. ss. 2000e et seq.", jurisdiction="us", doc_type="domestic_law", year=1964, source_url="https://uscode.house.gov/", text="Title VII prohibits employment discrimination on protected grounds and supports disparate treatment, disparate impact, retaliation, and harassment claims. Research often turns on administrative exhaustion, burden-shifting, mixed motives, remedies, and the scope of sex discrimination after Bostock."),
    ],
    COLLECTION_STATUTES_UK: [
        _record(title="Human Rights Act 1998", citation="Human Rights Act 1998", jurisdiction="uk", doc_type="domestic_law", year=1998, source_url="https://www.legislation.gov.uk/ukpga/1998/42/contents", text="The Human Rights Act incorporates Convention rights into UK domestic law. Public authorities must act compatibly with Convention rights, courts must interpret legislation compatibly so far as possible, and higher courts may issue declarations of incompatibility without invalidating primary legislation."),
        _record(title="Constitutional Reform Act 2005", citation="Constitutional Reform Act 2005", jurisdiction="uk", doc_type="domestic_law", year=2005, source_url="https://www.legislation.gov.uk/ukpga/2005/4/contents", text="This Act altered the office of Lord Chancellor, strengthened judicial independence, created the Supreme Court of the United Kingdom, and established the Judicial Appointments Commission. It is central to UK separation of powers and judicial independence research."),
        _record(title="European Union (Withdrawal) Act 2018", citation="European Union (Withdrawal) Act 2018", jurisdiction="uk", doc_type="domestic_law", year=2018, source_url="https://www.legislation.gov.uk/ukpga/2018/16/contents", text="The Withdrawal Act repealed the European Communities Act 1972 and retained much EU-derived law as domestic law after exit day. It is important for questions of retained EU law, delegated powers, interpretive continuity, supremacy, and post-Brexit constitutional change."),
        _record(title="Constitutional Reform and Governance Act 2010", citation="Constitutional Reform and Governance Act 2010", jurisdiction="uk", doc_type="domestic_law", year=2010, source_url="https://www.legislation.gov.uk/ukpga/2010/25/contents", text="CRAG 2010 places treaty ratification before Parliament under a statutory laying procedure and reforms civil service and public records rules. It is frequently relevant to treaty-making, prerogative powers, and parliamentary control of international agreements."),
        _record(title="Equality Act 2010", citation="Equality Act 2010", jurisdiction="uk", doc_type="domestic_law", year=2010, source_url="https://www.legislation.gov.uk/ukpga/2010/15/contents", text="The Equality Act consolidates UK anti-discrimination law. It protects characteristics including age, disability, gender reassignment, marriage and civil partnership, pregnancy and maternity, race, religion or belief, sex, and sexual orientation, and structures direct discrimination, indirect discrimination, harassment, victimisation, and public sector equality duties."),
        _record(title="Data Protection Act 2018", citation="Data Protection Act 2018", jurisdiction="uk", doc_type="domestic_law", year=2018, source_url="https://www.legislation.gov.uk/ukpga/2018/12/contents", text="The Data Protection Act 2018 supplements UK data protection rules and implements law-enforcement and intelligence-processing regimes. It is read with the UK GDPR and is relevant to privacy, processing bases, data subject rights, enforcement, and public authority processing."),
        _record(title="Police and Criminal Evidence Act 1984", citation="Police and Criminal Evidence Act 1984", jurisdiction="uk", doc_type="domestic_law", year=1984, source_url="https://www.legislation.gov.uk/ukpga/1984/60/contents", text="PACE is the core UK statute on stop and search, arrest, detention, interview, custody records, search warrants, seizure, and codes of practice. For practical criminal-procedure research it is the first source for arrest powers, detention safeguards, access to legal advice, treatment of detainees, and the structure of police powers in England and Wales."),
        _record(title="Road Traffic Act 1988", citation="Road Traffic Act 1988", jurisdiction="uk", doc_type="domestic_law", year=1988, source_url="https://www.legislation.gov.uk/ukpga/1988/52/contents", text="The Road Traffic Act 1988 regulates driver licensing, driving offences, document production, disqualification, insurance, and police powers connected to road traffic enforcement. It is central to questions about driving entitlement, roadside production of licences, penalties for unlicensed driving, and the interaction between traffic offences and criminal procedure."),
    ],
    COLLECTION_STATUTES_EU: [
        _record(title="Treaty on European Union", citation="TEU", jurisdiction="eu", doc_type="domestic_law", year=1992, source_url="https://eur-lex.europa.eu/", text="The TEU states the Union's values, competences, institutional framework, democratic principles, enhanced cooperation, common foreign and security policy, and accession/withdrawal rules. Article 2 values, Article 4 sincere cooperation, Article 5 conferral, subsidiarity and proportionality, Article 6 rights, Article 7 rule-of-law procedures, and Article 50 withdrawal are recurrent research anchors."),
        _record(title="Treaty on the Functioning of the European Union", citation="TFEU", jurisdiction="eu", doc_type="domestic_law", year=1957, source_url="https://eur-lex.europa.eu/", text="The TFEU contains detailed rules on EU competences, internal market freedoms, competition, state aid, citizenship, area of freedom security and justice, external action, and judicial remedies. It is the main source for free movement, competition law, preliminary references, annulment, infringement, and damages actions."),
        _record(title="Charter of Fundamental Rights of the European Union", citation="Charter of Fundamental Rights of the European Union", jurisdiction="eu", doc_type="domestic_law", year=2000, source_url="https://eur-lex.europa.eu/", text="The Charter protects dignity, freedoms, equality, solidarity, citizens' rights, and justice rights when EU law is being implemented. Important provisions include dignity, privacy, data protection, expression, non-discrimination, effective remedy, fair trial, legality, and proportionality of limitations under Article 52."),
        _record(title="General Data Protection Regulation", citation="Regulation (EU) 2016/679", jurisdiction="eu", doc_type="domestic_law", year=2016, source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj", text="The GDPR governs personal data processing in the EU and has extraterritorial reach in defined circumstances. Core issues include lawful bases, transparency, data subject rights, controller and processor duties, international transfers, enforcement, administrative fines, and special-category data."),
        _record(title="Digital Services Act", citation="Regulation (EU) 2022/2065", jurisdiction="eu", doc_type="domestic_law", year=2022, source_url="https://eur-lex.europa.eu/eli/reg/2022/2065/oj", text="The DSA regulates intermediary services, hosting providers, online platforms, and very large online platforms. It addresses notice-and-action, transparency, recommender systems, advertising, systemic risk mitigation, due diligence, and enforcement by national coordinators and the Commission."),
        _record(title="Artificial Intelligence Act", citation="Regulation (EU) 2024/1689", jurisdiction="eu", doc_type="domestic_law", year=2024, source_url="https://eur-lex.europa.eu/eli/reg/2024/1689/oj", text="The EU AI Act creates a risk-based framework for AI systems, including prohibited practices, high-risk system obligations, transparency rules, general-purpose AI rules, conformity assessment, governance, and penalties. Research should verify phased application dates and delegated or implementing acts."),
    ],
    COLLECTION_STATUTES_IN: [
        _record(title="Constitution of India", citation="Constitution of India", jurisdiction="india", doc_type="domestic_law", year=1950, source_url="https://legislative.gov.in/constitution-of-india/", text="The Constitution establishes parliamentary government, federal structure, fundamental rights, directive principles, emergency powers, judicial review, and constitutional amendment. It is central to Indian public law questions on equality, liberty, federalism, basic structure, reservations, emergency, and separation of powers."),
        _record(title="Bharatiya Nyaya Sanhita 2023", citation="Bharatiya Nyaya Sanhita, 2023", jurisdiction="india", doc_type="domestic_law", year=2023, source_url="https://legislative.gov.in/", text="The Bharatiya Nyaya Sanhita replaces the Indian Penal Code framework for substantive criminal offences. Legal research should verify commencement, amendments, transitional provisions, and relationship to older IPC authorities when applying older precedent."),
        _record(title="Bharatiya Nagarik Suraksha Sanhita 2023", citation="Bharatiya Nagarik Suraksha Sanhita, 2023", jurisdiction="india", doc_type="domestic_law", year=2023, source_url="https://legislative.gov.in/", text="The BNSS replaces the Code of Criminal Procedure framework for criminal investigation, arrest, bail, trial, sentencing procedure, appeal, and revision. Research must track transition from CrPC cases and the treatment of pending proceedings."),
        _record(title="Bharatiya Sakshya Adhiniyam 2023", citation="Bharatiya Sakshya Adhiniyam, 2023", jurisdiction="india", doc_type="domestic_law", year=2023, source_url="https://legislative.gov.in/", text="The Bharatiya Sakshya Adhiniyam replaces the Evidence Act framework for relevance, admissibility, burden of proof, presumptions, electronic evidence, documentary proof, witnesses, and privilege. Older Evidence Act precedent may still guide corresponding provisions but must be mapped carefully."),
        _record(title="Information Technology Act 2000", citation="Information Technology Act, 2000", jurisdiction="india", doc_type="domestic_law", year=2000, source_url="https://www.meity.gov.in/", text="The IT Act governs electronic records, digital signatures, cyber offences, intermediary liability, blocking powers, and adjudication. It is central to Indian cyber law and is read with IT Rules, privacy developments, and constitutional free speech decisions."),
        _record(title="Right to Information Act 2005", citation="Right to Information Act, 2005", jurisdiction="india", doc_type="domestic_law", year=2005, source_url="https://rti.gov.in/", text="The RTI Act creates a statutory right to access information held by public authorities, subject to exemptions. It structures public information officers, appeals, commissions, time limits, proactive disclosure, and public-interest balancing."),
        _record(title="Motor Vehicles Act, 1988", citation="Motor Vehicles Act, 1988", jurisdiction="india", doc_type="domestic_law", year=1988, source_url="https://www.indiacode.nic.in/handle/123456789/19009?sam_handle=123456789%2F2454", text="The Motor Vehicles Act is India's main road transport statute governing driver licensing, vehicle registration, insurance, permits, traffic regulation, and penalties. For cross-border driving questions it is the core domestic source on the issuance and validity of Indian driving licences and the broader regulatory context for international driving permits and transport documentation."),
    ],
    COLLECTION_STATUTES_RU: [
        _record(title="Constitution of the Russian Federation", citation="Constitution of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=1993, source_url="http://www.kremlin.ru/acts/constitution", text="The Constitution establishes the foundations of the constitutional order, rights and freedoms, federal structure, President, Federal Assembly, Government, judiciary, local self-government, and amendment rules. Researchers must verify current text after constitutional amendments, especially 2020 changes."),
        _record(title="Civil Code of the Russian Federation", citation="Civil Code of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=1994, source_url="http://pravo.gov.ru/", text="The Civil Code structures property, obligations, contracts, corporate law, intellectual property, inheritance, and private international law. It is the primary source for Russian private law research, subject to current amendments and official text verification."),
        _record(title="Criminal Code of the Russian Federation", citation="Criminal Code of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=1996, source_url="http://pravo.gov.ru/", text="The Criminal Code defines offences, penalties, general principles of criminal liability, defences, sentencing, and special offences. Research should verify current official text and amendments, especially for national security, extremism, information, and sanctions-related offences."),
        _record(title="Arbitrazh Procedure Code", citation="Arbitrazh Procedure Code of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=2002, source_url="http://pravo.gov.ru/", text="The Arbitrazh Procedure Code governs commercial court proceedings, jurisdiction, evidence, appeals, supervisory review, and enforcement in business disputes. It is central to Russian commercial litigation and administrative economic disputes."),
        _record(title="Federal Constitutional Law on the Constitutional Court", citation="Federal Constitutional Law on the Constitutional Court of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=1994, source_url="http://pravo.gov.ru/", text="This law governs jurisdiction, procedure, and effects of decisions of the Constitutional Court. It is relevant to constitutional review, rights claims, federal competence disputes, and interaction between constitutional doctrine and legislation."),
        _record(title="Code of Administrative Offences of the Russian Federation", citation="Code of Administrative Offences of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=2001, source_url="https://publication.pravo.gov.ru/", text="The Code of Administrative Offences supplies the general framework for administrative liability, protocols, fines, appeals, and many traffic-related offences. For practical road-stop scenarios it is the main starting point for whether the conduct is treated as an administrative violation rather than a criminal charge, how the case is documented, and what immediate penalties or review routes may apply."),
        _record(title="Criminal Procedure Code of the Russian Federation", citation="Criminal Procedure Code of the Russian Federation", jurisdiction="russia", doc_type="domestic_law", year=2001, source_url="https://publication.pravo.gov.ru/", text="The Criminal Procedure Code governs arrest, detention, suspect status, defence counsel, interpreters, evidence gathering, and judicial supervision of criminal proceedings. It becomes critical if a road-incident matter escalates beyond an administrative offence or if the person is formally detained or charged."),
        _record(title="Federal Law on Road Traffic Safety", citation="Federal Law No. 196-FZ of 10 December 1995", jurisdiction="russia", doc_type="domestic_law", year=1995, source_url="https://ips.pravo.gov.ru/api/ips/legislation/document?baseid=None&hash=f541fae60f2468397fc18f632b6a3277f9bb1050cbea9398e78959a4558555e8", text="This federal law provides the general legal framework for road traffic safety, admission to driving, driver qualification, licensing, and state supervision of compliance with road-safety legislation. It is one of the key Russian statutes for questions about foreign drivers, recognition of driving entitlement, and the regulatory background to document checks and traffic enforcement."),
        _record(title="Federal Law on Police", citation="Federal Law No. 3-FZ of 7 February 2011", jurisdiction="russia", doc_type="domestic_law", year=2011, source_url="https://publication.pravo.gov.ru/", text="The federal Police law structures police powers, duties, identification, delivery to police premises, use of coercive measures, and obligations to explain rights and grounds for action. It is relevant whenever a traffic stop or identity check leads to administrative restraint, transport to a station, or broader questions about police authority and detainee safeguards."),
    ],
    COLLECTION_STATUTES_IL: [
        _record(title="Basic Law: Human Dignity and Liberty", citation="Basic Law: Human Dignity and Liberty", jurisdiction="israel", doc_type="domestic_law", year=1992, source_url="https://main.knesset.gov.il/EN/activity/pages/basiclaws.aspx", text="This Basic Law protects life, body, dignity, property, liberty, privacy, and movement from Israel. Its limitation clause permits rights infringement only by law befitting the values of the State of Israel, for a proper purpose, and no more than required."),
        _record(title="Basic Law: Freedom of Occupation", citation="Basic Law: Freedom of Occupation", jurisdiction="israel", doc_type="domestic_law", year=1994, source_url="https://main.knesset.gov.il/EN/activity/pages/basiclaws.aspx", text="This Basic Law protects the right of every Israeli national or resident to engage in any occupation, profession, or trade. It includes a limitation clause and is central to constitutional proportionality analysis in economic liberty cases."),
        _record(title="Basic Law: The Judiciary", citation="Basic Law: The Judiciary", jurisdiction="israel", doc_type="domestic_law", year=1984, source_url="https://main.knesset.gov.il/EN/activity/pages/basiclaws.aspx", text="This Basic Law structures the courts, judicial independence, appointment, tenure, discipline, and the Supreme Court's jurisdiction, including its sitting as the High Court of Justice. It anchors judicial review and administrative law petitions."),
        _record(title="Basic Law: The Government", citation="Basic Law: The Government", jurisdiction="israel", doc_type="domestic_law", year=2001, source_url="https://main.knesset.gov.il/EN/activity/pages/basiclaws.aspx", text="This Basic Law governs formation, powers, and resignation of the Government, the Prime Minister, ministers, emergency regulations, and continuity. It is relevant to executive authority, coalition formation, and emergency powers."),
        _record(title="Basic Law: Israel - The Nation State of the Jewish People", citation="Basic Law: Israel - The Nation State of the Jewish People", jurisdiction="israel", doc_type="domestic_law", year=2018, source_url="https://main.knesset.gov.il/EN/activity/pages/basiclaws.aspx", text="This Basic Law declares national identity provisions concerning the State of Israel, symbols, capital, language, ingathering of exiles, Jewish settlement, calendar, and holidays. It is significant for constitutional interpretation and equality debates."),
    ],
}


NATIONAL_RECORDS: dict[str, list[dict[str, Any]]] = {
    COLLECTION_NATIONAL_US: STATUTE_RECORDS[COLLECTION_STATUTES_US],
    COLLECTION_NATIONAL_UK: STATUTE_RECORDS[COLLECTION_STATUTES_UK],
    COLLECTION_NATIONAL_EU: STATUTE_RECORDS[COLLECTION_STATUTES_EU],
    COLLECTION_NATIONAL_IN: STATUTE_RECORDS[COLLECTION_STATUTES_IN],
    COLLECTION_NATIONAL_RU: STATUTE_RECORDS[COLLECTION_STATUTES_RU],
    COLLECTION_NATIONAL_IL: STATUTE_RECORDS[COLLECTION_STATUTES_IL],
}


CASE_RECORDS: dict[str, list[dict[str, Any]]] = {
    COLLECTION_CASE_LAW_GLOBAL: [
        _record(title="Tinoco Arbitration", citation="Great Britain v Costa Rica, 1 RIAA 369 (1923)", jurisdiction="international", doc_type="case_law", year=1923, source_url="https://legal.un.org/riaa/cases/vol_I/369-399.pdf", text="Chief Justice William Howard Taft, sitting as sole arbitrator, treated the Tinoco regime as a de facto government because it exercised effective control over Costa Rica and received habitual obedience. Non-recognition by other states was evidence but not conclusive where non-recognition rested on legitimacy rather than factual control. The award is a leading authority on de facto governments, recognition, and successor responsibility for acts of an effective government."),
        _record(title="Corfu Channel", citation="United Kingdom v Albania, ICJ Reports 1949 p. 4", jurisdiction="international", doc_type="case_law", year=1949, source_url="https://www.icj-cij.org/case/1", text="The ICJ held Albania responsible for failing to warn of mines in its territorial waters and rejected the United Kingdom's unilateral minesweeping operation as a violation of sovereignty. The case is foundational for circumstantial evidence, the duty not to knowingly allow territory to be used contrary to the rights of other states, innocent passage, and limits on forcible self-help."),
        _record(title="Caroline case", citation="Caroline correspondence, 29 BFSP 1137 (1837-1842)", jurisdiction="international", doc_type="case_law", year=1842, source_url="https://avalon.law.yale.edu/19th_century/br-1842d.asp", text="The Caroline correspondence is the classic formulation of necessity and proportionality for anticipatory self-defence. The Webster test asks whether the necessity of self-defence is instant, overwhelming, leaving no choice of means and no moment for deliberation, and whether the response remains proportionate. It is a foundational authority for debates on anticipatory self-defence under customary international law and Article 51 analysis."),
        _record(title="North Sea Continental Shelf", citation="ICJ Reports 1969 p. 3", jurisdiction="international", doc_type="case_law", year=1969, source_url="https://www.icj-cij.org/case/52", text="The ICJ held that the equidistance rule had not become customary international law for non-parties to the Continental Shelf Convention. It formulated the two-element analysis of custom: extensive and virtually uniform state practice plus opinio juris, and required delimitation by agreement according to equitable principles."),
        _record(title="Barcelona Traction", citation="Belgium v Spain, ICJ Reports 1970 p. 3", jurisdiction="international", doc_type="case_law", year=1970, source_url="https://www.icj-cij.org/case/50", text="The ICJ denied Belgium standing to espouse shareholder claims for a Canadian company and articulated the idea of obligations erga omnes owed to the international community as a whole. The decision is central to diplomatic protection, corporate nationality, standing, and community-interest obligations."),
        _record(title="Legal Consequences of the Construction of a Wall in the Occupied Palestinian Territory", citation="Advisory Opinion, ICJ Reports 2004 p. 136", jurisdiction="international", doc_type="case_law", year=2004, source_url="https://www.icj-cij.org/case/131", text="The ICJ advised that construction of the wall and its associated regime in the Occupied Palestinian Territory breached international humanitarian law and human rights obligations. The Court used Barcelona Traction's erga omnes doctrine to explain that certain obligations violated by Israel were owed to the international community as a whole, giving all states a legal interest in their protection. The opinion then derived consequences for third states, including non-recognition of the illegal situation, non-assistance in maintaining it, and cooperation to bring the unlawful situation to an end."),
        _record(title="Military and Paramilitary Activities in and against Nicaragua", citation="Nicaragua v United States, ICJ Reports 1986 p. 14", jurisdiction="international", doc_type="case_law", year=1986, source_url="https://www.icj-cij.org/case/70", text="The ICJ held that the United States violated the prohibition on the use of force and non-intervention and analysed customary international law independently of treaty law. The case is central to armed attack, collective self-defence, evidentiary burdens, non-intervention, and the customary status of Article 2(4) and Article 51 principles."),
        _record(title="Oil Platforms", citation="Islamic Republic of Iran v United States of America, ICJ Reports 2003 p. 161", jurisdiction="international", doc_type="case_law", year=2003, source_url="https://www.icj-cij.org/case/90", text="In Oil Platforms, the ICJ assessed United States reliance on self-defence after attacks on shipping and oil facilities. The Court required proof of an armed attack attributable to Iran and examined necessity and proportionality, treating Article 51 self-defence as unavailable where the factual threshold was not established. The case is central to armed attack threshold, evidence, necessity, proportionality, and use-of-force analysis."),
        _record(title="Gabčikovo-Nagymaros Project", citation="Hungary/Slovakia, ICJ Reports 1997 p. 7", jurisdiction="international", doc_type="case_law", year=1997, source_url="https://www.icj-cij.org/case/92", text="The ICJ rejected Hungary's reliance on necessity to terminate or suspend treaty obligations and addressed material breach, impossibility, changed circumstances, and environmental considerations. The case is important for state responsibility, treaty law, sustainable development, and equitable implementation of continuing treaty regimes."),
        _record(title="Jurisdictional Immunities of the State", citation="Germany v Italy, ICJ Reports 2012 p. 99", jurisdiction="international", doc_type="case_law", year=2012, source_url="https://www.icj-cij.org/case/143", text="The ICJ held that Italy violated Germany's jurisdictional immunity by allowing civil claims for wartime acts and measures against German property. The Court treated state immunity as procedural and not displaced by alleged jus cogens violations, while leaving substantive responsibility separate from forum immunity."),
        _record(title="Arrest Warrant", citation="Democratic Republic of the Congo v Belgium, ICJ Reports 2002 p. 3", jurisdiction="international", doc_type="case_law", year=2002, source_url="https://www.icj-cij.org/case/121", text="The ICJ held that an incumbent foreign minister enjoyed immunity from criminal jurisdiction and inviolability before foreign national courts. The judgment distinguishes immunity from impunity and identifies possible fora after office or before international criminal tribunals."),
    ],
    COLLECTION_CASE_LAW_US: [
        _record(title="Marbury v Madison", citation="5 U.S. (1 Cranch) 137 (1803)", jurisdiction="us", doc_type="case_law", year=1803, source_url="https://supreme.justia.com/cases/federal/us/5/137/", text="The Supreme Court held that it had authority to say what the law is and to decline to apply a statute inconsistent with the Constitution. Marbury is the canonical source for judicial review and the relationship between constitutional supremacy and ordinary legislation."),
        _record(title="Brown v Board of Education", citation="347 U.S. 483 (1954)", jurisdiction="us", doc_type="case_law", year=1954, source_url="https://supreme.justia.com/cases/federal/us/347/483/", text="The Court held that racial segregation in public schools violates equal protection because separate educational facilities are inherently unequal. Brown is foundational for equal protection, desegregation, strict scrutiny development, and constitutional anti-subordination principles."),
        _record(title="Youngstown Sheet and Tube Co. v Sawyer", citation="343 U.S. 579 (1952)", jurisdiction="us", doc_type="case_law", year=1952, source_url="https://supreme.justia.com/cases/federal/us/343/579/", text="The Court invalidated President Truman's seizure of steel mills during the Korean War. Justice Jackson's concurrence supplies the tripartite framework for presidential power: maximum authority with Congress, a zone of twilight without congressional action, and lowest ebb against Congress."),
        _record(title="Chevron U.S.A. Inc. v Natural Resources Defense Council", citation="467 U.S. 837 (1984)", jurisdiction="us", doc_type="case_law", year=1984, source_url="https://supreme.justia.com/cases/federal/us/467/837/", text="Chevron formerly required courts to defer to reasonable agency interpretations of ambiguous statutes. Researchers must account for the Supreme Court's later overruling of Chevron deference in Loper Bright Enterprises v Raimondo, while older cases may remain relevant historically and for prior administrative law doctrine."),
        _record(title="Loper Bright Enterprises v Raimondo", citation="603 U.S. ___ (2024)", jurisdiction="us", doc_type="case_law", year=2024, source_url="https://www.supremecourt.gov/opinions/23pdf/22-451_7m58.pdf", text="The Supreme Court overruled Chevron deference and held that courts must exercise independent judgment in deciding whether an agency acted within statutory authority. The case is now central to statutory interpretation, administrative law, and judicial review of agency interpretations."),
    ],
    COLLECTION_CASE_LAW_UK: [
        _record(title="Entick v Carrington", citation="(1765) 19 St Tr 1029", jurisdiction="uk", doc_type="case_law", year=1765, source_url="https://www.bailii.org/", text="The court held that executive officials needed legal authority for searches and seizures and could not rely on general state necessity. Entick is a foundational UK authority for legality, limits on executive power, property, privacy, and the rule of law."),
        _record(title="Associated Provincial Picture Houses v Wednesbury Corporation", citation="[1948] 1 KB 223", jurisdiction="uk", doc_type="case_law", year=1948, source_url="https://www.bailii.org/", text="The Court of Appeal formulated the classic standard of irrationality in judicial review. A public authority decision may be unlawful if it is so unreasonable that no reasonable authority could have made it, subject to later development through proportionality and rights-based review."),
        _record(title="Anisminic Ltd v Foreign Compensation Commission", citation="[1969] 2 AC 147", jurisdiction="uk", doc_type="case_law", year=1969, source_url="https://www.bailii.org/", text="The House of Lords treated errors of law by a public body as jurisdictional and resisted broad ouster of judicial review. Anisminic is central to rule-of-law review, statutory interpretation of ouster clauses, and the modern decline of the jurisdictional/non-jurisdictional error distinction."),
        _record(title="R v Secretary of State for the Home Department, ex parte Fire Brigades Union", citation="[1995] 2 AC 513", jurisdiction="uk", doc_type="case_law", year=1995, source_url="https://www.bailii.org/", text="The House of Lords held that a minister could not use prerogative power to frustrate a statutory scheme that Parliament had enacted but not yet brought into force. The case is important for prerogative powers, legitimate expectation, and parliamentary sovereignty."),
        _record(title="R (Miller) v Secretary of State for Exiting the European Union", citation="[2017] UKSC 5", jurisdiction="uk", doc_type="case_law", year=2017, source_url="https://www.supremecourt.uk/cases/uksc-2016-0196.html", text="The UK Supreme Court held that ministers could not trigger Article 50 using prerogative powers without parliamentary authorization because withdrawal would alter domestic law and statutory rights. The case is central to prerogative power, parliamentary sovereignty, and Brexit constitutional law."),
        _record(title="R (Miller) v Prime Minister; Cherry v Advocate General", citation="[2019] UKSC 41", jurisdiction="uk", doc_type="case_law", year=2019, source_url="https://www.supremecourt.uk/cases/uksc-2019-0192.html", text="The Supreme Court held that prorogation was justiciable and unlawful because it frustrated Parliament's constitutional functions without reasonable justification. The case is a leading authority on constitutional principles, accountability, and limits of prerogative power."),
    ],
    COLLECTION_CASE_LAW_EU: [
        _record(title="Van Gend en Loos", citation="Case 26/62", jurisdiction="eu", doc_type="case_law", year=1963, source_url="https://eur-lex.europa.eu/", text="The Court of Justice held that EU law can confer rights on individuals enforceable in national courts. The case established direct effect and described the Community as a new legal order of international law."),
        _record(title="Costa v ENEL", citation="Case 6/64", jurisdiction="eu", doc_type="case_law", year=1964, source_url="https://eur-lex.europa.eu/", text="The Court of Justice held that EU law has primacy over conflicting national law. Costa v ENEL is foundational for supremacy, uniformity, and the autonomous legal order of the European Union."),
        _record(title="Cassis de Dijon", citation="Case 120/78", jurisdiction="eu", doc_type="case_law", year=1979, source_url="https://eur-lex.europa.eu/", text="The Court held that goods lawfully marketed in one Member State should generally be admitted in others unless justified by mandatory requirements. The case created mutual recognition and proportionality analysis in free movement of goods."),
        _record(title="Francovich", citation="Joined Cases C-6/90 and C-9/90", jurisdiction="eu", doc_type="case_law", year=1991, source_url="https://eur-lex.europa.eu/", text="The Court recognized Member State liability in damages for failure to implement EU directives where the directive confers rights, content is identifiable, and causation exists. Francovich is central to effective judicial protection and enforcement of EU law."),
        _record(title="Kadi", citation="Joined Cases C-402/05 P and C-415/05 P", jurisdiction="eu", doc_type="case_law", year=2008, source_url="https://eur-lex.europa.eu/", text="The Court reviewed EU measures implementing UN sanctions against EU fundamental rights standards. Kadi is important for autonomy of EU law, judicial protection, due process, and interaction between EU law and international security obligations."),
        _record(title="Data Protection Commissioner v Facebook Ireland and Schrems", citation="Case C-311/18, Schrems II", jurisdiction="eu", doc_type="case_law", year=2020, source_url="https://eur-lex.europa.eu/", text="The Court invalidated the EU-US Privacy Shield adequacy decision and upheld standard contractual clauses subject to effective protection assessment. Schrems II is central to international data transfers, surveillance concerns, and GDPR enforcement."),
    ],
    COLLECTION_CASE_LAW_IN: [
        _record(title="Kesavananda Bharati v State of Kerala", citation="(1973) 4 SCC 225", jurisdiction="india", doc_type="case_law", year=1973, source_url="https://main.sci.gov.in/", text="The Supreme Court held that Parliament may amend the Constitution but cannot alter its basic structure. The basic structure doctrine protects constitutional identity, judicial review, rule of law, separation of powers, federalism, secularism, and fundamental rights from destructive amendments."),
        _record(title="Maneka Gandhi v Union of India", citation="(1978) 1 SCC 248", jurisdiction="india", doc_type="case_law", year=1978, source_url="https://main.sci.gov.in/", text="The Supreme Court expanded Article 21 by requiring procedure depriving life or personal liberty to be just, fair, and reasonable. The decision linked Articles 14, 19, and 21 and is foundational for substantive due process-like review in Indian constitutional law."),
        _record(title="Minerva Mills v Union of India", citation="(1980) 3 SCC 625", jurisdiction="india", doc_type="case_law", year=1980, source_url="https://main.sci.gov.in/", text="The Supreme Court reaffirmed the basic structure doctrine and held that limited amending power itself forms part of the basic structure. The case balances Fundamental Rights and Directive Principles as complementary constitutional commitments."),
        _record(title="S.R. Bommai v Union of India", citation="(1994) 3 SCC 1", jurisdiction="india", doc_type="case_law", year=1994, source_url="https://main.sci.gov.in/", text="The Court made presidential proclamations under Article 356 subject to judicial review and reinforced federalism and secularism as constitutional principles. The case is central to emergency powers, state government dismissal, and constitutional federalism."),
        _record(title="Justice K.S. Puttaswamy v Union of India", citation="(2017) 10 SCC 1", jurisdiction="india", doc_type="case_law", year=2017, source_url="https://main.sci.gov.in/", text="A nine-judge bench recognized privacy as a fundamental right under the Constitution. Puttaswamy is central to dignity, autonomy, informational privacy, proportionality, data protection, surveillance, and constitutional limits on state action."),
        _record(title="Navtej Singh Johar v Union of India", citation="(2018) 10 SCC 1", jurisdiction="india", doc_type="case_law", year=2018, source_url="https://main.sci.gov.in/", text="The Supreme Court decriminalized consensual same-sex relations by reading down Section 377 of the Penal Code. The case is important for equality, dignity, privacy, constitutional morality, transformative constitutionalism, and anti-discrimination principles."),
        _record(title="D.K. Basu v State of West Bengal", citation="(1997) 1 SCC 416", jurisdiction="india", doc_type="case_law", year=1997, source_url="https://main.sci.gov.in/", text="The Supreme Court laid down safeguards for arrest and detention, including transparency about arrest, notification, medical examination, records, and protection against custodial abuse. It remains one of the leading Indian authorities on arrest procedure, police accountability, and detainee rights."),
        _record(title="Joginder Kumar v State of U.P.", citation="(1994) 4 SCC 260", jurisdiction="india", doc_type="case_law", year=1994, source_url="https://main.sci.gov.in/", text="The Supreme Court stressed that arrest power does not justify routine arrest and that liberty requires a rational justification for taking a person into custody. The case is often cited on the limits of arrest discretion, the need for grounds, and the obligation to inform relatives or friends of the arrest."),
        _record(title="Arnesh Kumar v State of Bihar", citation="(2014) 8 SCC 273", jurisdiction="india", doc_type="case_law", year=2014, source_url="https://main.sci.gov.in/", text="The Supreme Court reinforced limits on unnecessary arrest and directed careful compliance with statutory safeguards before remand. It is a practical leading case on arrest discipline, liberty-protective procedure, and judicial scrutiny of routine custody requests."),
    ],
    COLLECTION_CASE_LAW_RU: [
        _record(title="Russian Constitutional Court death penalty moratorium cases", citation="Constitutional Court of the Russian Federation, death penalty jurisprudence", jurisdiction="russia", doc_type="case_law", year=1999, source_url="http://ksrf.ru/", text="The Constitutional Court's death penalty jurisprudence tied capital punishment to jury trial guarantees and later maintained a moratorium. The line of authority is relevant to constitutional rights, criminal punishment, human dignity, and Russia's constitutional treatment of capital punishment."),
        _record(title="Anchugov and Gladkov v Russia", citation="ECtHR, Applications nos. 11157/04 and 15162/05", jurisdiction="russia", doc_type="case_law", year=2013, source_url="https://hudoc.echr.coe.int/", text="The European Court of Human Rights held that Russia's blanket prisoner voting ban violated Article 3 of Protocol No. 1. The case is important for Russian constitutional interaction with international human rights judgments and later Constitutional Court responses."),
        _record(title="Yukos v Russia", citation="ECtHR, OAO Neftyanaya Kompaniya Yukos v Russia", jurisdiction="russia", doc_type="case_law", year=2011, source_url="https://hudoc.echr.coe.int/", text="The ECtHR examined tax enforcement and fair trial complaints arising from proceedings against Yukos. The case is important for property rights, due process, enforcement measures, and investment disputes connected to Russian state action."),
        _record(title="Konstantin Markin v Russia", citation="ECtHR Grand Chamber, Application no. 30078/06", jurisdiction="russia", doc_type="case_law", year=2012, source_url="https://hudoc.echr.coe.int/", text="The Grand Chamber found discrimination in denial of parental leave to a male serviceman. The case became significant in Russian constitutional dialogue over ECtHR judgments, equality, military service, and family rights."),
    ],
    COLLECTION_CASE_LAW_IL: [
        _record(title="United Mizrahi Bank v Migdal Cooperative Village", citation="CA 6821/93", jurisdiction="israel", doc_type="case_law", year=1995, source_url="https://versa.cardozo.yu.edu/", text="The Supreme Court treated Basic Laws on rights as having constitutional status and recognized judicial review of ordinary legislation inconsistent with protected rights. The decision is central to Israel's constitutional revolution and proportionality review."),
        _record(title="Public Committee Against Torture in Israel v Government of Israel", citation="HCJ 5100/94", jurisdiction="israel", doc_type="case_law", year=1999, source_url="https://versa.cardozo.yu.edu/", text="The High Court held that the security service lacked statutory authority to use physical interrogation methods amounting to coercion. The case is central to administrative legality, human dignity, security powers, and limits on necessity arguments."),
        _record(title="Beit Sourik Village Council v Government of Israel", citation="HCJ 2056/04", jurisdiction="israel", doc_type="case_law", year=2004, source_url="https://versa.cardozo.yu.edu/", text="The Court applied proportionality review to the route of the separation barrier, balancing security needs against harm to local residents. The case is important for military commander powers, occupation law, proportionality, and judicial review in security contexts."),
        _record(title="Ka'adan v Israel Lands Administration", citation="HCJ 6698/95", jurisdiction="israel", doc_type="case_law", year=2000, source_url="https://versa.cardozo.yu.edu/", text="The Court held that the state could not allocate land in a manner that discriminated against Arab citizens. Ka'adan is a leading equality decision concerning public resources, state land, and constitutional principles of equal treatment."),
        _record(title="Ressler v Knesset", citation="HCJ 6298/07", jurisdiction="israel", doc_type="case_law", year=2012, source_url="https://versa.cardozo.yu.edu/", text="The Court addressed equality and military service exemptions for yeshiva students, invalidating legislative arrangements after constitutional proportionality analysis. The case is relevant to equality, religion-state relations, and judicial review of Basic Law rights."),
    ],
}


COMMENTARY_RECORDS = [
    _record(title="Sources of international law research guide", citation="ICJ Statute art. 38; OmniLegal foundation note", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://www.icj-cij.org/statute", text="Article 38 of the ICJ Statute lists treaties, custom, general principles, and subsidiary means such as judicial decisions and teachings. Research should separate binding sources from evidence of law, identify parties and reservations for treaties, prove state practice and opinio juris for custom, and distinguish soft-law instruments from legal obligations."),
    _record(title="Treaty interpretation research guide", citation="Vienna Convention on the Law of Treaties arts. 31-33", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf", text="Treaty interpretation begins with ordinary meaning in good faith, context, object and purpose, subsequent agreements, subsequent practice, and relevant rules of international law. Supplementary means such as preparatory work may confirm meaning or resolve ambiguity, and multilingual texts require reconciliation of authentic versions."),
    _record(title="State responsibility research guide", citation="ILC Articles on State Responsibility", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://legal.un.org/ilc/texts/instruments/english/draft_articles/9_6_2001.pdf", text="State responsibility analysis asks whether conduct is attributable to the state, whether it breaches an international obligation, whether any circumstance precludes wrongfulness, and what consequences follow. Remedies include cessation, assurances of non-repetition, restitution, compensation, satisfaction, and countermeasures subject to limits."),
    _record(title="Use of force research guide", citation="UN Charter arts. 2(4), 51", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://www.un.org/en/about-us/un-charter", text="Use-of-force research starts with the Article 2(4) prohibition and recognized exceptions for Security Council authorization and self-defence after an armed attack. Key issues include attribution, necessity, proportionality, collective self-defence, non-state actors, intervention by invitation, humanitarian intervention claims, and jus ad bellum versus IHL separation."),
    _record(title="International human rights research guide", citation="ICCPR; ICESCR; regional human rights treaties", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://www.ohchr.org/", text="Human rights research identifies the treaty, state party status, reservations, derogations, jurisdiction, admissibility, and interpretive materials. Civil and political rights often require legality, legitimate aim, necessity, and proportionality analysis, while economic and social rights often involve progressive realization and minimum core debates."),
    _record(title="Erga omnes obligations and the Wall Advisory Opinion", citation="Barcelona Traction; Wall Advisory Opinion; OmniLegal foundation note", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="https://www.icj-cij.org/case/131", text="Barcelona Traction supplied the ICJ's general formulation that obligations erga omnes are owed to the international community as a whole and that all states have a legal interest in their protection. The 2004 Wall Advisory Opinion applied that formulation outside the diplomatic-protection setting to occupied territory, self-determination, humanitarian law, and third-state consequences. The doctrinal move matters because it links community-interest obligations to duties of non-recognition, non-assistance, and cooperation."),
]


CORE_FALLBACK_RECORDS: dict[str, list[dict[str, Any]]] = {
    COLLECTION_INTL_TREATIES: [
        _record(title="Charter of the United Nations", citation="UN Charter", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1945, source_url="https://www.un.org/en/about-us/un-charter", text="The UN Charter is the constitutional treaty of the United Nations. Key legal anchors include Article 2(4) on the prohibition of force, Article 51 on self-defence, Chapter VI peaceful settlement, Chapter VII Security Council enforcement powers, and Article 103 priority for Charter obligations over inconsistent treaty obligations."),
        _record(title="Statute of the International Court of Justice", citation="ICJ Statute", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1945, source_url="https://www.icj-cij.org/statute", text="The ICJ Statute governs the Court's composition, contentious jurisdiction, advisory opinions, applicable law, procedure, and effect of judgments. Article 38 is the standard reference point for treaties, custom, general principles, judicial decisions, and teachings as materials for determining international law."),
        _record(title="Vienna Convention on the Law of Treaties", citation="1155 UNTS 331", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1969, source_url="https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf", text="The VCLT codifies core treaty law on conclusion, reservations, entry into force, interpretation, invalidity, termination, suspension, and depositaries. Articles 31 to 33 are the central interpretive rules: ordinary meaning, context, object and purpose, subsequent agreement and practice, relevant rules of international law, supplementary means, and multilingual reconciliation."),
        _record(title="International Covenant on Civil and Political Rights", citation="999 UNTS 171", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1966, source_url="https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-civil-and-political-rights", text="The ICCPR protects civil and political rights including life, liberty, fair trial, privacy, expression, religion, association, political participation, equality, and minority rights. Research requires checking state party status, reservations, derogations, jurisdiction, Human Rights Committee materials, and domestic implementation."),
        _record(title="Fourth Geneva Convention", citation="75 UNTS 287", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1949, source_url="https://ihl-databases.icrc.org/en/ihl-treaties/gciv-1949", text="The Fourth Geneva Convention protects civilians in armed conflict and occupation. Issues include protected persons, humane treatment, collective penalties, transfers and deportations, occupying power duties, security measures, and the obligation in common Article 1 to respect and ensure respect for the Conventions."),
        _record(title="Vienna Convention on Consular Relations", citation="596 UNTS 261", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1963, source_url="https://legal.un.org/ilc/texts/instruments/english/conventions/9_2_1963.pdf", text="The Vienna Convention on Consular Relations is the main treaty source on consular functions, contact with nationals, and communication with detained foreign nationals. For cross-border arrest scenarios it is the standard international instrument on consular notification, consular access, and the role of the sending state's consular officers when one of their nationals is detained abroad."),
        _record(title="Convention on Road Traffic", citation="Vienna Convention on Road Traffic, 1968", jurisdiction="international", doc_type="treaty", legal_type="treaty", year=1968, source_url="https://unece.org/DAM/trans/conventn/Conv_road_traffic_EN.pdf", text="The 1968 Convention on Road Traffic is the main multilateral treaty on international road traffic, recognition of driving permits, and harmonised road-traffic rules among contracting parties. It is frequently relevant to questions about whether a foreign driving licence or international driving permit may be recognised in another state, subject always to the receiving state's implementation rules and reservations."),
    ],
    COLLECTION_SHAW_PRIVATE: [
        _record(title="Public international law doctrinal foundation note", citation="OmniLegal foundation commentary", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="verify against primary sources", text="This public foundation note summarizes common public international law research structure without reproducing licensed textbook content. Analysis should identify the relevant source of law, distinguish treaty from custom and general principles, address jurisdiction and admissibility, apply state responsibility where breach is alleged, and separate primary obligations from consequences such as reparation, non-recognition, non-assistance, and cooperation."),
        _record(title="Diplomatic protection and community obligations note", citation="OmniLegal foundation commentary", jurisdiction="international", doc_type="commentary", legal_type="commentary", source_url="verify against primary sources", text="Diplomatic protection traditionally concerns a state's espousal of claims for injury to its nationals, subject to nationality and exhaustion of local remedies. Barcelona Traction is important because it distinguished corporate/shareholder protection from obligations erga omnes, while later authorities used community-interest obligations in settings beyond diplomatic protection."),
    ],
}


DIRECTORY_SPECS: dict[str, tuple[str, str, str]] = {
    COLLECTION_INTL_TREATIES: ("intl_treaties", "international", "treaty"),
    COLLECTION_NATIONAL_US: ("national_us", "us", "domestic_law"),
    COLLECTION_NATIONAL_UK: ("national_uk", "uk", "domestic_law"),
    COLLECTION_NATIONAL_EU: ("national_eu", "eu", "domestic_law"),
    COLLECTION_NATIONAL_IN: ("national_in", "india", "domestic_law"),
    COLLECTION_NATIONAL_RU: ("national_ru", "russia", "domestic_law"),
    COLLECTION_NATIONAL_IL: ("national_il", "israel", "domestic_law"),
    COLLECTION_STATUTES_US: ("statutes_us", "us", "domestic_law"),
    COLLECTION_STATUTES_UK: ("statutes_uk", "uk", "domestic_law"),
    COLLECTION_STATUTES_EU: ("statutes_eu", "eu", "domestic_law"),
    COLLECTION_STATUTES_IN: ("statutes_in", "india", "domestic_law"),
    COLLECTION_STATUTES_RU: ("statutes_ru", "russia", "domestic_law"),
    COLLECTION_STATUTES_IL: ("statutes_il", "israel", "domestic_law"),
    COLLECTION_CASE_LAW_GLOBAL: ("case_law_global", "international", "case_law"),
    COLLECTION_CASE_LAW_US: ("case_law_us", "us", "case_law"),
    COLLECTION_CASE_LAW_UK: ("case_law_uk", "uk", "case_law"),
    COLLECTION_CASE_LAW_EU: ("case_law_eu", "eu", "case_law"),
    COLLECTION_CASE_LAW_IN: ("case_law_in", "india", "case_law"),
    COLLECTION_CASE_LAW_RU: ("case_law_ru", "russia", "case_law"),
    COLLECTION_CASE_LAW_IL: ("case_law_il", "israel", "case_law"),
    COLLECTION_COMMENTARY_GLOBAL: ("commentary_global", "international", "commentary"),
}


def _foundation_records_by_collection() -> dict[str, list[dict[str, Any]]]:
    records: dict[str, list[dict[str, Any]]] = {}
    records.update({collection: list(items) for collection, items in NATIONAL_RECORDS.items()})
    records.update({collection: list(items) for collection, items in STATUTE_RECORDS.items()})
    records.update({collection: list(items) for collection, items in CASE_RECORDS.items()})
    records[COLLECTION_INTL_TREATIES] = list(CORE_FALLBACK_RECORDS.get(COLLECTION_INTL_TREATIES, []))
    records[COLLECTION_COMMENTARY_GLOBAL] = list(COMMENTARY_RECORDS)
    return records


def write_foundation_corpus() -> dict[str, Any]:
    per_collection = _foundation_records_by_collection()
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "files": [],
        "total_records": 0,
    }
    for collection, (directory_name, _, _) in DIRECTORY_SPECS.items():
        directory = CORPUS_DIR / directory_name
        directory.mkdir(parents=True, exist_ok=True)
        for old in directory.glob("omnilegal_foundation*.jsonl"):
            old.unlink()
        records = per_collection.get(collection, [])
        path = directory / _FOUNDATION_FILENAME
        with path.open("w", encoding="utf-8", newline="\n") as fh:
            for record in records:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        readme = directory / "_README.txt"
        readme.write_text(
            f"OmniLegal local corpus slot for {collection}.\n"
            f"Foundation file: {_FOUNDATION_FILENAME}\n"
            "Add jurisdiction-specific PDFs, TXT, MD, or JSONL files here and rerun the knowledge-base build.\n",
            encoding="utf-8",
        )
        manifest["files"].append({"collection": collection, "path": str(path), "records": len(records)})
        manifest["total_records"] += len(records)
    return manifest


def _write_artifact(payload: dict[str, Any], name: str) -> Path:
    out_dir = DATA_DIR / "global_rebuild"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}_{name}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    latest = out_dir / f"latest_{name}.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _upsert_lexical_only(collection: str, chunks: list[dict[str, Any]], *, batch_size: int) -> int:
    """Upsert payloads with zero vectors for fast lexical-only recovery."""
    return upsert_chunks_lexical_only(collection, chunks, batch_size=batch_size)


def _upsert_grouped(
    chunks: list[dict[str, Any]],
    *,
    default_collection: str,
    batch_size: int,
    lexical_only: bool = False,
) -> dict[str, int]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        collection = str((chunk.get("metadata") or {}).get("collection") or default_collection)
        grouped[collection].append(chunk)
    result: dict[str, int] = {}
    for collection, collection_chunks in grouped.items():
        if lexical_only:
            inserted = _upsert_lexical_only(collection, collection_chunks, batch_size=batch_size)
        else:
            inserted = upsert_chunks(collection, collection_chunks, batch_size=batch_size)
        result[collection] = result.get(collection, 0) + inserted
    return result


def _merge_counts(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    merged = dict(left)
    for key, value in right.items():
        merged[key] = merged.get(key, 0) + int(value or 0)
    return merged


def _ingest_directory_collection(
    collection: str,
    *,
    batch_size: int,
    lexical_only: bool = False,
    contextual: bool = False,
) -> dict[str, int]:
    directory_name, jurisdiction, doc_type = DIRECTORY_SPECS[collection]
    chunks = _ingest_directory_slot(
        CORPUS_DIR / directory_name,
        collection=collection,
        jurisdiction=jurisdiction,
        doc_type=doc_type,
        add_context=contextual,
    )
    return _upsert_grouped(chunks, default_collection=collection, batch_size=batch_size, lexical_only=lexical_only)


def _chunks_from_records(collection: str, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        metadata = {key: value for key, value in record.items() if key != "text"}
        metadata["collection"] = collection
        metadata["chunk_index"] = idx
        chunks.append({
            "raw_text": record.get("text", ""),
            "text": record.get("text", ""),
            "index_text": record.get("text", ""),
            "metadata": metadata,
        })
    return chunks


def _reference_dataset_collection(source_id: str) -> str:
    return (
        COLLECTION_REFERENCE_DATASET_EU
        if source_id in _REFERENCE_DATASET_EU_SOURCES
        else COLLECTION_REFERENCE_DATASET_GLOBAL
    )


def _reference_dataset_chunks(*, sample_limit_per_source: int = 50) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    sources_seen: dict[str, int] = {}
    records_seen = 0

    for record in iter_reference_dataset_records(sample_limit_per_source=sample_limit_per_source):
        records_seen += 1
        collection = _reference_dataset_collection(record.source_repo)
        sources_seen[record.source_repo] = sources_seen.get(record.source_repo, 0) + 1
        text_parts = [f"Title: {record.title}", record.text]
        if record.summary:
            text_parts.append(f"Summary: {record.summary}")
        if record.labels:
            text_parts.append(f"Labels: {record.labels}")
        if record.question:
            text_parts.append(f"Question: {record.question}")
        if record.answer:
            text_parts.append(f"Answer: {record.answer}")
        text = "\n\n".join(part for part in text_parts if part).strip()
        if not text:
            continue

        metadata_extra = {
            "record_id": record.id,
            "source_repo": record.source_repo,
            "source_path": record.source_path,
            "dataset_title": (record.extra_metadata or {}).get("dataset_title"),
            "task_family": record.task_family,
            "source_document_type": record.document_type,
            "dataset_split": record.split,
            "labels": record.labels,
            "summary": record.summary,
            "question": record.question,
            "answer": record.answer,
            "court_or_body": record.court,
            "date": record.date,
            "translation_status": "multilingual_reference" if record.language == "multi" else "reference_dataset",
            "authority_tier": "reference_dataset",
            "citation": record.title or record.source_name or record.source_repo,
            "source_version": record.date or record.split or "reference",
            "version_date": record.date or record.split or "reference",
        }
        chunks.extend(
            _chunk_plain_text(
                text,
                collection=collection,
                source_name=record.title or record.source_name or record.source_repo,
                jurisdiction=record.jurisdiction or "mixed",
                doc_type="reference_dataset",
                add_context=False,
                private_public="public",
                license_note=record.license_note or "reference dataset; not controlling legal authority",
                metadata_extra=metadata_extra,
            )
        )

    manifest = {
        "sample_limit_per_source": sample_limit_per_source,
        "records": records_seen,
        "sources": sources_seen,
        "chunks": len(chunks),
    }
    return chunks, manifest


def _ingest_reference_datasets(*, batch_size: int, lexical_only: bool = False) -> dict[str, Any]:
    chunks, manifest = _reference_dataset_chunks()
    counts = _upsert_grouped(
        chunks,
        default_collection=COLLECTION_REFERENCE_DATASET_GLOBAL,
        batch_size=batch_size,
        lexical_only=lexical_only,
    )
    manifest["upserted_by_collection"] = counts
    return manifest


def _stream_case_jsonl(*, case_limit: int, batch_size: int, lexical_only: bool = False) -> dict[str, Any]:
    if not CASE_LAW_JSONL or not Path(CASE_LAW_JSONL).exists():
        return {"path": str(CASE_LAW_JSONL), "cases": 0, "chunks": 0, "upserted_by_collection": {}, "missing": True}

    buffers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    upserted: dict[str, int] = {}
    cases = 0
    chunks = 0

    def flush(collection: str | None = None) -> None:
        targets = [collection] if collection else list(buffers)
        for target in targets:
            batch = buffers.get(target, [])
            if not batch:
                continue
            if lexical_only:
                inserted = _upsert_lexical_only(target, batch, batch_size=batch_size)
            else:
                inserted = upsert_chunks(target, batch, batch_size=batch_size)
            upserted[target] = upserted.get(target, 0) + inserted
            buffers[target] = []

    with Path(CASE_LAW_JSONL).open(encoding="utf-8") as fh:
        for line in fh:
            if case_limit > 0 and cases >= case_limit:
                break
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError:
                continue
            case_chunks = _chunk_case(case, add_context=False)
            if not case_chunks:
                continue
            cases += 1
            chunks += len(case_chunks)
            for chunk in case_chunks:
                collection = str((chunk.get("metadata") or {}).get("collection") or COLLECTION_CASE_LAW_US)
                buffers[collection].append(chunk)
                if len(buffers[collection]) >= batch_size:
                    flush(collection)
            if cases % 250 == 0:
                print(f"  streamed {cases} local case records -> {chunks} chunks")

    flush()
    return {
        "path": str(CASE_LAW_JSONL),
        "case_limit": case_limit,
        "cases": cases,
        "chunks": chunks,
        "upserted_by_collection": upserted,
        "missing": False,
    }


def build_and_ingest(
    *,
    recreate: bool,
    batch_size: int,
    case_limit: int,
    skip_core_pdfs: bool,
    skip_full_case_jsonl: bool,
    skip_source_catalog: bool,
    lexical_only: bool,
    contextual: bool = False,
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recreate": recreate,
        "batch_size": batch_size,
        "case_limit": case_limit,
        "skip_core_pdfs": skip_core_pdfs,
        "skip_full_case_jsonl": skip_full_case_jsonl,
        "skip_source_catalog": skip_source_catalog,
        "lexical_only": lexical_only,
        "contextual": contextual,
        "upserted_by_collection": {},
        "events": [],
    }
    manifest["foundation_corpus"] = write_foundation_corpus()

    for collection in ALL_COLLECTIONS:
        create_collection(collection, recreate=recreate)
        manifest["events"].append({"collection": collection, "recreated": recreate})

    if not skip_core_pdfs:
        for collection in (COLLECTION_INTL_TREATIES, COLLECTION_NATIONAL_IN, COLLECTION_SHAW_PRIVATE):
            print(f"Ingesting core corpus collection {collection}...", flush=True)
            chunks = ingest_collection(collection, add_context=contextual)
            counts = _upsert_grouped(chunks, default_collection=collection, batch_size=batch_size, lexical_only=lexical_only)
            manifest["upserted_by_collection"] = _merge_counts(manifest["upserted_by_collection"], counts)
    else:
        for collection, records in CORE_FALLBACK_RECORDS.items():
            print(f"Ingesting foundation fallback collection {collection}...", flush=True)
            chunks = _chunks_from_records(collection, records)
            counts = _upsert_grouped(chunks, default_collection=collection, batch_size=batch_size, lexical_only=lexical_only)
            manifest["upserted_by_collection"] = _merge_counts(manifest["upserted_by_collection"], counts)

    directory_exclusions = set() if skip_core_pdfs else {COLLECTION_NATIONAL_IN}
    directory_collections = [
        collection
        for collection in DIRECTORY_SPECS
        if collection not in directory_exclusions
    ]
    for collection in directory_collections:
        print(f"Ingesting directory corpus collection {collection}...", flush=True)
        counts = _ingest_directory_collection(
            collection,
            batch_size=batch_size,
            lexical_only=lexical_only,
            contextual=contextual,
        )
        manifest["upserted_by_collection"] = _merge_counts(manifest["upserted_by_collection"], counts)

    if not skip_full_case_jsonl:
        manifest["full_case_jsonl"] = _stream_case_jsonl(
            case_limit=case_limit,
            batch_size=batch_size,
            lexical_only=lexical_only,
        )
        manifest["upserted_by_collection"] = _merge_counts(
            manifest["upserted_by_collection"],
            manifest["full_case_jsonl"].get("upserted_by_collection", {}),
        )

    if not skip_source_catalog:
        remote = run_remote_ingestion(
            download=True,
            ingest=True,
            mode="licensed",
            max_items_per_source=_TARGETED_REMOTE_MAX_ITEMS_PER_SOURCE,
            adapter_filter=_TARGETED_REMOTE_ADAPTERS,
            quality_gate="strict",
            update_mode="overwrite_same_source_version",
            dedupe="strict",
            importance_ranking=True,
            lexical_only=lexical_only,
        )
        manifest["source_catalog_ingestion"] = remote
        manifest["upserted_by_collection"] = _merge_counts(
            manifest["upserted_by_collection"],
            remote.get("upserted_by_collection", {}),
        )

    reference_dataset_ingestion = _ingest_reference_datasets(
        batch_size=batch_size,
        lexical_only=lexical_only,
    )
    manifest["reference_dataset_ingestion"] = reference_dataset_ingestion
    manifest["upserted_by_collection"] = _merge_counts(
        manifest["upserted_by_collection"],
        reference_dataset_ingestion.get("upserted_by_collection", {}),
    )

    manifest["final_counts"] = {collection: collection_point_count(collection) for collection in ALL_COLLECTIONS}
    path = _write_artifact(manifest, "legal_knowledge_base_build")
    manifest["artifact_path"] = str(path)
    return manifest


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Build and ingest the OmniLegal jurisdiction knowledge base")
    parser.add_argument("--recreate", action="store_true", help="Drop and recreate all configured Qdrant collections before ingesting")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--case-limit", type=int, default=0, help="Number of local JSONL cases to stream; 0 means all")
    parser.add_argument("--skip-core-pdfs", action="store_true", help="Skip shipped PDFs and ingest only directory/JSONL/source-catalog material")
    parser.add_argument("--skip-full-case-jsonl", action="store_true")
    parser.add_argument("--skip-source-catalog", action="store_true")
    parser.add_argument("--lexical-only", action="store_true", help="Upsert zero-vector payloads for fast lexical retrieval without loading embedding models")
    parser.add_argument("--contextual", action="store_true", help="Add retrieval-only contextual summaries to index_text while preserving raw_text")
    args = parser.parse_args()

    result = build_and_ingest(
        recreate=args.recreate,
        batch_size=args.batch_size,
        case_limit=args.case_limit,
        skip_core_pdfs=args.skip_core_pdfs,
        skip_full_case_jsonl=args.skip_full_case_jsonl,
        skip_source_catalog=args.skip_source_catalog,
        lexical_only=args.lexical_only,
        contextual=args.contextual,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
