"""OmniLegal v3 API routes — the 5 flagship pillars.

Mounted directly on the backend FastAPI app at port 8001. Existing
``src.api_router.router`` (health, ingestion, conflict, irac, debug) is
mounted alongside; this module only adds the new flagship endpoints.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("omnilegal.api_v2")

router = APIRouter(prefix="/api", tags=["omnilegal_v3"])


# ── Schemas ────────────────────────────────────────────────────────────────


class AtlasRequest(BaseModel):
    topic: str = Field(..., description="Legal topic, e.g. 'death penalty'.")
    include_ai_inferred: bool = Field(default=True)


class ForensicsRequest(BaseModel):
    text: str = Field(..., description="Legal prose to verify.")


class AdvocacyRequest(BaseModel):
    country_key: str = Field(..., description="e.g. 'india', 'us', 'uk'.")
    country_name: str = Field(..., description="Display name, e.g. 'India'.")
    topic: str
    position: str = Field(default="FOR", description="FOR | AGAINST | NEUTRAL")
    include_conflict: bool = True


class LiveRequest(BaseModel):
    query: str
    sources: list[str] | None = None
    max_items: int = 5


class CouncilRequest(BaseModel):
    query: str
    k: int = 6


class ResearchRequest(BaseModel):
    query: str
    persona: str = Field(default="researcher")
    k: int = 6


# ── Atlas ──────────────────────────────────────────────────────────────────


@router.post("/atlas/analyze")
async def atlas_analyze(req: AtlasRequest) -> dict[str, Any]:
    try:
        from src.services.atlas_service import build_atlas

        return await asyncio.to_thread(build_atlas, req.topic,
                                       include_ai_inferred=req.include_ai_inferred)
    except Exception as exc:
        log.exception("atlas_analyze failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Forensics ──────────────────────────────────────────────────────────────


@router.post("/forensics/verify")
async def forensics_verify(req: ForensicsRequest) -> dict[str, Any]:
    try:
        from src.services.forensics_service import verify_text

        return await asyncio.to_thread(verify_text, req.text)
    except Exception as exc:
        log.exception("forensics_verify failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Advocacy ───────────────────────────────────────────────────────────────


@router.post("/advocacy/generate")
async def advocacy_generate(req: AdvocacyRequest) -> dict[str, Any]:
    try:
        from src.services.advocacy_service import generate_advocacy_packet

        return await asyncio.to_thread(
            generate_advocacy_packet,
            req.country_key, req.country_name, req.topic, req.position,
            include_conflict=req.include_conflict,
        )
    except Exception as exc:
        log.exception("advocacy_generate failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Live Authority ─────────────────────────────────────────────────────────


@router.post("/live/search")
async def live_search(req: LiveRequest) -> dict[str, Any]:
    try:
        from src.services.live_authority_service import search_live

        return await asyncio.to_thread(
            search_live, req.query, req.sources, req.max_items,
        )
    except Exception as exc:
        log.exception("live_search failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Council of Models ──────────────────────────────────────────────────────


@router.post("/council/debate")
async def council_debate(req: CouncilRequest) -> dict[str, Any]:
    try:
        from src.services.council_service import run_council

        return await asyncio.to_thread(run_council, req.query, req.k)
    except Exception as exc:
        log.exception("council_debate failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Research console (replacement for Chainlit chat) ───────────────────────


_PERSONA_PROMPTS = {
    "tourist": (
        "You are a practical legal advisor for a traveller or tourist. Answer in plain "
        "English. Focus on what is and isn't allowed in the relevant jurisdictions, the "
        "punishments, and what to do if a problem arises. Cite sources with [C#] markers."
    ),
    "researcher": (
        "You are an academic legal researcher. Provide a thorough, footnote-dense answer "
        "with cross-jurisdictional analysis where relevant. Cite sources with [C#] markers."
    ),
    "law_student": (
        "You are a law student preparing for an exam. Structure your answer in IRAC "
        "(Issue, Rule, Application, Conclusion). Cite leading cases with [C#] markers."
    ),
    "layman": (
        "You are explaining the law to a non-lawyer. Use plain English, short sentences, "
        "and concrete examples. Cite sources with [C#] markers."
    ),
    "conflict_detector": (
        "You are a comparative-law analyst. Compare how different jurisdictions treat the "
        "question and flag any conflict with international rules. Cite sources with "
        "[C#] markers."
    ),
}


@router.post("/research/ask")
async def research_ask(req: ResearchRequest) -> dict[str, Any]:
    try:
        from src.services.citation_verification import verify_answer_citations
        from src.services.retrieval_qa import (
            answer_question, build_context, dedupe_citations, retrieve_passages,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"import failed: {type(exc).__name__}: {exc}")

    persona_key = (req.persona or "researcher").lower()
    persona_prompt = _PERSONA_PROMPTS.get(persona_key, _PERSONA_PROMPTS["researcher"])

    def _run() -> dict[str, Any]:
        passages = retrieve_passages(req.query, k=req.k, comparative=True)
        # Reuse answer_question for the Groq path; for persona variation we rely on the
        # built-in retrieval template fallback if no client is configured.
        qa = answer_question(req.query, k=req.k, use_groq=True)

        # Try to bias the Groq-rendered answer toward the persona by re-prompting.
        if qa.used_groq and passages:
            from src.services.groq_client import generate_groq_chat

            ctx = build_context(passages)
            re_run = generate_groq_chat(
                messages=[
                    {"role": "system", "content": persona_prompt},
                    {"role": "user", "content": (
                        f"QUESTION: {req.query}\n\nRETRIEVED CONTEXT:\n{ctx[:6000]}\n\n"
                        "Answer using only the context. Use [C#] markers to cite."
                    )},
                ],
                max_tokens=1500,
                temperature=0.25,
            )
            answer_text = re_run.text or qa.answer
            used_model = re_run.model or qa.used_model
        else:
            answer_text = qa.answer
            used_model = qa.used_model

        passage_dicts = [
            {
                "marker": p.citation.marker,
                "source_name": p.citation.source_name,
                "jurisdiction": p.citation.jurisdiction,
                "page": p.citation.page,
                "excerpt": p.citation.excerpt or p.content[:280],
                "text": p.content[:1000],
            }
            for p in passages
        ]
        verification = verify_answer_citations(answer_text, passage_dicts)
        citations = dedupe_citations([p.citation for p in passages])

        return {
            "query": req.query,
            "persona": persona_key,
            "answer": answer_text,
            "used_model": used_model,
            "citations": [
                {
                    "marker": c.marker,
                    "source_name": c.source_name,
                    "jurisdiction": c.jurisdiction,
                    "page": c.page,
                    "excerpt": c.excerpt,
                }
                for c in citations
            ],
            "passages": passage_dicts,
            "verification": verification,
        }

    try:
        return await asyncio.to_thread(_run)
    except Exception as exc:
        log.exception("research_ask failed")
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


# ── Sources/dataset overview (for landing page metrics) ────────────────────


@router.get("/overview")
async def overview() -> dict[str, Any]:
    """Cheap, fast snapshot for the landing page."""
    try:
        from src.config import ALL_COLLECTIONS
        from src.rag.vector_store import get_store

        def _scan() -> dict[str, Any]:
            store = get_store()
            existing = set(store.available_collections())
            total = 0
            collection_counts: dict[str, int] = {}
            for col in ALL_COLLECTIONS:
                if col in existing:
                    n = store.collection_point_count(col)
                    collection_counts[col] = n
                    total += n
            return {
                "total_chunks": total,
                "collections": collection_counts,
                "collection_count": len(collection_counts),
            }

        snapshot = await asyncio.to_thread(_scan)
    except Exception as exc:
        snapshot = {"total_chunks": 0, "collections": {}, "collection_count": 0,
                    "error": f"{type(exc).__name__}: {exc}"}

    return {
        **snapshot,
        "live_sources": [
            {"key": "indian_kanoon",  "name": "Indian Kanoon",        "jurisdiction": "India"},
            {"key": "courtlistener", "name": "CourtListener",         "jurisdiction": "United States"},
            {"key": "govinfo",       "name": "GovInfo",               "jurisdiction": "United States"},
            {"key": "eurlex",        "name": "EUR-Lex",                "jurisdiction": "European Union"},
            {"key": "hudoc",         "name": "HUDOC (ECHR)",           "jurisdiction": "ECHR"},
            {"key": "un_treaties",   "name": "UN Treaty Index",        "jurisdiction": "International"},
        ],
        "council_models": [
            {"id": "claude-sonnet-4-5",  "name": "Claude Sonnet 4.5",  "provider": "Anthropic via Emergent"},
            {"id": "gemini-2.5-flash",   "name": "Gemini 2.5 Flash",   "provider": "Google"},
            {"id": "llama-3.3-70b",      "name": "Llama 3.3 70B",      "provider": "Groq"},
        ],
    }
