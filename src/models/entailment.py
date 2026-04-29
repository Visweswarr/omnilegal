import torch
from transformers import pipeline

import os
from dotenv import load_dotenv
from pathlib import Path
from groq import Groq

# Load environment variables for the API key
load_dotenv(Path(__file__).parent.parent.parent / ".env")

_ENTAILMENT_PIPE = None
_GROQ_CLIENT = None

def _get_groq_client():
    global _GROQ_CLIENT
    if _GROQ_CLIENT is None:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            return None
        _GROQ_CLIENT = Groq(api_key=api_key)
    return _GROQ_CLIENT

def get_entailment_pipeline():
    """Loads a DeBERTa NLI model for premise/hypothesis conflict detection."""
    global _ENTAILMENT_PIPE
    if _ENTAILMENT_PIPE is None:
        device = 0 if torch.cuda.is_available() else -1
        model_name = "cross-encoder/nli-deberta-base"
        print(f"Loading Conflict Detection model {model_name}...")
        _ENTAILMENT_PIPE = pipeline("text-classification", model=model_name, device=device)
    return _ENTAILMENT_PIPE

def detect_conflict(premise: str, hypothesis: str):
    """
    Evaluates whether the hypothesis contradicts the premise.
    For UN vs Indian Law: 
    Premise = Indian Constitutional Article
    Hypothesis = International Treaty Clause
    """
    pipe = get_entailment_pipeline()
    
    # Run the fast cross-encoder to get the mathematical logic prediction
    try:
        result = pipe({"text": premise, "text_pair": hypothesis})
        label = result.get('label', '')
        score = result.get('score', 0.0)
    except Exception:
        # Fallback if the pipeline gets weird dictionary inputs
        result = pipe(f"{premise} [SEP] {hypothesis}")[0]
        label = result.get('label', '')
        score = result.get('score', 0.0)
    
    if label == "LABEL_0" or label == "contradiction":
        status = "Conflict Detected"
        color = "red"
    elif label == "LABEL_1" or label == "entailment":
        status = "Full Alignment"
        color = "green"
    else:
        status = "Neutral / Not Directly Addressed"
        color = "yellow"
        
    # Now use Groq (Llama 3 70B) to explain the legal nuance
    explanation = "No explanation available (Groq API Key missing)."
    client = _get_groq_client()
    
    if client:
        system_prompt = (
            "You are an expert Model United Nations Legal Analyst. "
            "Your job is to analyze the relationship between two legal texts. "
            "Explain exactly WHY they are in conflict, why they align, or why they are neutral. "
            "Keep your explanation under 3 paragraphs and be highly specific to the given texts."
        )
        
        user_message = (
            f"Indian Domestic Law:\n{premise}\n\n"
            f"International Treaty Law:\n{hypothesis}\n\n"
            f"The cross-encoder NLI model predicted this relationship as: {status}\n\n"
            f"Please write a brilliant, MUN-style legal brief explaining this relationship."
        )
        
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                model="llama-3.3-70b-versatile",
                temperature=0.3,
                max_tokens=1024,
            )
            explanation = chat_completion.choices[0].message.content
        except Exception as e:
            explanation = f"Error generating explanation: {e}"
        
    return {
        "status": status,
        "raw_label": label,
        "confidence": score,
        "color": color,
        "explanation": explanation
    }
