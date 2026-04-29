"""
Step 4 — Per-jurisdiction reasoning in IRAC format.

The implementation keeps DSPy optional: if dspy-ai is installed later, this
module's JSON contract is already shaped like the DSPy signature that MIPROv2
will tune. The current local Windows path uses Groq when available and a
deterministic fallback otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).parent.parent.parent))

from src.config import GROQ_API_KEY, GROQ_MODEL
from src.pipeline.state import PipelineStateDict
from src.services.groq_client import generate_groq_chat

_IRAC_SYSTEM = """You are OmniLegal Codex, an expert cross-border legal research analyst.
Analyze the provided sources under the specified jurisdiction using a concise IRAC method:
- Issue: identify the core legal question
- Rule: state the applicable rules, treaties, or precedents
- Application: apply the rules to the facts, with attention to arrest procedure, detention safeguards, consular access, foreign-document recognition, and realistic procedural next steps when relevant
- Conclusion: state a clear conclusion

CRITICAL RULES:
- NEVER fabricate or invent case names, party names, or citations.
- ONLY reference cases, treaties, and articles that appear in the provided SOURCE PASSAGES.
- Do NOT create fictitious case names like "Government of X vs Y" unless explicitly in the sources.
- If sources are insufficient, say "insufficient evidence" — do NOT make up legal authorities.
- Prefer primary law and case law over commentary.

Return ONLY valid JSON matching this schema:
{
  "jurisdiction": "<jurisdiction name>",
  "applicable_rules": [{"rule": "<rule text>", "source_marker": <int or null>, "quote": "<short quote or empty>"}],
  "application": "<application paragraph>",
  "conclusion": "<lawful|unlawful|indeterminate|lawful_if_conditions>",
  "conditions_if_any": ["<condition>", "..."],
  "confidence": <0.0-1.0>,
  "citations": [{"source_name": "...", "article": "...", "excerpt": "..."}]
}"""


def _call_groq(
    *,
    messages: list[dict[str, str]],
    max_tokens: int = 1024,
    temperature: float = 0.1,
    response_format: dict[str, str] | None = None,
) -> str:
    """Small wrapper kept patchable for tests and future LLM backends."""
    if not GROQ_API_KEY:
        return ""
    generation = generate_groq_chat(
        model=GROQ_MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        response_format=response_format,
    )
    if generation.error:
        print(f"Warning: Groq jurisdiction analysis failed: {generation.error}")
    return generation.text


def _analyze_jurisdiction(
    query: str,
    jurisdiction: str,
    passages: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run IRAC analysis for a single jurisdiction."""
    from src.models.dspy_modules import load_jurisdiction_analyzer

    if not GROQ_API_KEY:
        return _fallback_analysis(jurisdiction)

    relevant = [p for p in passages if p.get("metadata", {}).get("jurisdiction") == jurisdiction or jurisdiction == "international"][:6]
    if not relevant:
        relevant = passages[:4]

    context = "\n\n".join(
        f"[{i+1}] {p['metadata'].get('source_name','')}: {p['text'][:600]}"
        for i, p in enumerate(relevant)
    )

    dspy_analyzer = load_jurisdiction_analyzer()
    if dspy_analyzer is not None:
        try:
            prediction = dspy_analyzer(jurisdiction=jurisdiction, question=query, context=context)
            
            # Extract fields logically
            applicable_rules = []
            if isinstance(prediction.applicable_rules, list):
                for rule in prediction.applicable_rules:
                    applicable_rules.append({"rule": str(rule), "source_marker": None, "quote": ""})
            elif isinstance(prediction.applicable_rules, str):
                applicable_rules.append({"rule": prediction.applicable_rules, "source_marker": None, "quote": ""})

            result = {
                "jurisdiction": jurisdiction,
                "applicable_rules": applicable_rules,
                "application": str(prediction.application) if hasattr(prediction, "application") else "",
                "conclusion": str(prediction.conclusion) if hasattr(prediction, "conclusion") else "indeterminate",
                "conditions_if_any": prediction.conditions_if_any if isinstance(getattr(prediction, "conditions_if_any", []), list) else [str(getattr(prediction, "conditions_if_any", ""))],
                "confidence": float(prediction.confidence) if hasattr(prediction, "confidence") else 0.0,
                "citations": []
            }
            return result
        except Exception as exc:
            import sys
            print(f"Warning: DSPy jurisdiction analysis failed for {jurisdiction}: {exc}. Falling back to default Groq prompt.", file=sys.stderr)

    try:
        raw = _call_groq(
            messages=[
                {"role": "system", "content": _IRAC_SYSTEM},
                {"role": "user", "content": (
                    f"JURISDICTION: {jurisdiction}\n\n"
                    f"QUESTION: {query}\n\n"
                    f"SOURCES:\n{context}\n\n"
                    "Provide the IRAC analysis as JSON:"
                )},
            ],
            max_tokens=1024,
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        raw = raw or "{}"
        result = json.loads(raw)
        result["jurisdiction"] = jurisdiction
        result.setdefault("conditions_if_any", [])
        result.setdefault("applicable_rules", [])
        result.setdefault("confidence", 0.0)
        return result
    except Exception as exc:
        print(f"Warning: jurisdiction analysis failed for {jurisdiction}: {exc}")
        return _fallback_analysis(jurisdiction)


def _fallback_analysis(jurisdiction: str) -> dict[str, Any]:
    return {
        "jurisdiction": jurisdiction,
        "applicable_rules": [],
        "application": "insufficient evidence: no verified jurisdiction-specific analysis was produced from the retrieved sources.",
        "conclusion": "indeterminate",
        "conditions_if_any": [],
        "confidence": 0.0,
        "citations": [],
    }


def _detect_jurisdictions(retrieved: list[dict[str, Any]], iso_codes: list[str]) -> list[str]:
    """Infer which jurisdictions are represented in retrieved passages or from query entities."""
    seen: set[str] = {code.lower() for code in iso_codes}
    for p in retrieved:
        j = str(p.get("metadata", {}).get("jurisdiction", "")).lower()
        if j and j not in ("unknown", "international", ""):
            seen.add(j)
        elif not j or j == "unknown":
            text = str(p.get("text", "")).lower()
            if "supreme court of india" in text or "constitution of india" in text:
                seen.add("in")
            elif "united states code" in text or "supreme court of the united states" in text or "us supreme court" in text:
                seen.add("us")
            elif "european court of human rights" in text or "echr" in text or "cjeu" in text:
                seen.add("eu")
            elif "uk supreme court" in text or "house of lords" in text:
                seen.add("gb")
                
    if not seen:
        seen.add("international")
    return sorted(seen)


def analyze_jurisdictions(state: PipelineStateDict) -> PipelineStateDict:
    query = state["raw_input"]
    retrieved = state.get("retrieved", [])
    
    iso_codes = []
    if "entities" in state and "iso_country_codes" in state["entities"]:
        iso_codes = state["entities"]["iso_country_codes"]
        
    jurisdictions = _detect_jurisdictions(retrieved, iso_codes)

    analyses = []
    for jur in jurisdictions:
        analysis = _analyze_jurisdiction(query, jur, retrieved)
        analyses.append(analysis)

    return {**state, "jurisdiction_analyses": analyses}
