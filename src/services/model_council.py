from __future__ import annotations

from src.models.council import evaluate_with_groq, generate_council_responses
from src.schemas import Citation, CouncilResult, CouncilSubmission
from src.services.retrieval_qa import answer_question, dedupe_citations


def _normalize_submission(raw_answer: dict) -> CouncilSubmission:
    return CouncilSubmission(
        expert=raw_answer.get("expert", "Unknown"),
        answer=raw_answer.get("answer", "").strip(),
        source=raw_answer.get("source", "Unknown"),
        confidence=raw_answer.get("confidence"),
    )


def _fallback_verdict(query: str, qa_answer: str, council_answers: list[CouncilSubmission]) -> str:
    if council_answers:
        return (
            "Evaluation of Junior Assistant Submissions\n\n"
            "The council submissions were generated, but no Chief Justice review was available. "
            "Use the cited passages and junior submissions below as supporting research, not as a final holding.\n\n"
            "Final Verdict\n\n"
            f"For the query `{query}`, the shared retrieval pipeline supports this answer:\n\n{qa_answer}"
        )
    return qa_answer


def run_model_council(query: str, status_placeholder=None) -> CouncilResult:
    qa_result = answer_question(query, k=6, use_groq=False)

    try:
        council_data = generate_council_responses(query, status_placeholder=status_placeholder)
    except Exception:
        council_data = {"context": "", "council_answers": [], "docs": []}

    council_answers = [
        _normalize_submission(answer)
        for answer in council_data.get("council_answers", [])
        if answer.get("answer")
    ]

    verdict = ""
    used_groq = False
    context = council_data.get("context", "")
    if context:
        verdict = evaluate_with_groq(
            query,
            context,
            [answer.model_dump(exclude_none=True) for answer in council_answers],
            status_placeholder=status_placeholder,
        )
        used_groq = "Chief Justice cannot preside" not in verdict and not verdict.startswith("Error during")

    if not verdict:
        verdict = _fallback_verdict(query, qa_result.answer, council_answers)
    elif "Chief Justice cannot preside" in verdict or verdict.startswith("Error during"):
        verdict = _fallback_verdict(query, qa_result.answer, council_answers)
        used_groq = False

    citations: list[Citation] = dedupe_citations(
        qa_result.citations + [passage.citation for passage in qa_result.sources]
    )

    return CouncilResult(
        query=query,
        verdict=verdict,
        council_answers=council_answers,
        citations=citations,
        supporting_context=qa_result.sources,
        supporting_qa=qa_result,
        used_model="hybrid_council",
        used_groq=used_groq,
    )
