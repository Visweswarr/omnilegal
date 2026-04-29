"""Curated seed corpus — real treaty / statute / case text for verification-first RAG.

Everything here is short excerpts or paraphrases drawn from public-domain legal
texts (UN treaties, constitutions, public-domain US/UK/IN judgments) that are
sufficient to answer the kinds of questions OmniLegal is designed for:

  - International vs local law conflict
  - Tourist / travel safety
  - Case research (landmark)

This is a BOOTSTRAP corpus — it is intentionally compact but high-signal. Add
longer texts via `pipeline_v2.ingest_remote` adapters in a follow-up pass.
"""
from __future__ import annotations

SEED_DOCS: list[dict] = [
    # ── International treaties ─────────────────────────────────────────────
    {
        "source_id": "un_charter_art_2_4",
        "citation": "UN Charter, Article 2(4)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.un.org/en/about-us/un-charter/full-text",
        "text": (
            "All Members shall refrain in their international relations from the threat "
            "or use of force against the territorial integrity or political independence "
            "of any state, or in any other manner inconsistent with the Purposes of the "
            "United Nations. (UN Charter art. 2(4), 1945)"
        ),
    },
    {
        "source_id": "un_charter_art_51",
        "citation": "UN Charter, Article 51",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.un.org/en/about-us/un-charter/full-text",
        "text": (
            "Nothing in the present Charter shall impair the inherent right of individual "
            "or collective self-defence if an armed attack occurs against a Member of the "
            "United Nations, until the Security Council has taken measures necessary to "
            "maintain international peace and security. (UN Charter art. 51, 1945)"
        ),
    },
    {
        "source_id": "un_charter_art_103",
        "citation": "UN Charter, Article 103",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.un.org/en/about-us/un-charter/full-text",
        "text": (
            "In the event of a conflict between the obligations of the Members of the "
            "United Nations under the present Charter and their obligations under any "
            "other international agreement, their obligations under the present Charter "
            "shall prevail. (UN Charter art. 103, 1945)"
        ),
    },
    {
        "source_id": "vclt_art_26",
        "citation": "Vienna Convention on the Law of Treaties, Article 26 (pacta sunt servanda)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf",
        "text": (
            "Every treaty in force is binding upon the parties to it and must be performed "
            "by them in good faith. (Vienna Convention on the Law of Treaties, 1969, art. 26)"
        ),
    },
    {
        "source_id": "vclt_art_27",
        "citation": "Vienna Convention on the Law of Treaties, Article 27",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf",
        "text": (
            "A party may not invoke the provisions of its internal law as justification "
            "for its failure to perform a treaty. (VCLT 1969, art. 27). Read together with "
            "art. 46, internal law only matters where consent to the treaty was manifestly "
            "violated against a rule of fundamental importance."
        ),
    },
    {
        "source_id": "vclt_art_53",
        "citation": "Vienna Convention on the Law of Treaties, Article 53 (jus cogens)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf",
        "text": (
            "A treaty is void if, at the time of its conclusion, it conflicts with a "
            "peremptory norm of general international law. A peremptory norm is one "
            "accepted and recognised by the international community of States as a whole "
            "as a norm from which no derogation is permitted. (VCLT 1969, art. 53)"
        ),
    },
    {
        "source_id": "iccpr_art_9",
        "citation": "ICCPR, Article 9 (liberty and security of person)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-civil-and-political-rights",
        "text": (
            "Everyone has the right to liberty and security of person. No one shall be "
            "subjected to arbitrary arrest or detention. Anyone arrested shall be informed, "
            "at the time of arrest, of the reasons for arrest and shall be promptly informed "
            "of any charges. (ICCPR 1966, art. 9)"
        ),
    },
    {
        "source_id": "iccpr_art_14",
        "citation": "ICCPR, Article 14 (fair trial)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-civil-and-political-rights",
        "text": (
            "All persons shall be equal before the courts. Everyone charged with a criminal "
            "offence has the right to be presumed innocent, to be informed promptly of the "
            "charge in a language they understand, to have adequate time and facilities to "
            "prepare a defence, and to have the free assistance of an interpreter if needed. "
            "(ICCPR 1966, art. 14)"
        ),
    },
    {
        "source_id": "vccr_art_36",
        "citation": "Vienna Convention on Consular Relations, Article 36",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://legal.un.org/ilc/texts/instruments/english/conventions/9_2_1963.pdf",
        "text": (
            "If a foreign national is arrested or detained, the competent authorities of the "
            "receiving State shall, without delay, inform the consular post of the sending "
            "State if the person so requests. The detained person must be informed of this "
            "right without delay. Consular officers have the right to visit, converse with, "
            "and arrange legal representation for their nationals in detention. (VCCR 1963, "
            "art. 36)"
        ),
    },
    {
        "source_id": "vcdr_art_29_31",
        "citation": "Vienna Convention on Diplomatic Relations, Articles 29 & 31",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://legal.un.org/ilc/texts/instruments/english/conventions/9_1_1961.pdf",
        "text": (
            "The person of a diplomatic agent shall be inviolable. He shall not be liable to "
            "any form of arrest or detention. (art. 29). A diplomatic agent shall enjoy "
            "immunity from the criminal jurisdiction of the receiving State, and from its "
            "civil and administrative jurisdiction, with limited exceptions relating to "
            "private real property, succession, and private commercial activity. (VCDR 1961, "
            "art. 31)"
        ),
    },
    {
        "source_id": "vienna_road_traffic_art_41",
        "citation": "Vienna Convention on Road Traffic 1968, Article 41 (driver licensing)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://treaties.un.org/pages/ViewDetailsIII.aspx?src=TREATY&mtdsg_no=XI-B-19&chapter=11",
        "text": (
            "Contracting Parties shall recognize any domestic driving permit drawn up in "
            "their national language or in one of their national languages, or, if not "
            "drawn up in such a language, accompanied by a certified translation; any "
            "domestic driving permit conforming to the provisions of Annex 6; and any "
            "international driving permit conforming to the provisions of Annex 7, as valid "
            "for driving in their territory a vehicle coming within the categories covered "
            "by the permit, provided that the permit is still valid. (Vienna 1968, art. 41)"
        ),
    },
    {
        "source_id": "refugee_convention_art_33",
        "citation": "1951 Refugee Convention, Article 33 (non-refoulement)",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.unhcr.org/3b66c2aa10",
        "text": (
            "No Contracting State shall expel or return ('refouler') a refugee in any manner "
            "whatsoever to the frontiers of territories where his life or freedom would be "
            "threatened on account of his race, religion, nationality, membership of a "
            "particular social group or political opinion. (Refugee Convention 1951, art. 33)"
        ),
    },
    {
        "source_id": "udhr_art_13",
        "citation": "Universal Declaration of Human Rights, Article 13",
        "jurisdiction": "INTL",
        "doc_type": "treaty",
        "url": "https://www.un.org/en/about-us/universal-declaration-of-human-rights",
        "text": (
            "Everyone has the right to freedom of movement and residence within the borders "
            "of each State. Everyone has the right to leave any country, including his own, "
            "and to return to his country. (UDHR 1948, art. 13)"
        ),
    },

    # ── United States ──────────────────────────────────────────────────────
    {
        "source_id": "us_const_supremacy",
        "citation": "U.S. Constitution, Article VI, clause 2 (Supremacy Clause)",
        "jurisdiction": "US",
        "doc_type": "statute",
        "url": "https://constitution.congress.gov/constitution/article-6/",
        "text": (
            "This Constitution, and the Laws of the United States which shall be made in "
            "Pursuance thereof; and all Treaties made, or which shall be made, under the "
            "Authority of the United States, shall be the supreme Law of the Land; and the "
            "Judges in every State shall be bound thereby, any Thing in the Constitution or "
            "Laws of any State to the Contrary notwithstanding. (U.S. Const. art. VI, cl. 2)"
        ),
    },
    {
        "source_id": "us_const_1a",
        "citation": "U.S. Constitution, First Amendment",
        "jurisdiction": "US",
        "doc_type": "statute",
        "url": "https://constitution.congress.gov/constitution/amendment-1/",
        "text": (
            "Congress shall make no law respecting an establishment of religion, or "
            "prohibiting the free exercise thereof; or abridging the freedom of speech, or "
            "of the press; or the right of the people peaceably to assemble, and to petition "
            "the Government for a redress of grievances. (U.S. Const. amend. I)"
        ),
    },
    {
        "source_id": "us_const_4a",
        "citation": "U.S. Constitution, Fourth Amendment",
        "jurisdiction": "US",
        "doc_type": "statute",
        "url": "https://constitution.congress.gov/constitution/amendment-4/",
        "text": (
            "The right of the people to be secure in their persons, houses, papers, and "
            "effects, against unreasonable searches and seizures, shall not be violated, and "
            "no Warrants shall issue, but upon probable cause, supported by Oath or "
            "affirmation, and particularly describing the place to be searched, and the "
            "persons or things to be seized. (U.S. Const. amend. IV)"
        ),
    },
    {
        "source_id": "miranda_1966",
        "citation": "Miranda v. Arizona, 384 U.S. 436 (1966)",
        "jurisdiction": "US",
        "doc_type": "case_law",
        "url": "https://supreme.justia.com/cases/federal/us/384/436/",
        "text": (
            "Miranda v. Arizona held that prior to any custodial interrogation, the person "
            "must be warned that: they have the right to remain silent; anything said can "
            "and will be used against them in court; they have the right to consult an "
            "attorney and to have an attorney present during interrogation; and if they "
            "cannot afford an attorney one will be appointed. Absent such warnings, "
            "statements obtained during custodial interrogation are inadmissible. "
            "(Miranda v. Arizona, 384 U.S. 436 (1966))"
        ),
    },
    {
        "source_id": "medellin_2008",
        "citation": "Medellín v. Texas, 552 U.S. 491 (2008)",
        "jurisdiction": "US",
        "doc_type": "case_law",
        "url": "https://supreme.justia.com/cases/federal/us/552/491/",
        "text": (
            "Medellín v. Texas held that an ICJ judgment (Avena) was not directly "
            "enforceable domestic federal law absent congressional implementing legislation "
            "or a self-executing treaty provision. The VCCR is binding on the United States "
            "at the international level, but its enforcement in U.S. courts turns on whether "
            "the treaty is self-executing. (Medellín v. Texas, 552 U.S. 491 (2008))"
        ),
    },
    {
        "source_id": "foley_square_reid_1957",
        "citation": "Reid v. Covert, 354 U.S. 1 (1957)",
        "jurisdiction": "US",
        "doc_type": "case_law",
        "url": "https://supreme.justia.com/cases/federal/us/354/1/",
        "text": (
            "Reid v. Covert held that no treaty or executive agreement can confer on the "
            "government power which is free from the constraints of the U.S. Constitution. "
            "A treaty cannot authorize what the Constitution forbids. "
            "(Reid v. Covert, 354 U.S. 1 (1957))"
        ),
    },

    # ── United Kingdom ────────────────────────────────────────────────────
    {
        "source_id": "uk_hra_s2",
        "citation": "Human Rights Act 1998, Section 2",
        "jurisdiction": "UK",
        "doc_type": "statute",
        "url": "https://www.legislation.gov.uk/ukpga/1998/42/section/2",
        "text": (
            "A court or tribunal determining a question which has arisen in connection with "
            "a Convention right must take into account any judgment, decision, declaration or "
            "advisory opinion of the European Court of Human Rights. (UK Human Rights Act "
            "1998, s. 2)"
        ),
    },
    {
        "source_id": "uk_hra_s3",
        "citation": "Human Rights Act 1998, Section 3",
        "jurisdiction": "UK",
        "doc_type": "statute",
        "url": "https://www.legislation.gov.uk/ukpga/1998/42/section/3",
        "text": (
            "So far as it is possible to do so, primary legislation and subordinate "
            "legislation must be read and given effect in a way which is compatible with "
            "the Convention rights. (UK Human Rights Act 1998, s. 3(1))"
        ),
    },
    {
        "source_id": "uk_pace_s58",
        "citation": "Police and Criminal Evidence Act 1984, Section 58",
        "jurisdiction": "UK",
        "doc_type": "statute",
        "url": "https://www.legislation.gov.uk/ukpga/1984/60/section/58",
        "text": (
            "A person arrested and held in custody in a police station shall be entitled, if "
            "he so requests, to consult a solicitor privately at any time. The right may only "
            "be delayed in narrowly defined circumstances where a serious arrestable offence "
            "is involved. (UK PACE 1984, s. 58)"
        ),
    },

    # ── European Union ───────────────────────────────────────────────────
    {
        "source_id": "eu_costa_enel_1964",
        "citation": "Costa v. ENEL, Case 6/64, [1964] ECR 585",
        "jurisdiction": "EU",
        "doc_type": "case_law",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A61964CJ0006",
        "text": (
            "Costa v. ENEL established the doctrine of primacy of EU law: the integration "
            "into the laws of each Member State of provisions deriving from the Community "
            "makes it impossible for States, as a corollary, to accord precedence to a "
            "unilateral and subsequent measure over a legal order accepted by them. EU law "
            "cannot be overridden by domestic legal provisions. (Costa v. ENEL, 6/64, 1964)"
        ),
    },
    {
        "source_id": "eu_charter_art_47",
        "citation": "EU Charter of Fundamental Rights, Article 47",
        "jurisdiction": "EU",
        "doc_type": "statute",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A12012P%2FTXT",
        "text": (
            "Everyone whose rights and freedoms guaranteed by the law of the Union are "
            "violated has the right to an effective remedy before a tribunal. Everyone is "
            "entitled to a fair and public hearing within a reasonable time by an "
            "independent and impartial tribunal previously established by law. (EU Charter "
            "of Fundamental Rights, art. 47)"
        ),
    },
    {
        "source_id": "gdpr_art_5",
        "citation": "GDPR, Article 5 (principles relating to processing)",
        "jurisdiction": "EU",
        "doc_type": "statute",
        "url": "https://eur-lex.europa.eu/eli/reg/2016/679/oj",
        "text": (
            "Personal data shall be processed lawfully, fairly and in a transparent manner; "
            "collected for specified, explicit and legitimate purposes (purpose limitation); "
            "adequate, relevant and limited to what is necessary (data minimisation); "
            "accurate; kept no longer than necessary; and processed in a secure manner. "
            "(Regulation (EU) 2016/679, art. 5)"
        ),
    },

    # ── India ────────────────────────────────────────────────────────────
    {
        "source_id": "in_const_art_14",
        "citation": "Constitution of India, Article 14",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/15240",
        "text": (
            "The State shall not deny to any person equality before the law or the equal "
            "protection of the laws within the territory of India. (Constitution of India, "
            "art. 14)"
        ),
    },
    {
        "source_id": "in_const_art_19",
        "citation": "Constitution of India, Article 19",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/15240",
        "text": (
            "All citizens shall have the right to freedom of speech and expression; to "
            "assemble peaceably and without arms; to form associations or unions; to move "
            "freely throughout the territory of India; to reside and settle in any part of "
            "India; and to practise any profession. The State may impose reasonable "
            "restrictions in the interests of sovereignty, public order, decency, morality, "
            "contempt of court, defamation, or incitement to an offence. (Constitution of "
            "India, art. 19)"
        ),
    },
    {
        "source_id": "in_const_art_21",
        "citation": "Constitution of India, Article 21",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/15240",
        "text": (
            "No person shall be deprived of his life or personal liberty except according "
            "to procedure established by law. (Constitution of India, art. 21) — extended "
            "by Maneka Gandhi v. Union of India (1978) to require that the procedure be "
            "just, fair, and reasonable."
        ),
    },
    {
        "source_id": "in_const_art_51",
        "citation": "Constitution of India, Article 51 (DPSP on international law)",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/15240",
        "text": (
            "The State shall endeavour to promote international peace and security; maintain "
            "just and honourable relations between nations; foster respect for international "
            "law and treaty obligations in the dealings of organised peoples with one "
            "another; and encourage settlement of international disputes by arbitration. "
            "(Constitution of India, art. 51)"
        ),
    },
    {
        "source_id": "in_bns_s103",
        "citation": "Bharatiya Nyaya Sanhita 2023, Section 103 (murder)",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/20062",
        "text": (
            "Whoever commits murder shall be punished with death or imprisonment for life, "
            "and shall also be liable to fine. Where an act is done by five or more persons "
            "acting in concert on the ground of race, caste, sex, place of birth, language, "
            "etc., each of them shall be punished with death or imprisonment for life. "
            "(Bharatiya Nyaya Sanhita, 2023, s. 103)"
        ),
    },
    {
        "source_id": "in_mv_act_s3",
        "citation": "Motor Vehicles Act 1988, Section 3 (driving licence)",
        "jurisdiction": "IN",
        "doc_type": "statute",
        "url": "https://www.indiacode.nic.in/handle/123456789/1798",
        "text": (
            "No person shall drive a motor vehicle in any public place unless he holds an "
            "effective driving licence issued to him authorising him to drive the vehicle. "
            "A person holding a driving licence issued by a Contracting Party to the Vienna "
            "Convention on Road Traffic 1968 may drive in India as a foreign national "
            "subject to the conditions in Rule 14 of the Central Motor Vehicles Rules. "
            "(Motor Vehicles Act 1988, s. 3 read with CMVR r. 14)"
        ),
    },
    {
        "source_id": "vishaka_1997",
        "citation": "Vishaka v. State of Rajasthan (1997) 6 SCC 241",
        "jurisdiction": "IN",
        "doc_type": "case_law",
        "url": "https://main.sci.gov.in/judgment/judis/14005.pdf",
        "text": (
            "In the absence of domestic law on sexual harassment, the Supreme Court held "
            "that international conventions ratified by India — specifically CEDAW — can be "
            "read into Articles 14, 15, 19 and 21 of the Constitution. International "
            "conventions and norms are to be read into fundamental rights where there is no "
            "inconsistency with domestic law and there is a void. (Vishaka v. State of "
            "Rajasthan (1997) 6 SCC 241)"
        ),
    },
    {
        "source_id": "gramophone_1984",
        "citation": "Gramophone Co. of India v. Birendra Bahadur Pandey (1984) 2 SCC 534",
        "jurisdiction": "IN",
        "doc_type": "case_law",
        "url": "https://main.sci.gov.in/",
        "text": (
            "The doctrine of incorporation was restated: rules of international law are "
            "incorporated into national law and considered to be part of the national law "
            "unless they are in conflict with an Act of Parliament. In case of conflict, "
            "the national law prevails for Indian courts. (Gramophone Co. v. Birendra "
            "Bahadur Pandey (1984) 2 SCC 534)"
        ),
    },
    {
        "source_id": "maneka_gandhi_1978",
        "citation": "Maneka Gandhi v. Union of India, AIR 1978 SC 597",
        "jurisdiction": "IN",
        "doc_type": "case_law",
        "url": "https://main.sci.gov.in/",
        "text": (
            "Maneka Gandhi extended the reach of Article 21 of the Constitution to require "
            "any procedure depriving a person of life or personal liberty to be just, fair, "
            "and reasonable, not arbitrary, fanciful or oppressive. The right to travel "
            "abroad is a facet of personal liberty. (Maneka Gandhi v. Union of India, AIR "
            "1978 SC 597)"
        ),
    },

    # ── Russia ────────────────────────────────────────────────────────────
    {
        "source_id": "ru_const_art_15_4",
        "citation": "Constitution of the Russian Federation, Article 15(4)",
        "jurisdiction": "RU",
        "doc_type": "statute",
        "url": "http://www.constitution.ru/en/10003000-03.htm",
        "text": (
            "The universally recognised principles and norms of international law and the "
            "international treaties of the Russian Federation shall be a component part of "
            "its legal system. If an international treaty of the Russian Federation "
            "establishes rules other than those envisaged by law, the rules of the "
            "international treaty shall apply — subject, after the 2020 amendments, to the "
            "Constitutional Court's confirmation that the treaty provision is not contrary "
            "to the Constitution. (Constitution RF, art. 15(4))"
        ),
    },
    {
        "source_id": "ru_admin_code_art_12_7",
        "citation": "Code of Administrative Offences of the Russian Federation, Art. 12.7",
        "jurisdiction": "RU",
        "doc_type": "statute",
        "url": "http://www.consultant.ru/",
        "text": (
            "Driving a motor vehicle by a person who does not hold the right to drive (other "
            "than a learner) is punishable by an administrative fine of 5,000 to 15,000 "
            "roubles. Foreign driving permits are recognised only insofar as Russia is a "
            "party to the Vienna Convention on Road Traffic 1968; from 1 June 2021, foreign "
            "nationals working as professional drivers in Russia must obtain a Russian "
            "licence. (CoAO RF, art. 12.7)"
        ),
    },
    {
        "source_id": "ru_foreign_nationals_law",
        "citation": "Federal Law No. 115-FZ 'On the Legal Status of Foreign Citizens in the RF'",
        "jurisdiction": "RU",
        "doc_type": "statute",
        "url": "http://www.consultant.ru/document/cons_doc_LAW_37868/",
        "text": (
            "Foreign citizens in the Russian Federation shall enjoy the rights and bear the "
            "duties on an equal footing with citizens of the Russian Federation, except as "
            "provided by federal law. They are required to present a valid passport and a "
            "migration card and to register their place of stay with the migration "
            "authorities within the statutory period. (Federal Law 115-FZ, 25 July 2002)"
        ),
    },

    # ── Israel ───────────────────────────────────────────────────────────
    {
        "source_id": "il_basic_law_dignity",
        "citation": "Basic Law: Human Dignity and Liberty (Israel), 1992",
        "jurisdiction": "IL",
        "doc_type": "statute",
        "url": "https://main.knesset.gov.il/EN/activity/Documents/BasicLawsPDF/BasicLawLiberty.pdf",
        "text": (
            "There shall be no violation of the life, body or dignity of any person as such. "
            "There shall be no deprivation or restriction of the liberty of a person by "
            "imprisonment, arrest, extradition or otherwise. All persons are entitled to "
            "protection of their life, body and dignity. The rights under this Basic Law "
            "may be violated only by a law befitting the values of the State of Israel, "
            "enacted for a proper purpose, and to an extent no greater than required. "
            "(Basic Law: Human Dignity and Liberty, 1992, ss. 2, 4, 8)"
        ),
    },

    # ── Cross-border landmark international cases ────────────────────────
    {
        "source_id": "lagrand_2001",
        "citation": "LaGrand Case (Germany v. United States), ICJ, 2001",
        "jurisdiction": "INTL",
        "doc_type": "case_law",
        "url": "https://www.icj-cij.org/case/104",
        "text": (
            "The ICJ held that Article 36(1)(b) of the Vienna Convention on Consular "
            "Relations creates individual rights. The United States violated its obligations "
            "under the VCCR by failing to inform the LaGrand brothers of their right to "
            "consular notification without delay and by executing them before the ICJ could "
            "rule. (LaGrand, ICJ Rep. 2001 p. 466)"
        ),
    },
    {
        "source_id": "avena_2004",
        "citation": "Avena and Other Mexican Nationals (Mexico v. USA), ICJ, 2004",
        "jurisdiction": "INTL",
        "doc_type": "case_law",
        "url": "https://www.icj-cij.org/case/128",
        "text": (
            "The ICJ ordered the United States, by means of its own choosing, to provide "
            "review and reconsideration of the convictions and sentences of 51 Mexican "
            "nationals who had been denied consular notification under VCCR art. 36. The "
            "remedy must give full weight to the violation of the rights under the "
            "Convention. (Avena, ICJ Rep. 2004 p. 12)"
        ),
    },
    {
        "source_id": "barcelona_traction_1970",
        "citation": "Barcelona Traction (Belgium v. Spain), ICJ, 1970",
        "jurisdiction": "INTL",
        "doc_type": "case_law",
        "url": "https://www.icj-cij.org/case/50",
        "text": (
            "An essential distinction must be drawn between the obligations of a State "
            "towards the international community as a whole, and those arising vis-à-vis "
            "another State. By their very nature the former are the concern of all States. "
            "Such obligations erga omnes derive, in contemporary international law, from "
            "the outlawing of acts of aggression and of genocide, from the principles and "
            "rules concerning the basic rights of the human person, including protection "
            "from slavery and racial discrimination. (Barcelona Traction, ICJ Rep. 1970, "
            "paras. 33-34)"
        ),
    },
    {
        "source_id": "nicaragua_1986",
        "citation": "Military and Paramilitary Activities (Nicaragua v. USA), ICJ, 1986",
        "jurisdiction": "INTL",
        "doc_type": "case_law",
        "url": "https://www.icj-cij.org/case/70",
        "text": (
            "The Court reaffirmed that the prohibition on the use of force in Article 2(4) "
            "of the UN Charter is also a rule of customary international law. Self-defence "
            "under Article 51 requires an armed attack; 'assistance to rebels in the form of "
            "the provision of weapons or logistical or other support' does not in itself "
            "amount to an armed attack. (Nicaragua, ICJ Rep. 1986 p. 14)"
        ),
    },

    # ── Conflict-of-laws doctrines (commentary) ──────────────────────────
    {
        "source_id": "doctrine_monism_dualism",
        "citation": "Doctrines of Monism and Dualism (commentary)",
        "jurisdiction": "INTL",
        "doc_type": "commentary",
        "url": "",
        "text": (
            "Under monism, international law and domestic law form a single legal order; "
            "ratified treaties apply directly in domestic courts (examples: the Netherlands "
            "under art. 94 of its Constitution; France under art. 55). Under dualism, "
            "international and domestic law are separate systems; a treaty only binds "
            "domestic courts once it has been transformed into domestic legislation "
            "(examples: the United Kingdom, India's general approach, and the non-"
            "self-executing doctrine applied in the United States per Medellín v. Texas). "
            "Where a jus cogens norm (VCLT art. 53) is in play, no domestic rule can "
            "derogate from it."
        ),
    },
    {
        "source_id": "tourist_consular_checklist",
        "citation": "Traveller Consular Rights Checklist (derived from VCCR art. 36 + ICCPR)",
        "jurisdiction": "INTL",
        "doc_type": "commentary",
        "url": "",
        "text": (
            "A foreign national who is arrested or detained abroad has the following "
            "minimum rights under widely ratified treaties: (1) to be informed without "
            "delay that they may ask the local authorities to contact their consulate "
            "(VCCR art. 36); (2) to be informed of the reasons for arrest and any charges "
            "in a language they understand (ICCPR art. 9 and 14); (3) to have a lawyer of "
            "their choice and, if required, a free interpreter (ICCPR art. 14); (4) not to "
            "be subjected to arbitrary detention (ICCPR art. 9). Practical steps: ask for a "
            "lawyer; ask the officer to notify your consulate; do not sign any document in "
            "a language you do not fully understand."
        ),
    },
]


def get_seed_docs() -> list[dict]:
    # Clone to avoid accidental caller mutation.
    return [dict(d) for d in SEED_DOCS]
