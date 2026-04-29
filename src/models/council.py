import os
import gc
import re
from pathlib import Path
from dotenv import load_dotenv

from src.rag.retriever import get_hybrid_retriever, normalize_query_text
from src.config import COUNCIL_EXPERT_2_MODEL

# Load environment variables
load_dotenv(Path(__file__).parent.parent.parent / ".env")

def _free_memory():
    """Aggressively free GPU memory between model loading."""
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass

def _get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return None
    from groq import Groq
    return Groq(api_key=api_key)

_QUERY_PREFIX_PATTERNS = [
    r"^\s*tell me about\s+",
    r"^\s*brief me on\s+",
    r"^\s*explain\s+",
    r"^\s*summarize\s+",
    r"^\s*summary of\s+",
    r"^\s*what is\s+",
    r"^\s*what are\s+",
    r"^\s*who is\s+",
]

_QUERY_STOPWORDS = {
    "a", "about", "an", "and", "are", "brief", "case", "cases", "court",
    "decision", "describe", "discuss", "explain", "for", "give", "held",
    "holding", "how", "in", "is", "judge", "judgment", "law", "legal",
    "me", "of", "on", "or", "please", "regarding", "rule", "rules",
    "summarize", "summary", "tell", "the", "this", "to", "what", "when",
    "where", "who", "why", "arbitration", "arbitral", "tribunal"
}


def _doc_text(doc) -> str:
    """Return the text field from either a dict hit or a LangChain Document."""
    return doc["text"] if isinstance(doc, dict) else doc.page_content


def _doc_meta(doc) -> dict:
    """Return the metadata dict from either a dict hit or a LangChain Document."""
    return doc.get("metadata", {}) if isinstance(doc, dict) else getattr(doc, "metadata", {})


def _normalize_text(text: str) -> str:
    text = re.sub(r"(?<=[A-Za-z])\d{2,3}\b", "", text or "")
    text = re.sub(r"^\d+\s+", "", text)
    return " ".join(text.split()).strip()


def _tokenize(text: str):
    return re.findall(r"[a-z0-9]+", text.lower())


def _extract_query_terms(query: str):
    return [
        token for token in _tokenize(query)
        if len(token) > 2 and token not in _QUERY_STOPWORDS
    ]


def _normalize_query_subject(query: str) -> str:
    subject = normalize_query_text((query or "").strip().rstrip("?.! "))
    for pattern in _QUERY_PREFIX_PATTERNS:
        subject = re.sub(pattern, "", subject, flags=re.IGNORECASE)
    return subject.strip() or (query or "").strip()


def _build_qa_question(query: str) -> str:
    stripped = (query or "").strip()
    if stripped.endswith("?") and len(stripped.split()) <= 14:
        return stripped
    return f"What does this source say about {_normalize_query_subject(query)}?"


def _source_label(doc) -> str:
    meta = _doc_meta(doc)
    source = meta.get("source_name", "Unknown")
    page = meta.get("page")
    if page is None:
        return str(source)
    return f"{source} (page {page})"


def _substantive_text_score(text: str) -> float:
    lowered = text.lower()
    alpha_tokens = re.findall(r"[a-z]+", lowered)
    numeric_tokens = re.findall(r"\b\d+[a-z]?\b", lowered)
    citation_markers = [
        "icj reports", " ilr", " byil", " see also", " ibid",
        "pp.", "p. ", "series a", "series a/b"
    ]
    narrative_terms = [
        "court", "held", "states", "responsible", "sovereignty",
        "warships", "mines", "albania", "albanian", "british"
    ]

    score = min(len(alpha_tokens), 120) * 0.01
    score += min(lowered.count(".") + lowered.count(":"), 4) * 0.2
    score -= min(len(numeric_tokens), 25) * 0.04
    score -= sum(lowered.count(marker) for marker in citation_markers) * 0.35
    score -= min(lowered.count("("), 5) * 0.08
    score += sum(term in lowered for term in narrative_terms) * 0.08

    if lowered.startswith("see also") or lowered.startswith("ibid"):
        score -= 0.5

    return score


def _rank_docs_for_query(query: str, docs):
    query_terms = _extract_query_terms(query)
    if not query_terms:
        return docs

    phrase = " ".join(query_terms)

    def doc_score(doc):
        text = _doc_text(doc)
        lowered = text.lower()
        term_matches = sum(1 for term in query_terms if term in lowered)
        phrase_bonus = 2 if len(query_terms) > 1 and phrase in lowered else 0
        return (term_matches + phrase_bonus, _substantive_text_score(text))

    return sorted(docs, key=doc_score, reverse=True)


def _docs_with_explicit_query_hits(query: str, docs):
    query_terms = _extract_query_terms(query)
    if not query_terms:
        return []

    return [
        doc for doc in docs
        if any(term in _doc_text(doc).lower() for term in query_terms)
    ]


def _is_informative_answer(
    answer: str,
    *,
    min_chars: int,
    min_words: int,
    require_terminal_punctuation: bool = False
) -> bool:
    cleaned = _normalize_text(answer)
    if len(cleaned) < min_chars:
        return False
    if len(cleaned.split()) < min_words:
        return False
    if cleaned.upper() == "NOT_RELEVANT":
        return False
    if require_terminal_punctuation and cleaned[-1] not in ".!?\"'":
        return False
    return True


def _run_extractive_qa(question: str, context: str, tokenizer, model, device: str):
    import torch

    encoded = tokenizer(
        question,
        context,
        truncation="only_second",
        max_length=512,
        return_offsets_mapping=True,
        return_tensors="pt"
    )
    sequence_ids = encoded.sequence_ids(0)
    offset_mapping = encoded.pop("offset_mapping")[0]
    model_inputs = {key: value.to(device) for key, value in encoded.items()}

    with torch.no_grad():
        outputs = model(**model_inputs)

    start_logits = outputs.start_logits[0].cpu()
    end_logits = outputs.end_logits[0].cpu()
    start_probs = torch.softmax(start_logits, dim=-1)
    end_probs = torch.softmax(end_logits, dim=-1)

    best_text = ""
    best_score = float("-inf")
    best_confidence = 0.0
    max_answer_tokens = 40

    for start_index, sequence_id in enumerate(sequence_ids):
        if sequence_id != 1:
            continue

        for end_index in range(start_index, min(start_index + max_answer_tokens, len(sequence_ids))):
            if sequence_ids[end_index] != 1:
                break

            start_char, _ = offset_mapping[start_index].tolist()
            _, end_char = offset_mapping[end_index].tolist()
            if end_char <= start_char:
                continue

            answer_text = context[start_char:end_char].strip()
            if not answer_text:
                continue

            score = (start_logits[start_index] + end_logits[end_index]).item()
            if score > best_score:
                best_score = score
                best_confidence = float((start_probs[start_index] * end_probs[end_index]).item())
                best_text = answer_text

    return _normalize_text(best_text), best_confidence


def _dedupe_answers(council_answers):
    unique_answers = []
    normalized_answers = []

    for answer in council_answers:
        normalized = re.sub(r"[^a-z0-9]+", " ", answer["answer"].lower()).strip()
        is_duplicate = any(
            normalized == seen
            or normalized in seen
            or seen in normalized
            for seen in normalized_answers
        )
        if is_duplicate:
            continue

        normalized_answers.append(normalized)
        unique_answers.append(answer)

    return unique_answers


def _format_docs(docs):
    """Format retrieved documents into a context string."""
    parts = []
    for i, d in enumerate(docs, 1):
        meta = _doc_meta(d)
        source = meta.get('source_name', 'Unknown')
        jurisdiction = meta.get('jurisdiction', 'N/A')
        page = meta.get('page', '?')
        parts.append(
            f"[Source {i}: {source} | Jurisdiction: {jurisdiction} | Page: {page}]\n"
            f"{_doc_text(d)}"
        )
    return "\n\n".join(parts)

def generate_council_responses(query: str, status_placeholder=None):
    """
    1. Retrieve context
    2. Run Expert 1 (QA model) to get grounded extracted spans
    3. Clear memory
    4. Run Expert 2 (Generative) on focused excerpts instead of one
       truncated mega-prompt
    5. Return all grounded responses + context
    """
    retriever = get_hybrid_retriever(k=12)
    if not retriever:
        raise ValueError("Vector store not built. Run `python src/rag/vector_store.py`.")
    normalized_query = normalize_query_text(query)
        
    if status_placeholder:
        status_placeholder.info("🔍 Retrieving legal context...")
        
    ranked_docs = _rank_docs_for_query(normalized_query, retriever.invoke(query))
    explicit_hit_docs = _docs_with_explicit_query_hits(normalized_query, ranked_docs)
    if len(explicit_hit_docs) >= 3:
        docs = explicit_hit_docs[:6]
    else:
        docs = ranked_docs[:6]
    context_str = _format_docs(docs)
    
    council_answers = []
    import torch
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # ---------------------------------------------------------
    # EXPERT 1: Extractive QA Model
    # ---------------------------------------------------------
    if status_placeholder:
        status_placeholder.info("🧠 Expert 1 (Legal-BERT QA) reading context...")
        
    try:
        from transformers import AutoModelForQuestionAnswering, AutoTokenizer

        qa_question = _build_qa_question(normalized_query)
        qa_tokenizer = AutoTokenizer.from_pretrained(
            "atharvamundada99/bert-large-question-answering-finetuned-legal"
        )
        qa_model = AutoModelForQuestionAnswering.from_pretrained(
            "atharvamundada99/bert-large-question-answering-finetuned-legal"
        ).to(device)
        qa_model.eval()
        
        for doc in docs:
            answer_text, confidence = _run_extractive_qa(
                qa_question,
                _doc_text(doc),
                qa_tokenizer,
                qa_model,
                device
            )

            if confidence >= 0.12 and _is_informative_answer(
                answer_text,
                min_chars=18,
                min_words=4
            ):
                council_answers.append({
                    "expert": "Extractive Legal-BERT",
                    "answer": answer_text,
                    "source": _source_label(doc),
                    "confidence": round(confidence, 3)
                })
        
        del qa_model
        del qa_tokenizer
        _free_memory()
    except Exception as e:
        print(f"Failed to run Expert 1: {e}")
        
    # ---------------------------------------------------------
    # EXPERT 2: Abstractive Generative Model
    # ---------------------------------------------------------
    if status_placeholder:
        status_placeholder.info(f"💡 Expert 2 (Flan-T5 Generative) brainstorming...")
        
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(COUNCIL_EXPERT_2_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            COUNCIL_EXPERT_2_MODEL,
            torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        ).to(device)

        generation_tasks = []
        top_generation_docs = []
        seen_generation_sources = set()

        for doc in docs:
            source_label = _source_label(doc)
            if source_label in seen_generation_sources:
                continue
            if _substantive_text_score(_doc_text(doc)) < 0.5:
                continue
            seen_generation_sources.add(source_label)
            top_generation_docs.append(doc)
            if len(top_generation_docs) == 3:
                break

        if not top_generation_docs:
            top_generation_docs = docs[:3]

        for doc in top_generation_docs:
            source_label = _source_label(doc)
            base_prompt = (
                "You are a careful legal research assistant.\n"
                "Use only the source excerpt.\n"
                "If the excerpt is not relevant to the question, answer exactly: NOT_RELEVANT.\n\n"
                f"Question: {normalized_query}\n"
                f"Source: {source_label}\n"
                f"Excerpt:\n{_doc_text(doc)}\n\n"
            )
            generation_tasks.append({
                "source": source_label,
                "prompt": base_prompt + "Write 2-4 sentences summarizing the most relevant facts or holding."
            })
            generation_tasks.append({
                "source": source_label,
                "prompt": base_prompt + "Write 2-4 sentences identifying the legal principle or implication."
            })

        combined_excerpt = "\n\n".join(
            f"[{_source_label(doc)}]\n{_doc_text(doc)}"
            for doc in top_generation_docs
        )
        combined_prompt = (
            "You are a careful legal research assistant.\n"
            "Use only the source excerpts.\n"
            "If the excerpts are not relevant to the question, answer exactly: NOT_RELEVANT.\n\n"
            f"Question: {normalized_query}\n"
            f"Source excerpts:\n{combined_excerpt}\n\n"
        )
        generation_tasks.append({
            "source": "Combined top council sources",
            "prompt": combined_prompt + "Write 3-4 sentences summarizing the facts, issue, and outcome."
        })
        generation_tasks.append({
            "source": "Combined top council sources",
            "prompt": combined_prompt + "Write 3-4 sentences explaining the legal principles and significance."
        })

        prompts = [task["prompt"] for task in generation_tasks]
        inputs = tokenizer(
            prompts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=448
        ).to(device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=96,
                do_sample=True,
                temperature=0.7,
                top_p=0.9,
                repetition_penalty=1.15,
                no_repeat_ngram_size=3
            )

        decoded_answers = tokenizer.batch_decode(outputs, skip_special_tokens=True)

        for task, raw_answer in zip(generation_tasks, decoded_answers):
            answer_text = _normalize_text(raw_answer)
            if _is_informative_answer(
                answer_text,
                min_chars=40,
                min_words=8,
                require_terminal_punctuation=True
            ):
                council_answers.append({
                    "expert": "Abstractive Flan-T5",
                    "answer": answer_text,
                    "source": task["source"]
                })

        del model
        del tokenizer
        _free_memory()
    except Exception as e:
        print(f"Failed to run Expert 2: {e}")

    council_answers = _dedupe_answers(council_answers)

    return {
        "context": context_str,
        "council_answers": council_answers,
        "docs": docs
    }

def evaluate_with_groq(query, context, council_answers, status_placeholder=None):
    """
    Sends the ~10 council responses to Groq to act as the Chief Justice.
    """
    if status_placeholder:
        status_placeholder.info("👑 Chief Justice (Groq 70B) evaluating the council...")
        
    client = _get_groq_client()
    normalized_query = normalize_query_text(query)

    if not client:
        return "⚠️ GROQ_API_KEY is missing. The Chief Justice cannot preside over this case."
        
    # Format the council's submissions
    if council_answers:
        submission_blocks = []
        for idx, ans in enumerate(council_answers, 1):
            confidence_note = ""
            if "confidence" in ans:
                confidence_note = f" | confidence={ans['confidence']}"
            submission_blocks.append(
                f"--- Council Member {idx} ({ans['expert']} - {ans['source']}{confidence_note}) ---\n"
                f"Proposed Answer: {ans['answer']}"
            )
        submissions = "\n\n".join(submission_blocks)
    else:
        submissions = "No reliable junior submissions were produced. Answer directly from the context excerpts."

    system_prompt = (
        "You are the Chief Justice of a legal research council.\n"
        "You must answer ONLY from the provided context excerpts.\n"
        "Treat junior submissions as unreliable drafts: use them only when the context supports them.\n\n"
        "Requirements:\n"
        "1. Start with a short section titled 'Evaluation of Junior Assistant Submissions'.\n"
        "2. Mark submissions as supported, partially supported, or unsupported based on the context.\n"
        "3. Then write a section titled 'Final Verdict' that directly answers the user's question.\n"
        "4. Cite every material factual or legal claim with [Source N].\n"
        "5. If the context is incomplete, explicitly say what is missing instead of guessing.\n"
        "6. Ignore irrelevant retrieved material rather than forcing it into the answer."
    )
    
    normalized_query_note = ""
    if normalized_query.lower() != query.lower():
        normalized_query_note = f"NORMALIZED QUERY FOR RETRIEVAL: {normalized_query}\n\n"

    user_prompt = (
        f"QUESTION: {query}\n\n"
        f"{normalized_query_note}"
        f"RAW LEGAL CONTEXT:\n{context}\n\n"
        f"JUNIOR ASSISTANT SUBMISSIONS:\n{submissions}\n\n"
        "Please write the evaluation first, then the final verdict."
    )
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
            max_tokens=2048,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"Error during Chief Justice evaluation: {e}"
