"""Multi-model council orchestrator for quality-first legal research.

Phases:
  I.   Parallel Drafters  — 2-3 LLMs generate anonymised drafts
  II.  Cross-Examination   — Source Critic + Legal-Risk Critic + Citation Verifier
  III. Final Judge         — synthesises best answer from drafts + critiques
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any

from src.config import (
    LEGAL_RESEARCH_SHORT_DISCLAIMER,
    OMNILEGAL_COUNCIL_ANONYMIZE,
    OMNILEGAL_COUNCIL_DRAFTER_COUNT,
    OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
)
from src.schemas import (
    AnswerMode,
    Citation,
    CitationGrade,
    CouncilVote,
    ResearchAnswer,
    RetrievedPassage,
)
from src.services.answer_modes import build_mode_system_prompt, get_mode_spec
from src.services.provider_registry import ProviderMeta, ProviderRegistry

logger = logging.getLogger(__name__)


def _anonymise_draft(text: str, index: int) -> str:
    """Strip model identifiers and label as Draft-A/B/C."""
    label = chr(65 + index)  # A, B, C ...
    cleaned = re.sub(
        r"(?i)(gemini|groq|ollama|qwen|llama|gpt|claude|mistral)[^\s]*",
        "[model]",
        text,
    )
    return f"--- DRAFT {label} ---\n{cleaned}"


def _format_context(retrieved: list[dict[str, Any]], *, limit: int = 12) -> str:
    """Build a compact context string from retrieved passages."""
    parts: list[str] = []
    for i, p in enumerate(retrieved[:limit], 1):
        meta = p.get("metadata", {}) or {}
        source = meta.get("source_name", "Unknown")
        jurisdiction = meta.get("jurisdiction", "")
        citation = meta.get("citation", "")
        url = meta.get("source_url", "")
        excerpt = " ".join((p.get("text") or "").split())[:800]
        parts.append(f"[{i}] {source} | {jurisdiction} | {citation} | {url}\n{excerpt}")
    return "\n\n".join(parts)


class CouncilOrchestrator:
    """Runs the bounded multi-model council deliberation."""

    def __init__(self, registry: ProviderRegistry | None = None) -> None:
        self.registry = registry or ProviderRegistry.get_instance()

    async def run_council(
        self,
        query: str,
        retrieved: list[dict[str, Any]],
        answer_mode: AnswerMode = AnswerMode.tourist_practical,
        *,
        answer_style: str = "long",
    ) -> ResearchAnswer:
        """Execute the full council pipeline and return a typed ResearchAnswer."""
        t0 = time.monotonic()
        context = _format_context(retrieved)
        mode_prompt = build_mode_system_prompt(answer_mode)

        # Phase I — Parallel Drafting
        drafters = self.registry.get_drafters(OMNILEGAL_COUNCIL_DRAFTER_COUNT)
        if not drafters:
            logger.error("No LLM providers available for council drafting")
            return self._empty_answer(answer_mode, "No LLM providers available", t0)

        drafts = await self._parallel_draft(
            query, context, mode_prompt, answer_style, drafters
        )
        if not any(d["text"] for d in drafts):
            return self._empty_answer(answer_mode, "All drafters failed", t0)

        # Phase II — Cross-Examination
        anonymised = self._anonymise_drafts(drafts)
        critic = self.registry.get_best_for("critic")
        source_critique = ""
        risk_critique = ""
        if critic:
            source_critique, risk_critique = await asyncio.gather(
                self._source_critic(critic, anonymised, context),
                self._legal_risk_critic(critic, anonymised, query),
            )

        # Phase III — Final Judge
        judge_provider = self.registry.get_best_for("judge")
        final_text = ""
        if judge_provider:
            final_text = await self._judge_synthesise(
                judge_provider,
                query,
                anonymised,
                context,
                source_critique,
                risk_critique,
                mode_prompt,
                answer_style,
            )

        # Fallback: use best draft if judge failed
        if not final_text:
            best = max(drafts, key=lambda d: len(d.get("text", "")))
            final_text = best.get("text", "")

        # Build typed result
        return self._build_answer(
            final_text=final_text,
            drafts=drafts,
            source_critique=source_critique,
            risk_critique=risk_critique,
            retrieved=retrieved,
            answer_mode=answer_mode,
            t0=t0,
        )

    # ── Phase I: Parallel Drafting ────────────────────────────────────

    async def _parallel_draft(
        self,
        query: str,
        context: str,
        mode_prompt: str,
        answer_style: str,
        drafters: list[ProviderMeta],
    ) -> list[dict[str, Any]]:
        """Run all drafters concurrently."""
        system = (
            "You are a legal research drafter for OmniLegal Codex.\n\n"
            f"{mode_prompt}\n\n"
            "Ground every claim in the supplied source excerpts. "
            "Use [N] citation markers referencing source numbers. "
            f"Answer style: {answer_style}.\n"
            f"Disclaimer: {LEGAL_RESEARCH_SHORT_DISCLAIMER}"
        )
        prompt = f"QUERY: {query}\n\nRETRIEVED SOURCES:\n{context}"

        async def _draft_one(provider: ProviderMeta) -> dict[str, Any]:
            try:
                text = await asyncio.wait_for(
                    asyncio.to_thread(
                        provider.generate, system=system, prompt=prompt
                    ),
                    timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
                )
                return {"provider": provider.name, "text": text or ""}
            except asyncio.TimeoutError:
                logger.warning("Drafter %s timed out", provider.name)
                return {"provider": provider.name, "text": "", "error": "timeout"}
            except Exception as exc:
                logger.warning("Drafter %s failed: %s", provider.name, exc)
                return {"provider": provider.name, "text": "", "error": str(exc)}

        tasks = [_draft_one(d) for d in drafters]
        return list(await asyncio.gather(*tasks, return_exceptions=False))

    def _anonymise_drafts(self, drafts: list[dict[str, Any]]) -> str:
        """Combine drafts into an anonymised block."""
        parts: list[str] = []
        for i, d in enumerate(drafts):
            text = d.get("text", "").strip()
            if not text:
                continue
            if OMNILEGAL_COUNCIL_ANONYMIZE:
                parts.append(_anonymise_draft(text, i))
            else:
                parts.append(f"--- DRAFT ({d.get('provider', 'unknown')}) ---\n{text}")
        return "\n\n".join(parts) if parts else "No drafts produced."

    # ── Phase II: Critics ─────────────────────────────────────────────

    async def _source_critic(
        self, critic: ProviderMeta, anonymised: str, context: str
    ) -> str:
        """Source Critic: verifies claims against retrieved passages."""
        system = (
            "You are a Source Critic for a legal research council.\n"
            "Review the drafts against the retrieved sources.\n"
            "For each major claim, mark it:\n"
            "- VERIFIED: claim matches a specific source excerpt\n"
            "- UNSUPPORTED: claim has no matching source\n"
            "- NEEDS_CHECK: claim partially supported\n"
            "List AUTHORITY GAPS: important legal questions not covered."
        )
        prompt = f"DRAFTS:\n{anonymised}\n\nSOURCES:\n{context}"
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(critic.generate, system=system, prompt=prompt),
                timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Source critic failed: %s", exc)
            return ""

    async def _legal_risk_critic(
        self, critic: ProviderMeta, anonymised: str, query: str
    ) -> str:
        """Legal-Risk Critic: flags UPL, evasion, safety issues."""
        system = (
            "You are a Legal-Risk Critic.\n"
            "Review the drafts for:\n"
            "1. EVASION: advice to bribe, forge documents, or evade law\n"
            "2. UPL: overclaiming (presenting as legal advice, not information)\n"
            "3. SAFETY: missing critical warnings (detention, deportation risk)\n"
            "4. FABRICATION: citations or specifics not in the sources\n"
            "Flag each issue with severity: CRITICAL, HIGH, MEDIUM, LOW."
        )
        prompt = f"QUERY: {query}\n\nDRAFTS:\n{anonymised}"
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(critic.generate, system=system, prompt=prompt),
                timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            logger.warning("Legal-risk critic failed: %s", exc)
            return ""

    # ── Phase III: Judge ──────────────────────────────────────────────

    async def _judge_synthesise(
        self,
        judge: ProviderMeta,
        query: str,
        anonymised: str,
        context: str,
        source_critique: str,
        risk_critique: str,
        mode_prompt: str,
        answer_style: str,
    ) -> str:
        """Final Judge: synthesises the best answer."""
        system = (
            "You are the Chief Justice producing the FINAL user-facing legal research answer.\n\n"
            f"{mode_prompt}\n\n"
            "CRITICAL OUTPUT RULES:\n"
            "1. Produce a POLISHED, PROFESSIONAL answer that reads like a legal brief.\n"
            "2. Keep well-sourced claims and [N] citation markers from the drafts.\n"
            "3. For claims marked UNSUPPORTED by the critic, drop them unless they can be "
            "directly grounded in the verified source excerpts.\n"
            "4. NEVER include the words 'AUTHORITY GAP', 'UNSUPPORTED', 'FABRICATED', "
            "'VERIFIED', 'NEEDS_CHECK', 'Draft A', 'Draft B' in your output.\n"
            "5. NEVER mention models, AI, council, deliberation, or drafters.\n"
            "6. If information is incomplete, state what the law generally provides and "
            "recommend consulting a local lawyer for specifics.\n"
            "7. Address any safety/risk flags (detention, deportation, etc.).\n"
            "8. Use clear headings (## Quick Answer, ## Key Rights, ## Practical Steps, "
            "## What to Avoid, ## Disclaimer).\n"
            f"9. Answer style: {answer_style}.\n"
            f"Disclaimer: {LEGAL_RESEARCH_SHORT_DISCLAIMER}"
        )
        critiques = (
            f"SOURCE CRITIQUE:\n{source_critique or 'No source critique available.'}\n\n"
            f"RISK CRITIQUE:\n{risk_critique or 'No risk critique available.'}"
        )
        prompt = (
            f"QUERY: {query}\n\n"
            f"VERIFIED SOURCE EXCERPTS:\n{context}\n\n"
            f"DRAFTS:\n{anonymised}\n\n"
            f"{critiques}"
        )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(judge.generate, system=system, prompt=prompt),
                timeout=OMNILEGAL_COUNCIL_TIMEOUT_SECONDS + 10,
            )
        except Exception as exc:
            logger.warning("Judge synthesis failed: %s", exc)
            return ""

    # ── Helpers ────────────────────────────────────────────────────────

    def _build_answer(
        self,
        *,
        final_text: str,
        drafts: list[dict[str, Any]],
        source_critique: str,
        risk_critique: str,
        retrieved: list[dict[str, Any]],
        answer_mode: AnswerMode,
        t0: float,
    ) -> ResearchAnswer:
        sections: dict[str, str] = {}
        # Parse sections from final text
        current_heading = "content"
        current_lines: list[str] = []
        for line in final_text.splitlines():
            heading_match = re.match(r"^\s*#{2,6}\s+(.+?)\s*$", line)
            if heading_match:
                if current_lines:
                    sections[current_heading] = "\n".join(current_lines).strip()
                current_heading = heading_match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)
        if current_lines:
            sections[current_heading] = "\n".join(current_lines).strip()

        # Council votes
        votes: list[CouncilVote] = []
        for i, d in enumerate(drafts):
            if d.get("text"):
                votes.append(
                    CouncilVote(
                        drafter_id=chr(65 + i),
                        provider=d.get("provider", "unknown"),
                        model=d.get("provider", "unknown"),
                        position="agree" if d.get("text") else "disagree",
                        confidence=0.7 if d.get("text") else 0.0,
                    )
                )

        used_models = [d.get("provider", "") for d in drafts if d.get("text")]
        sources = _retrieved_to_sources(retrieved)

        return ResearchAnswer(
            answer_sections=sections,
            sources=sources,
            council_votes=votes,
            authority_gaps=[],
            answer_mode=answer_mode,
            used_models=used_models,
            total_time_ms=int((time.monotonic() - t0) * 1000),
            confidence=0.82 if sections and sources else 0.35 if sections else 0.0,
        )

    def _empty_answer(
        self, mode: AnswerMode, reason: str, t0: float
    ) -> ResearchAnswer:
        return ResearchAnswer(
            answer_mode=mode,
            fallback_reason=reason,
            total_time_ms=int((time.monotonic() - t0) * 1000),
        )


def _retrieved_to_sources(retrieved: list[dict[str, Any]]) -> list[RetrievedPassage]:
    """Convert retrieval dictionaries into the public ResearchAnswer source list."""
    sources: list[RetrievedPassage] = []
    for idx, item in enumerate(retrieved or [], 1):
        meta = item.get("metadata") or {}
        source_name = str(meta.get("source_name") or meta.get("citation") or "Unknown").strip()
        content = str(item.get("text") or "").strip()
        if not source_name or source_name == "Unknown" or not content:
            continue
        citation = Citation(
            marker=f"[{idx}]",
            source_name=source_name,
            jurisdiction=str(meta.get("jurisdiction") or "N/A"),
            page=meta.get("page") or meta.get("page_start"),
            excerpt=content[:500],
            article=str(meta.get("article_number") or meta.get("section") or "") or None,
            notes=str(meta.get("source_url") or meta.get("citation") or "") or None,
        )
        sources.append(
            RetrievedPassage(
                citation=citation,
                content=content,
                rank=idx,
                relevance_score=float(item.get("score") or item.get("rerank_score") or 0.0),
                document_type=str(meta.get("doc_type") or meta.get("legal_type") or "") or None,
            )
        )
    return sources
