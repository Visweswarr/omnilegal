"""User-facing answer sanitization helpers."""
from __future__ import annotations

import re


def clean_answer_text(text: str) -> str:
    """Strip internal markers that should never reach the user."""
    text = re.sub(r'\*?\*?Authority gaps?\s+noted[:\*]*.*', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'\*?\*?AUTHORITY GAP:?\*?\*?[^\n]*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\*?\*?(UNSUPPORTED|VERIFIED|FABRICATED|NEEDS_CHECK):?\*?\*?[^\n]*\n?', '', text, flags=re.IGNORECASE)
    text = re.sub(r'(?i)\b(?:draft [a-z])\b', '', text)
    text = re.sub(r'(?im)^[*\s]*council deliberation.*$', '', text)
    text = re.sub(
        r'(?i)\b(?:gemini|groq|ollama|qwen|llama|gpt|claude|mistral|'
        r'openai|openrouter|anthropic|hugging\s*face|huggingface)\b',
        '',
        text,
    )
    text = re.sub(r'(?i)\b(?:multi-model council|model council|council deliberation|drafter|critic)\b', '', text)
    text = re.sub(r'(?i)\|\s*Sources:\s*\d+\s*\*?', '', text)
    text = re.sub(r'(?i)\bSources:\s*\d+\b', '', text)
    text = re.sub(r'(?i)\|\s*Confidence:\s*\d+%\s*\*?', '', text)
    text = re.sub(r'\s+\.', '.', text)
    text = re.sub(r'(?:\.\s*){2,}', '. ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()
