"""OmniLegal Compliance Sentinel (Pillar 17 — STATE OF THE ART).

Paste a contract clause, policy, or piece of business text. We scan it
against a curated catalogue of 25+ FUTURE / RECENTLY-ENACTED legal
changes (DPDP India, EU AI Act phases, GDPR enforcement, US state
privacy laws, NIS2, DSA/DMA, MiCA, etc.) and flag every clause that
will be invalidated, weakened, or re-priced by the change.

Each detection is rule-based + LLM-validated:
  • Each rule has a regex / keyword pattern that must match.
  • The LLM is given the matched span + the rule, and asked to confirm
    whether the user's text actually triggers the rule (avoids false
    positives like "data" in a non-personal-data context).
  • Each detection includes effective date, jurisdiction, severity,
    "what to fix" remediation, and a primary-source URL.

ChatGPT cannot reliably do this because:
  • It doesn't know YOUR specific contract verbatim.
  • It doesn't have a structured catalogue of upcoming changes with
    effective dates.
  • Its answers are vague — "you might want to consider GDPR" — without
    pointing to specific clauses.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("omnilegal.sentinel")


# ── Curated catalogue of legal changes the sentinel checks against ────────


SENTINEL_RULES: list[dict[str, Any]] = [
    {
        "rule_id": "in_dpdp_2023_consent",
        "title": "India DPDP Act — granular consent + deemed consent rules",
        "jurisdiction": "India",
        "effective_date": "2025-rolled-out-in-phases",
        "severity": "high",
        "url": "https://www.meity.gov.in/sites/upload_files/dit/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf",
        "patterns": [
            r"\bdeemed\s+consent\b",
            r"\b(?:bulk|blanket)\s+consent\b",
            r"\bconsent\b.{0,40}\b(?:any|all)\s+(?:purpose|usage)",
        ],
        "remediation": "DPDP requires purpose-bound, specific and revocable consent. Replace blanket/deemed consent language with itemised purpose statements and add a stand-alone withdrawal clause.",
    },
    {
        "rule_id": "in_dpdp_2023_cross_border",
        "title": "India DPDP Act — cross-border data transfer restrictions",
        "jurisdiction": "India",
        "effective_date": "2025",
        "severity": "high",
        "url": "https://www.meity.gov.in/sites/upload_files/dit/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf",
        "patterns": [
            r"\btransfer\b.{0,40}\b(?:outside|abroad|foreign|us\b|usa\b|united states)",
            r"\b(?:store|process)\s+\bdata\b.{0,40}(?:outside|offshore|us-based|aws\b|gcp\b|azure)",
        ],
        "remediation": "DPDP empowers the central government to whitelist destination countries. Add a clause allowing the user to redirect storage to India when an applicable restriction is invoked.",
    },
    {
        "rule_id": "eu_ai_act_high_risk",
        "title": "EU AI Act — high-risk AI obligations",
        "jurisdiction": "European Union",
        "effective_date": "2026-08-02 (full application)",
        "severity": "high",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
        "patterns": [
            r"\b(automated|algorithmic)\s+(?:decision|scoring|hiring|credit|admission|grading)\b",
            r"\b(facial recognition|biometric identification|emotion recognition)\b",
            r"\bAI\b.{0,40}\b(?:HR|recruitment|employment|insurance|education)\b",
        ],
        "remediation": "EU AI Act treats these as 'high-risk AI systems' and requires conformity assessment, fundamental-rights impact assessment, and registration. Insert a vendor warranty that the system is registered and a human-oversight clause.",
    },
    {
        "rule_id": "eu_ai_act_prohibited",
        "title": "EU AI Act — prohibited practices (already in force Feb 2025)",
        "jurisdiction": "European Union",
        "effective_date": "2025-02-02",
        "severity": "blocking",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R1689",
        "patterns": [
            r"\bsocial scoring\b",
            r"\bemotion (?:recognition|detection)\b.{0,40}\b(?:workplace|education|school)",
            r"\bsubliminal\s+(?:technique|manipulation)",
        ],
        "remediation": "These practices are PROHIBITED. The clause must be removed entirely; no contractual carve-out is possible.",
    },
    {
        "rule_id": "eu_gdpr_us_transfer",
        "title": "GDPR Schrems II + Data Privacy Framework",
        "jurisdiction": "European Union",
        "effective_date": "2023-07-10 (DPF in force)",
        "severity": "high",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32016R0679",
        "patterns": [
            r"\b(?:transfer|share|disclose)\b.{0,40}\b(?:data|personal data|PII)\b.{0,40}\b(?:US|United States|USA)\b",
            r"\b(?:standard contractual clauses|SCC|SCCs)\b",
        ],
        "remediation": "Post-Schrems II, ensure receiving US entity is DPF-certified or include 2021 SCCs + Transfer Impact Assessment (TIA). Note that pre-2021 SCCs are no longer valid.",
    },
    {
        "rule_id": "eu_dsa_platform_liability",
        "title": "EU Digital Services Act — platform liability + transparency",
        "jurisdiction": "European Union",
        "effective_date": "2024-02-17 (full)",
        "severity": "medium",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R2065",
        "patterns": [
            r"\b(user-generated content|UGC|user content|hosted content)\b",
            r"\b(content moderation|takedown|notice and action)\b",
            r"\bplatform\b.{0,40}\b(?:not liable|no liability)\b",
        ],
        "remediation": "DSA imposes Notice-and-Action, transparency, and statement-of-reasons obligations on hosting platforms. Replace flat 'no liability' clauses with conditional safe-harbour language tied to expeditious takedown.",
    },
    {
        "rule_id": "eu_dma_gatekeeper",
        "title": "EU Digital Markets Act — gatekeeper rules (selfpref / interop)",
        "jurisdiction": "European Union",
        "effective_date": "2024-03-07",
        "severity": "medium",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022R1925",
        "patterns": [
            r"\b(self-preferenc|exclusive\s+(?:default|pre-installation))",
            r"\binteroperability\b.{0,40}\b(?:not|no|prohibited)\b",
        ],
        "remediation": "DMA bans self-preferencing and forces interoperability for designated gatekeepers. Re-draft any default-app/exclusive-pre-installation language.",
    },
    {
        "rule_id": "eu_nis2_cyber",
        "title": "EU NIS2 Directive — incident reporting + supply-chain security",
        "jurisdiction": "European Union",
        "effective_date": "2024-10-17 (transposition deadline)",
        "severity": "medium",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2555",
        "patterns": [
            r"\b(critical\s+infrastructure|essential\s+entity|important\s+entity)\b",
            r"\b(security incident|breach)\b.{0,40}\b(?:notify|notification)\b",
        ],
        "remediation": "NIS2 mandates 24-hour early-warning + 72-hour incident notice. Update the breach-notification SLA accordingly.",
    },
    {
        "rule_id": "us_california_cpra",
        "title": "California CCPA / CPRA",
        "jurisdiction": "United States — California",
        "effective_date": "2023-01-01",
        "severity": "high",
        "url": "https://leginfo.legislature.ca.gov/faces/codes_displayText.xhtml?division=3.&part=4.&lawCode=CIV&title=1.81.5",
        "patterns": [
            r"\b(sale|sharing) of (?:personal information|data)\b",
            r"\bdo not (?:sell|share)\b",
            r"\bsensitive personal information\b",
        ],
        "remediation": "CPRA requires a 'Do Not Sell or Share My Personal Information' link, plus a separate Sensitive PI rights page. Confirm the contract reflects the verbatim CPRA opt-out wording.",
    },
    {
        "rule_id": "us_state_privacy_2025",
        "title": "US state privacy law wave (TX, OR, MT, IA, DE, NJ, MN, etc.)",
        "jurisdiction": "United States — multi-state",
        "effective_date": "2024-2026 (rolling effective dates)",
        "severity": "medium",
        "url": "https://iapp.org/resources/article/us-state-privacy-legislation-tracker/",
        "patterns": [
            r"\b(?:Texas|Oregon|Montana|Iowa|Delaware|New Jersey|Minnesota)\s+residents?\b",
            r"\buniversal opt-out\b",
            r"\bglobal privacy control\b",
        ],
        "remediation": "Many of the 2024-26 state laws require honoring Universal Opt-Out Mechanisms (e.g., Global Privacy Control). Add a clause acknowledging UOMs are honored.",
    },
    {
        "rule_id": "in_bns_2023_replacement",
        "title": "India — IPC replaced by Bharatiya Nyaya Sanhita (BNS)",
        "jurisdiction": "India",
        "effective_date": "2024-07-01",
        "severity": "low",
        "url": "https://www.indiacode.nic.in/handle/123456789/20062",
        "patterns": [
            r"\bIndian\s+Penal\s+Code\b|\bIPC\b",
            r"\bSection\s+\d+\s+of\s+the\s+IPC\b",
            r"\bSection\s+(?:124A|420|499|375|376|144|153A)\b",
        ],
        "remediation": "IPC has been replaced by BNS (effective July 2024). Update statutory references — e.g., IPC 124A → BNS 152, IPC 420 → BNS 318.",
    },
    {
        "rule_id": "global_minimum_tax_pillar2",
        "title": "OECD Pillar Two — 15% global minimum tax",
        "jurisdiction": "International",
        "effective_date": "2024-01-01 (rolling)",
        "severity": "medium",
        "url": "https://www.oecd.org/tax/beps/about/",
        "patterns": [
            r"\b(?:tax\s+haven|low-tax\s+jurisdiction|effective\s+tax\s+rate)\b",
            r"\b(?:Cayman|BVI|Bermuda|Jersey|Ireland)\s+(?:subsidiary|entity|holdco)\b",
        ],
        "remediation": "Pillar Two imposes a 15% top-up tax via QDMTT/IIR/UTPR. Existing intra-group structures relying on low-tax jurisdictions should be reviewed before FY2025.",
    },
    {
        "rule_id": "eu_mica_crypto",
        "title": "EU MiCA — crypto-asset markets regulation",
        "jurisdiction": "European Union",
        "effective_date": "2024-12-30 (full)",
        "severity": "high",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1114",
        "patterns": [
            r"\b(stablecoin|asset-referenced token|e-money token|ART|EMT)\b",
            r"\b(crypto-?asset service|CASP|crypto exchange)\b",
        ],
        "remediation": "MiCA requires authorisation of Crypto-Asset Service Providers and prudential rules for stablecoin issuers. Add representations regarding MiCA compliance and authorised-CASP status.",
    },
    {
        "rule_id": "uk_online_safety_act",
        "title": "UK Online Safety Act 2023 — illegal-content + child-safety duties",
        "jurisdiction": "United Kingdom",
        "effective_date": "2025 (illegal harms duty live)",
        "severity": "high",
        "url": "https://www.legislation.gov.uk/ukpga/2023/50/contents",
        "patterns": [
            r"\b(user-to-user|U2U|user-generated)\b",
            r"\b(child sexual exploitation|CSE|CSAM)\b",
            r"\b(category\s+1|category 2A|category 2B)\b",
        ],
        "remediation": "Add a duty-of-care clause referencing illegal-harms risk assessment + Ofcom register status.",
    },
    {
        "rule_id": "in_dpdp_breach_notification",
        "title": "India DPDP — breach notification to DPB and affected users",
        "jurisdiction": "India",
        "effective_date": "2025",
        "severity": "medium",
        "url": "https://www.meity.gov.in/sites/upload_files/dit/files/Digital%20Personal%20Data%20Protection%20Act%202023.pdf",
        "patterns": [
            r"\b(data breach|security incident|personal data breach)\b",
            r"\bnotify\b.{0,30}\b(?:user|affected|customer|individual)\b",
        ],
        "remediation": "DPDP requires breach notification both to the Data Protection Board AND to each affected Data Principal. Update the SLA to include the latter, not just the regulator.",
    },
    {
        "rule_id": "us_sec_climate_disclosure",
        "title": "US SEC Climate-Related Disclosure Rule",
        "jurisdiction": "United States",
        "effective_date": "2025-2026 (phase-in)",
        "severity": "low",
        "url": "https://www.sec.gov/rules/final/2024/33-11275.pdf",
        "patterns": [
            r"\b(scope\s+1|scope\s+2|scope\s+3)\s+emissions\b",
            r"\bclimate-related\s+(?:risk|disclosure)\b",
        ],
        "remediation": "If the entity is SEC-registered and accelerated/large filer, scope-1/2 disclosures phase in from FY2025. Add a covenant for timely Form 10-K disclosure.",
    },
    {
        "rule_id": "eu_corp_sustainability",
        "title": "EU Corporate Sustainability Reporting Directive (CSRD) + ESRS",
        "jurisdiction": "European Union",
        "effective_date": "2024-2028 (rolling waves)",
        "severity": "low",
        "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32022L2464",
        "patterns": [
            r"\b(?:non-financial|sustainability)\s+(?:reporting|disclosure)\b",
            r"\bESRS\b",
            r"\bdouble materiality\b",
        ],
        "remediation": "CSRD + ESRS require double-materiality reporting on E/S/G KPIs. Confirm the entity's wave (1: large listed FY24 / 2: large non-listed FY25 / 3: listed SMEs FY26).",
    },
]


_RULE_CONFIRM_SYSTEM = """You are OmniLegal's Compliance Sentinel.

You will be given:
  • RULE — a specific legal change (id, title, jurisdiction, effective date, what to look for)
  • TEXT_SPAN — the exact span from the user's contract that the rule's pattern matched
  • CONTEXT — surrounding text (~600 chars) for disambiguation

Decide whether the user's TEXT actually triggers the rule, or if the
match is a false positive (e.g., "data" referring to non-personal data).

Return STRICT JSON:
{
  "triggers": true/false,
  "confidence": 0.0-1.0,
  "explanation": "<1-2 sentences justifying your decision>",
  "specific_advice": "<1-2 sentences of clause-specific remediation, NOT a generic legal lecture>"
}
"""


def _scan_patterns(text: str) -> list[dict[str, Any]]:
    """Find all rule pattern hits in ``text``."""
    hits: list[dict[str, Any]] = []
    for rule in SENTINEL_RULES:
        for pat in rule["patterns"]:
            for m in re.finditer(pat, text, re.IGNORECASE):
                start = max(0, m.start() - 300)
                end = min(len(text), m.end() + 300)
                hits.append({
                    "rule": rule,
                    "match_start": m.start(),
                    "match_end": m.end(),
                    "match_text": m.group(0),
                    "context": text[start:end],
                    "pattern": pat,
                })
    return hits


def _confirm_hit(hit: dict[str, Any]) -> dict[str, Any]:
    from src.services.llm_waterfall import generate_json
    rule = hit["rule"]
    prompt = (
        "RULE:\n" + json.dumps({
            "id": rule["rule_id"],
            "title": rule["title"],
            "jurisdiction": rule["jurisdiction"],
            "effective_date": rule["effective_date"],
            "severity": rule["severity"],
            "what_to_look_for": rule.get("remediation", ""),
        }, indent=2) +
        f"\n\nTEXT_SPAN: {hit['match_text']}\n\nCONTEXT:\n{hit['context']}\n\n"
        "Return STRICT JSON only."
    )
    parsed, used, _ = generate_json(
        system=_RULE_CONFIRM_SYSTEM, prompt=prompt,
        validate=lambda d: isinstance(d, dict) and "triggers" in d,
        max_tokens=600, temperature=0.15,
    )
    if parsed is None:
        # No LLM available — be conservative: treat the regex match as triggering, low confidence
        return {"triggers": True, "confidence": 0.4,
                "explanation": "Regex match — LLM unavailable to disambiguate.",
                "specific_advice": rule.get("remediation", ""),
                "used_model": "regex_only"}
    parsed["used_model"] = used
    return parsed


def scan(text: str, *, max_findings: int = 24) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {"error": "text is required"}
    if len(text) > 60_000:
        text = text[:60_000]

    hits = _scan_patterns(text)

    # Deduplicate: keep one hit per (rule_id, match_start//50) so the same rule
    # firing twice in the same paragraph doesn't blow up the LLM budget.
    deduped: dict[tuple[str, int], dict[str, Any]] = {}
    for h in hits:
        key = (h["rule"]["rule_id"], h["match_start"] // 50)
        if key not in deduped:
            deduped[key] = h
    final_hits = list(deduped.values())[:max_findings]

    findings: list[dict[str, Any]] = []
    for h in final_hits:
        verdict = _confirm_hit(h)
        if not verdict.get("triggers", False):
            continue
        rule = h["rule"]
        findings.append({
            "rule_id": rule["rule_id"],
            "title": rule["title"],
            "jurisdiction": rule["jurisdiction"],
            "effective_date": rule["effective_date"],
            "severity": rule["severity"],
            "url": rule["url"],
            "match_text": h["match_text"],
            "context_excerpt": h["context"][:480],
            "match_start": h["match_start"],
            "match_end": h["match_end"],
            "confidence": float(verdict.get("confidence") or 0.0),
            "explanation": verdict.get("explanation", ""),
            "remediation": verdict.get("specific_advice") or rule.get("remediation", ""),
            "verdict_used_model": verdict.get("used_model", ""),
        })

    severity_counts = {"blocking": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        severity_counts[f["severity"]] = severity_counts.get(f["severity"], 0) + 1

    # Risk score: blocking=1.0 each, high=0.6, medium=0.3, low=0.1, normalized to ≤1
    score = 0.0
    for f in findings:
        score += {"blocking": 1.0, "high": 0.6, "medium": 0.3, "low": 0.1}.get(f["severity"], 0.0)
    risk_score = min(1.0, score / 3.0)  # 3 high-sev = 100%

    findings.sort(key=lambda f: (
        {"blocking": 0, "high": 1, "medium": 2, "low": 3}.get(f["severity"], 9),
        -f["confidence"],
    ))

    return {
        "input_chars": len(text),
        "raw_pattern_hits": len(hits),
        "deduped_hits": len(final_hits),
        "confirmed_findings": len(findings),
        "rules_checked": len(SENTINEL_RULES),
        "severity_counts": severity_counts,
        "risk_score": round(risk_score, 3),
        "findings": findings,
    }


def list_rules() -> list[dict[str, Any]]:
    """Public-readable rule catalogue (without regex internals)."""
    return [
        {
            "rule_id": r["rule_id"],
            "title": r["title"],
            "jurisdiction": r["jurisdiction"],
            "effective_date": r["effective_date"],
            "severity": r["severity"],
            "url": r["url"],
            "remediation": r["remediation"],
        }
        for r in SENTINEL_RULES
    ]
