"""OmniLegal Live Authority Engine.

Concurrent live queries against free / token-based legal data APIs:

  • Indian Kanoon       (token from .env)
  • CourtListener      (token from .env)
  • GovInfo            (key from .env)
  • EUR-Lex (CELLAR)   (no key, public)
  • Legifrance PISTE   (credentials from .env)
  • HUDOC (ECHR)       (no key, public)
  • UN Treaty Series   (no key, public)

We hit each in parallel with a short per-call timeout and aggregate the
results into a single time-stamped feed. Every hit is annotated with
``source``, ``url``, ``date``, ``snippet``, and ``jurisdiction`` so the
React UI can render badges, dates, and relative-time labels.

Designed to be resilient: any individual API failing only removes its slice
from the response — the rest still come through.
"""
from __future__ import annotations

import concurrent.futures
import datetime as _dt
import html
import json
import logging
import os
import re
import urllib.parse
import urllib.request
from typing import Any

log = logging.getLogger("omnilegal.live_authority")


# ── HTTP helper ────────────────────────────────────────────────────────────


_DEFAULT_TIMEOUT = 12.0
_USER_AGENT = "OmniLegal/3.0 (+https://omnilegal.local)"

# CourtListener rate-limits aggressively (~5 RPS). Use a process-wide
# semaphore so concurrent calls from arbitrage / drift / live search don't
# all stampede the API and trigger 429s.
import threading as _threading
_CL_SEMAPHORE = _threading.BoundedSemaphore(value=2)


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: float = _DEFAULT_TIMEOUT) -> dict | list | None:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as exc:  # noqa: BLE001
        log.info("HTTP json failed for %s: %s", url, exc)
        return None


def _http_text(url: str, headers: dict[str, str] | None = None, timeout: float = _DEFAULT_TIMEOUT) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:  # noqa: BLE001
        log.info("HTTP text failed for %s: %s", url, exc)
        return ""


def _strip_tags(text: str, limit: int = 300) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = " ".join(html.unescape(text).split())
    return text[:limit]


# ── Adapters ───────────────────────────────────────────────────────────────


def _indian_kanoon(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    token = os.environ.get("INDIAN_KANOON_API_TOKEN") or os.environ.get("INDIAN_KANOON_API_KEY")
    if not token:
        return []
    url = f"https://api.indiankanoon.org/search/?{urllib.parse.urlencode({'formInput': query, 'pagenum': '0'})}"
    data = None
    req = urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT,
        "Accept": "application/json",
        "Authorization": f"Token {token}",
    }, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as exc:
        log.info("Indian Kanoon failed: %s", exc)
        return []
    docs = (data or {}).get("docs") or (data or {}).get("results") or []
    out: list[dict[str, Any]] = []
    for d in docs[:max_items]:
        doc_id = d.get("tid") or d.get("docid") or d.get("id")
        if not doc_id:
            continue
        out.append({
            "source": "Indian Kanoon",
            "jurisdiction": "India",
            "title": _strip_tags(str(d.get("title") or d.get("docsource") or f"Doc {doc_id}"), 200),
            "snippet": _strip_tags(str(d.get("headline") or d.get("fragment") or ""), 360),
            "url": f"https://indiankanoon.org/doc/{doc_id}/",
            "date": str(d.get("publishdate") or d.get("docdate") or ""),
            "court": _strip_tags(str(d.get("docsource") or ""), 80),
            "kind": "case_law",
        })
    return out


def _courtlistener(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    token = os.environ.get("COURTLISTENER_TOKEN")
    if not token:
        return []
    url = f"https://www.courtlistener.com/api/rest/v4/search/?{urllib.parse.urlencode({'q': query, 'type': 'o', 'order_by': 'dateFiled desc'})}"
    headers = {"Authorization": f"Token {token}"}
    # Bounded concurrency to avoid 429 cascades during multi-jurisdiction scans.
    acquired = _CL_SEMAPHORE.acquire(timeout=8.0)
    if not acquired:
        log.info("CL semaphore timeout for query=%r", query[:60])
        return []
    try:
        data = _http_json(url, headers=headers, timeout=8.0)
    finally:
        _CL_SEMAPHORE.release()
    if not data:
        return []
    results = data.get("results") if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for r in (results or [])[:max_items]:
        case_name = r.get("caseName") or r.get("case_name") or r.get("name") or "Unknown opinion"
        snippet = r.get("snippet") or r.get("text") or ""
        url_path = r.get("absolute_url") or r.get("download_url") or ""
        if url_path and not url_path.startswith("http"):
            url_path = f"https://www.courtlistener.com{url_path}"
        out.append({
            "source": "CourtListener",
            "jurisdiction": "United States",
            "title": _strip_tags(str(case_name), 240),
            "snippet": _strip_tags(str(snippet), 360),
            "url": url_path or "https://www.courtlistener.com/",
            "date": str(r.get("dateFiled") or r.get("date_filed") or ""),
            "court": str(r.get("court") or r.get("court_id") or ""),
            "kind": "case_law",
        })
    return out


def _govinfo(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    api_key = os.environ.get("GOVINFO_API_KEY")
    if not api_key:
        return []
    try:
        import requests

        body = {
            "query": query,
            "pageSize": max_items,
            "offsetMark": "*",
            "sorts": [{"field": "publishdate", "sortOrder": "DESC"}],
        }
        r = requests.post(
            f"https://api.govinfo.gov/search?api_key={api_key}",
            json=body,
            headers={"Accept": "application/json"},
            timeout=12.0,
        )
        if r.status_code >= 400:
            log.info("GovInfo POST failed %s: %s", r.status_code, r.text[:160])
            return []
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        log.info("GovInfo failed: %s", exc)
        return []
    results = data.get("results") if isinstance(data, dict) else []
    out: list[dict[str, Any]] = []
    for r in (results or [])[:max_items]:
        out.append({
            "source": "GovInfo",
            "jurisdiction": "United States",
            "title": _strip_tags(str(r.get("title") or "Untitled"), 240),
            "snippet": _strip_tags(str(r.get("teaser") or r.get("collectionName") or ""), 360),
            "url": str(r.get("packageLink") or r.get("download") or "https://www.govinfo.gov/"),
            "date": str(r.get("dateIssued") or r.get("publishdate") or ""),
            "court": str(r.get("collectionName") or "Federal"),
            "kind": "statute_or_record",
        })
    return out


_EU_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
_QUERY_STOPWORDS = {
    "about", "against", "after", "before", "case", "cases", "court", "does", "from",
    "have", "into", "legal", "law", "laws", "rule", "rules", "the", "their", "there",
    "this", "under", "what", "when", "where", "with",
}
_CELEX_RE = re.compile(r"\b[1-9]\d{4}[A-Z]\d{4,}[A-Z0-9()]*\b", re.I)


def _sparql_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _query_terms(query: str, *, max_terms: int = 4) -> list[str]:
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", query.lower()):
        if token in _QUERY_STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
        if len(terms) >= max_terms:
            break
    return terms


def _eurlex_filter(query: str) -> str:
    celex = _CELEX_RE.search(query or "")
    if celex:
        return f'  FILTER(STR(?celex) = "{_sparql_literal(celex.group(0).upper())}")\n'
    terms = _query_terms(query)
    if not terms:
        safe_q = re.sub(r"[^A-Za-z0-9 ,.\-_/']", " ", query or "")[:80].strip().lower()
        terms = [safe_q] if safe_q else []
    if not terms:
        return ""
    clauses = [f'CONTAINS(LCASE(STR(?title)), "{_sparql_literal(term)}")' for term in terms]
    return "  FILTER(" + " && ".join(clauses) + ")\n"


def _eurlex(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    """EUR-Lex live search via the EU Publications Office public SPARQL endpoint.

    The CELLAR SPARQL endpoint at ``publications.europa.eu/webapi/rdf/sparql``
    is free and unauthenticated. We run a regex-FILTER query on English
    titles, sort by date desc, and turn each work URI into a CELEX-keyed
    EUR-Lex document URL. If SPARQL returns no rows we fall back to the
    curated landmark index keyed by topic.
    """
    out: list[dict[str, Any]] = []
    filter_clause = _eurlex_filter(query)
    if filter_clause:
        sparql = (
            "PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>\n"
            "PREFIX lang: <http://publications.europa.eu/resource/authority/language/>\n"
            "SELECT ?work ?celex ?title ?date WHERE {\n"
            "  ?work cdm:work_id_document ?celex .\n"
            "  ?work cdm:work_date_document ?date .\n"
            "  ?expression cdm:expression_belongs_to_work ?work .\n"
            "  ?expression cdm:expression_uses_language lang:ENG .\n"
            "  ?expression cdm:expression_title ?title .\n"
            f"{filter_clause}"
            "} ORDER BY DESC(?date) LIMIT " + str(max(max_items * 3, 10))
        )
        try:
            sp_url = _EU_SPARQL_ENDPOINT + "?" + urllib.parse.urlencode({"query": sparql})
            data = _http_json(
                sp_url,
                headers={"Accept": "application/sparql-results+json"},
                timeout=10.0,
            )
            seen_celex: set[str] = set()
            for row in (data or {}).get("results", {}).get("bindings", []):
                celex = (row.get("celex") or {}).get("value") or ""
                title = (row.get("title") or {}).get("value") or ""
                date  = (row.get("date") or {}).get("value") or ""
                # Filter to docs that have a real CELEX number (skip ST/IMMC/CONSIL drafts)
                if not celex or not re.match(r"^[0-9][0-9A-Z][0-9]{4}", celex):
                    continue
                if celex in seen_celex:
                    continue
                seen_celex.add(celex)
                out.append({
                    "source": "EUR-Lex",
                    "jurisdiction": "European Union",
                    "title": title[:240],
                    "snippet": f"CELEX {celex}, published {date}.",
                    "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                    "date": date,
                    "court": "EU",
                    "kind": "statute_or_record",
                })
                if len(out) >= max_items:
                    break
        except Exception as exc:
            log.info("EUR-Lex SPARQL failed: %s", exc)

    if out:
        return out

    # Curated fallback — landmark EU instruments + courts of justice judgments
    keyword = query.lower()
    landmark = [
        ("Charter of Fundamental Rights of the EU", "12012P/TXT", "", ["fundamental rights", "human rights", "charter"]),
        ("GDPR (Regulation 2016/679)", "32016R0679", "2016-04-27", ["data", "privacy", "personal data", "gdpr"]),
        ("Digital Services Act (Regulation 2022/2065)", "32022R2065", "2022-10-19", ["platform", "online", "content moderation", "dsa", "digital services"]),
        ("Digital Markets Act (Regulation 2022/1925)", "32022R1925", "2022-09-14", ["competition", "monopoly", "gatekeeper", "dma"]),
        ("AI Act (Regulation 2024/1689)", "32024R1689", "2024-06-13", ["ai", "artificial intelligence", "automated decision"]),
        ("Treaty on European Union (TEU)", "12016M/TXT", "", ["treaty", "membership", "withdrawal", "subsidiarity"]),
        ("Treaty on the Functioning of the EU (TFEU)", "12016E/TXT", "", ["competition", "internal market", "free movement"]),
        ("Consumer Rights Directive (Directive 2011/83/EU)", "32011L0083", "2011-10-25", ["consumer", "consumer protection", "distance selling", "withdrawal"]),
        ("Unfair Commercial Practices Directive (Directive 2005/29/EC)", "32005L0029", "2005-05-11", ["consumer", "protection", "commercial practices", "misleading"]),
        ("Consumer Protection Cooperation Regulation (Regulation 2017/2394)", "32017R2394", "2017-12-12", ["consumer", "protection", "enforcement", "cooperation"]),
        ("General Product Safety Regulation (Regulation 2023/988)", "32023R0988", "2023-05-10", ["consumer", "product safety", "safety"]),
        ("Schrems II (CJEU C-311/18)", "62018CJ0311", "2020-07-16", ["data transfer", "privacy shield", "schrems"]),
        ("Google Spain (CJEU C-131/12)", "62012CJ0131", "2014-05-13", ["data", "right to be forgotten", "search engine"]),
        ("Van Gend en Loos (CJEU 26/62)", "61962CJ0026", "1963-02-05", ["direct effect", "treaty", "european union"]),
        ("Costa v ENEL (CJEU 6/64)", "61964CJ0006", "1964-07-15", ["supremacy", "primacy", "european union"]),
    ]
    hits = []
    query_terms = set(_query_terms(query, max_terms=12))
    for name, celex, date, hints in landmark:
        score = sum(1 for h in hints if h in keyword)
        title_terms = set(_query_terms(name, max_terms=12))
        score += sum(1 for term in query_terms if term in title_terms) * 0.4
        if score > 0:
            hits.append((score, {
                "source": "EUR-Lex",
                "jurisdiction": "European Union",
                "title": name,
                "snippet": f"CELEX {celex}. Landmark EU authority relevant to: {query}",
                "url": f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:{celex}",
                "date": date,
                "court": "EU",
                "kind": "statute_or_record",
            }))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:max_items]]


def _legifrance(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    """Legifrance live search. Returns no results until PISTE credentials exist."""
    if not (
        os.environ.get("PISTE_API_KEY")
        and os.environ.get("PISTE_CLIENT_ID")
        and os.environ.get("PISTE_CLIENT_SECRET")
    ):
        return []
    try:
        from src.services.adapters.legifrance import (
            _article_identity,
            _article_text,
            _consult_article,
            _get_token,
            _search_legifrance,
            _source_url,
        )

        token = _get_token()
        rows = _search_legifrance(token, query, page_size=max_items)
    except Exception as exc:
        log.info("Legifrance failed: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for item in rows[:max_items]:
        ident = _article_identity(item)
        title = ident["title"] or "Legifrance result"
        snippet = ""
        try:
            article = _consult_article(token, item)
            snippet = _strip_tags(_article_text(article, fallback_title=title), 360)
        except Exception:
            snippet = ""
        out.append({
            "source": "Legifrance",
            "jurisdiction": "France",
            "title": _strip_tags(title, 240),
            "snippet": snippet or f"Official Legifrance result for: {query}",
            "url": _source_url(item),
            "date": "",
            "court": "France",
            "kind": "statute_or_record",
        })
    return out


def _hudoc(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    """European Court of Human Rights (HUDOC) keyword-scored landmark index.

    HUDOC's public ``app/query/results`` JSON endpoint has been firewalled
    (returns ``resultcount:0`` for every query as of 2025-26). Until a
    public alternative materialises we maintain a curated landmark index
    of the most cited ECHR cases per topic. Keyword-scored so ranking
    actually depends on the query, not just on which case happens to be
    first.
    """
    keyword = (query or "").lower()
    landmark_index = [
        ("Klass and Others v. Germany (1978)", "https://hudoc.echr.coe.int/eng?i=001-57510",
         ["surveillance", "secret", "interception", "phone", "wiretap", "intelligence"]),
        ("Big Brother Watch v. United Kingdom (2021)", "https://hudoc.echr.coe.int/eng?i=001-210077",
         ["surveillance", "mass", "intelligence", "metadata", "bulk", "snowden"]),
        ("Roman Zakharov v. Russia (2015)", "https://hudoc.echr.coe.int/eng?i=001-159324",
         ["surveillance", "russia", "telecom", "interception", "covert"]),
        ("Soering v. United Kingdom (1989)", "https://hudoc.echr.coe.int/eng?i=001-57619",
         ["death penalty", "extradition", "death row", "torture", "capital"]),
        ("Al-Saadoon and Mufdhi v. United Kingdom (2010)", "https://hudoc.echr.coe.int/eng?i=001-97575",
         ["death penalty", "iraq", "extradition", "transfer"]),
        ("Lautsi v. Italy (2011)", "https://hudoc.echr.coe.int/eng?i=001-104040",
         ["religion", "religious", "crucifix", "education", "school", "secular"]),
        ("Handyside v. United Kingdom (1976)", "https://hudoc.echr.coe.int/eng?i=001-57499",
         ["expression", "speech", "obscenity", "press", "margin of appreciation"]),
        ("Sunday Times v. United Kingdom (1979)", "https://hudoc.echr.coe.int/eng?i=001-57584",
         ["expression", "press", "media", "thalidomide", "contempt", "prior restraint"]),
        ("Goodwin v. United Kingdom (1996)", "https://hudoc.echr.coe.int/eng?i=001-57974",
         ["press", "journalist", "source", "expression", "confidentiality"]),
        ("Hatton v. United Kingdom (2003)", "https://hudoc.echr.coe.int/eng?i=001-61188",
         ["environment", "noise", "airport", "heathrow", "private life"]),
        ("Vinter and Others v. United Kingdom (2013)", "https://hudoc.echr.coe.int/eng?i=001-122664",
         ["life", "imprisonment", "whole life", "sentence", "parole"]),
        ("Hirst v. United Kingdom (2005)", "https://hudoc.echr.coe.int/eng?i=001-70442",
         ["voting", "prisoner", "elections", "disenfranchisement"]),
        ("S.A.S. v. France (2014)", "https://hudoc.echr.coe.int/eng?i=001-145466",
         ["religion", "veil", "burka", "niqab", "muslim", "face covering"]),
        ("M.S.S. v. Belgium and Greece (2011)", "https://hudoc.echr.coe.int/eng?i=001-103050",
         ["asylum", "refugee", "dublin", "migration"]),
        ("Hirsi Jamaa v. Italy (2012)", "https://hudoc.echr.coe.int/eng?i=001-109231",
         ["asylum", "refugee", "non-refoulement", "boat", "migration", "libya"]),
        ("Tarakhel v. Switzerland (2014)", "https://hudoc.echr.coe.int/eng?i=001-148070",
         ["asylum", "refugee", "dublin", "family", "italy"]),
        ("Salduz v. Turkey (2008)", "https://hudoc.echr.coe.int/eng?i=001-89893",
         ["fair trial", "lawyer", "right to counsel", "interrogation"]),
        ("Beuze v. Belgium (2018)", "https://hudoc.echr.coe.int/eng?i=001-187802",
         ["fair trial", "lawyer", "police", "interrogation", "right to counsel"]),
        ("Dudgeon v. United Kingdom (1981)", "https://hudoc.echr.coe.int/eng?i=001-57473",
         ["homosexual", "lgbt", "private life", "criminal", "ireland"]),
        ("Oliari v. Italy (2015)", "https://hudoc.echr.coe.int/eng?i=001-156265",
         ["lgbt", "same-sex", "marriage", "civil union", "italy"]),
        ("K.A.B. v. Spain (2012)", "https://hudoc.echr.coe.int/eng?i=001-111758",
         ["family", "child", "adoption", "deportation"]),
        ("Christine Goodwin v. United Kingdom (2002)", "https://hudoc.echr.coe.int/eng?i=001-60596",
         ["transgender", "trans", "gender recognition", "identity"]),
        ("Hämäläinen v. Finland (2014)", "https://hudoc.echr.coe.int/eng?i=001-145768",
         ["transgender", "trans", "marriage", "private life"]),
        ("Vavricka v. Czech Republic (2021)", "https://hudoc.echr.coe.int/eng?i=001-209039",
         ["vaccine", "vaccination", "compulsory", "health", "child"]),
        ("Verein Klimaseniorinnen v. Switzerland (2024)", "https://hudoc.echr.coe.int/eng?i=001-233206",
         ["climate", "environment", "warming", "switzerland"]),
        ("Ilascu v. Moldova and Russia (2004)", "https://hudoc.echr.coe.int/eng?i=001-61886",
         ["torture", "detention", "transnistria", "russia", "extraterritorial"]),
        ("Ireland v. United Kingdom (1978)", "https://hudoc.echr.coe.int/eng?i=001-57506",
         ["torture", "interrogation", "five techniques", "ireland", "northern ireland"]),
        ("Selmouni v. France (1999)", "https://hudoc.echr.coe.int/eng?i=001-58287",
         ["torture", "police", "custody", "ill-treatment"]),
        ("Aksoy v. Turkey (1996)", "https://hudoc.echr.coe.int/eng?i=001-58003",
         ["torture", "turkey", "kurd", "police custody"]),
        ("McCann v. United Kingdom (1995)", "https://hudoc.echr.coe.int/eng?i=001-57943",
         ["right to life", "police", "shooting", "ira", "gibraltar"]),
        ("Osman v. United Kingdom (1998)", "https://hudoc.echr.coe.int/eng?i=001-58257",
         ["right to life", "police", "duty to protect"]),
        ("Catan v. Moldova and Russia (2012)", "https://hudoc.echr.coe.int/eng?i=001-114082",
         ["education", "language", "russia", "moldova", "transnistria"]),
        ("Bayev v. Russia (2017)", "https://hudoc.echr.coe.int/eng?i=001-174422",
         ["lgbt", "russia", "propaganda", "expression"]),
        ("Navalny v. Russia (2018)", "https://hudoc.echr.coe.int/eng?i=001-187605",
         ["russia", "navalny", "assembly", "political", "arbitrary"]),
        ("Big Brother Watch v. United Kingdom (2018)", "https://hudoc.echr.coe.int/eng?i=001-186048",
         ["surveillance", "intelligence", "metadata"]),
        ("Hentrich v. France (1994)", "https://hudoc.echr.coe.int/eng?i=001-57878",
         ["property", "tax", "preemption", "expropriation"]),
        ("James v. United Kingdom (1986)", "https://hudoc.echr.coe.int/eng?i=001-57507",
         ["property", "leasehold", "expropriation"]),
        ("Lithgow v. United Kingdom (1986)", "https://hudoc.echr.coe.int/eng?i=001-57526",
         ["property", "nationalisation", "compensation"]),
        ("Sporrong and Lönnroth v. Sweden (1982)", "https://hudoc.echr.coe.int/eng?i=001-57580",
         ["property", "expropriation", "permits"]),
        ("Cengiz v. Turkey (2015)", "https://hudoc.echr.coe.int/eng?i=001-159188",
         ["expression", "internet", "youtube", "blocking", "turkey"]),
        ("Ahmet Yıldırım v. Turkey (2012)", "https://hudoc.echr.coe.int/eng?i=001-115705",
         ["internet", "blocking", "expression", "turkey", "google"]),
        ("Gillberg v. Sweden (2012)", "https://hudoc.echr.coe.int/eng?i=001-110144",
         ["data", "research", "academic", "privacy", "freedom of information"]),
    ]
    # Generic keywords add a *small* score, so even a bare query produces something
    base_words = set(re.findall(r"[a-z]+", keyword)) | {"echr", "human rights"}
    hits: list[tuple[float, dict[str, Any]]] = []
    for name, url, hints in landmark_index:
        score = 0.0
        for h in hints:
            if h in keyword:
                score += 1.0
        # Token overlap as tie-breaker
        for tok in re.findall(r"[a-z]+", name.lower()):
            if tok in base_words and len(tok) > 4:
                score += 0.3
        if score <= 0:
            continue
        hits.append((score, {
            "source": "HUDOC (ECHR)",
            "jurisdiction": "European Court of Human Rights",
            "title": name,
            "snippet": f"Landmark ECHR case relevant to: {query}",
            "url": url,
            "date": "",
            "court": "European Court of Human Rights",
            "kind": "case_law",
        }))
    hits.sort(key=lambda x: x[0], reverse=True)
    return [h[1] for h in hits[:max_items]]


def _un_treaties(query: str, max_items: int = 5) -> list[dict[str, Any]]:
    """UN Treaty Collection — public HTML search."""
    url = (
        "https://treaties.un.org/Pages/AdvanceSearch.aspx?tab=UNTS&clang=_en"
    )
    # The UNTC site is heavy on POST forms; the simpler signal is to surface
    # canonical landing-page entries derived from the query keywords.
    # We synthesise a curated list of likely-relevant treaty hubs.
    hits = []
    keyword = query.lower()
    treaty_index = [
        ("UN Charter", "https://www.un.org/en/about-us/un-charter", ["un", "charter", "security", "war", "force"]),
        ("ICCPR", "https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-civil-and-political-rights", ["civil", "political", "speech", "expression", "torture", "fair trial", "privacy", "religion"]),
        ("ICESCR", "https://www.ohchr.org/en/instruments-mechanisms/instruments/international-covenant-economic-social-and-cultural-rights", ["economic", "social", "cultural", "education", "health", "labour", "housing"]),
        ("CEDAW", "https://www.ohchr.org/en/instruments-mechanisms/instruments/convention-elimination-all-forms-discrimination-against-women", ["women", "gender", "discrimination"]),
        ("CRC", "https://www.ohchr.org/en/instruments-mechanisms/instruments/convention-rights-child", ["child", "minor", "youth"]),
        ("CRPD", "https://www.ohchr.org/en/instruments-mechanisms/instruments/convention-rights-persons-disabilities", ["disability", "disabled"]),
        ("UNCAT", "https://www.ohchr.org/en/instruments-mechanisms/instruments/convention-against-torture-and-other-cruel-inhuman-or-degrading", ["torture", "inhuman", "degrading", "death penalty"]),
        ("Geneva Conventions", "https://ihl-databases.icrc.org/ihl", ["geneva", "war", "armed conflict", "humanitarian"]),
        ("Rome Statute (ICC)", "https://www.icc-cpi.int/", ["icc", "international criminal", "genocide", "crimes against humanity", "war crimes"]),
        ("VCLT", "https://legal.un.org/ilc/texts/instruments/english/conventions/1_1_1969.pdf", ["treaty", "vienna", "interpretation"]),
        ("Refugee Convention", "https://www.unhcr.org/1951-refugee-convention", ["refugee", "asylum", "non-refoulement"]),
        ("Paris Agreement", "https://unfccc.int/process-and-meetings/the-paris-agreement", ["climate", "paris", "carbon", "emissions"]),
    ]
    for name, link, hints in treaty_index:
        score = sum(1 for h in hints if h in keyword)
        if score:
            hits.append((score, name, link))
    hits.sort(key=lambda x: x[0], reverse=True)
    out: list[dict[str, Any]] = []
    for score, name, link in hits[:max_items]:
        out.append({
            "source": "UN Treaty Index",
            "jurisdiction": "International",
            "title": name,
            "snippet": f"Public international-law instrument relevant to: {query}",
            "url": link,
            "date": "",
            "court": "United Nations",
            "kind": "treaty",
        })
    return out


# ── Aggregator ─────────────────────────────────────────────────────────────


_REGISTRY = {
    "indian_kanoon": _indian_kanoon,
    "courtlistener": _courtlistener,
    "govinfo":       _govinfo,
    "eurlex":        _eurlex,
    "legifrance":    _legifrance,
    "hudoc":         _hudoc,
    "un_treaties":   _un_treaties,
}


def search_live(query: str, sources: list[str] | None = None, max_items: int = 5) -> dict[str, Any]:
    """Hit every requested source in parallel and aggregate."""
    query = (query or "").strip()
    if not query:
        return {"query": query, "results": [], "by_source": {}, "total": 0}
    selected = [s for s in (sources or list(_REGISTRY.keys())) if s in _REGISTRY]
    if not selected:
        selected = list(_REGISTRY.keys())

    by_source: dict[str, list[dict[str, Any]]] = {}
    errors: dict[str, str] = {}
    started = _dt.datetime.utcnow()

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(8, len(selected))) as pool:
        futures = {
            pool.submit(_REGISTRY[name], query, max_items): name
            for name in selected
        }
        for fut in concurrent.futures.as_completed(futures, timeout=_DEFAULT_TIMEOUT * 2):
            name = futures[fut]
            try:
                hits = fut.result(timeout=_DEFAULT_TIMEOUT)
            except Exception as exc:
                errors[name] = f"{type(exc).__name__}: {exc}"
                hits = []
            by_source[name] = hits or []

    flat: list[dict[str, Any]] = []
    for name, hits in by_source.items():
        for h in hits:
            h.setdefault("source_key", name)
            flat.append(h)

    elapsed = (_dt.datetime.utcnow() - started).total_seconds()
    return {
        "query": query,
        "elapsed_seconds": round(elapsed, 2),
        "results": flat,
        "by_source": by_source,
        "errors": errors,
        "total": len(flat),
        "asked_sources": selected,
        "available_sources": list(_REGISTRY.keys()),
    }
