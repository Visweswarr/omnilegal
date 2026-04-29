"""
Central abstraction for heavy NLP model loading.
Memoizes load failures to prevent crashing or repeated retries during graph execution.
"""
from __future__ import annotations

import sys
from functools import lru_cache

from src.config import (
    CLASSIFIER_MODEL,
    GLINER_MODEL,
    NLI_MODEL,
    OMNILEGAL_ENABLE_GLINER,
    OMNILEGAL_ENABLE_LEGAL_NER,
    OMNILEGAL_ENABLE_NLI_VERIFIER,
    OMNILEGAL_ENABLE_ZERO_SHOT,
    SPACY_FALLBACK_MODEL,
    SPACY_NER_MODEL,
)

_FAILED_MODELS: set[str] = set()


@lru_cache(maxsize=1)
def get_spacy_model():
    """Retrieve the spaCy legal NER model, or fallback, or None on failure."""
    if not OMNILEGAL_ENABLE_LEGAL_NER:
        return None

    if "spacy" in _FAILED_MODELS:
        return None

    try:
        import spacy

        try:
            return spacy.load(SPACY_NER_MODEL)
        except OSError:
            print(f"Warning: Primary spaCy model '{SPACY_NER_MODEL}' not found. Trying fallback '{SPACY_FALLBACK_MODEL}'...", file=sys.stderr)
            try:
                return spacy.load(SPACY_FALLBACK_MODEL)
            except OSError:
                print(f"Warning: Fallback spaCy model '{SPACY_FALLBACK_MODEL}' also not found. Disabling spaCy NER.", file=sys.stderr)
                _FAILED_MODELS.add("spacy")
                return None
    except ImportError:
        print("Warning: 'spacy' library not installed. Disabling spaCy NER.", file=sys.stderr)
        _FAILED_MODELS.add("spacy")
        return None
    except Exception as exc:
        print(f"Warning: Unexpected error loading spaCy: {exc}", file=sys.stderr)
        _FAILED_MODELS.add("spacy")
        return None


@lru_cache(maxsize=1)
def get_gliner_model():
    """Retrieve the GLiNER model, or None on failure."""
    if not OMNILEGAL_ENABLE_GLINER:
        return None

    if "gliner" in _FAILED_MODELS:
        return None

    try:
        from gliner import GLiNER
        model = GLiNER.from_pretrained(GLINER_MODEL)
        return model
    except ImportError:
        print("Warning: 'gliner' library not installed. Trying isolated adapter later if configured.", file=sys.stderr)
        _FAILED_MODELS.add("gliner")
        return None
    except Exception as exc:
        print(f"Warning: Unexpected error loading GLiNER in-process: {exc}", file=sys.stderr)
        _FAILED_MODELS.add("gliner")
        return None


@lru_cache(maxsize=1)
def get_zero_shot_classifier(multi_label: bool = False):
    """Retrieve the DeBERTa zero-shot pipeline, or None on failure."""
    if not OMNILEGAL_ENABLE_ZERO_SHOT:
        return None
    
    key = f"zero_shot_{multi_label}"
    if key in _FAILED_MODELS:
        return None
        
    try:
        from transformers import pipeline
        clf = pipeline(
            "zero-shot-classification",
            model=CLASSIFIER_MODEL,
            device=-1, # CPU by default
            multi_label=multi_label
        )
        return clf
    except ImportError:
        print("Warning: 'transformers' or 'torch' library not installed. Disabling zero-shot classification.", file=sys.stderr)
        _FAILED_MODELS.add(key)
        return None
    except Exception as exc:
        print(f"Warning: Unexpected error loading zero-shot pipeline: {exc}", file=sys.stderr)
        _FAILED_MODELS.add(key)
        return None


@lru_cache(maxsize=None)
def get_nli_verifier(model_name: str = NLI_MODEL, kwargs_str: str = ""):
    """Retrieve the NLI pipeline, or None on failure."""
    if not OMNILEGAL_ENABLE_NLI_VERIFIER:
        return None
        
    key = f"nli_{model_name}"
    if key in _FAILED_MODELS:
        return None
        
    try:
        from transformers import pipeline
        
        kwargs = {}
        if "trust_remote_code" in kwargs_str:
            kwargs["trust_remote_code"] = True
            
        nli = pipeline(
            "text-classification",
            model=model_name,
            device=-1,
            **kwargs
        )
        return nli
    except ImportError:
        print("Warning: 'transformers' or 'torch' library not installed. Disabling NLI verification.", file=sys.stderr)
        _FAILED_MODELS.add(key)
        return None
    except Exception as exc:
        print(f"Warning: NLI pipeline '{model_name}' failed to load: {exc}", file=sys.stderr)
        _FAILED_MODELS.add(key)
        return None
