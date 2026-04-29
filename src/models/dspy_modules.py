"""
DSPy Modules configuration and loader for OmniLegal.
This abstracts away the dependency on dspy while running in production nodes.
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from src.config import (
    GROQ_API_KEY,
    GROQ_MODEL,
    OMNILEGAL_DSPY_COMPILED_PATH,
    OMNILEGAL_DSPY_USE_COMPILED,
    OMNILEGAL_ENABLE_DSPY,
)

_dspy_lm_configured = False


def _configure_dspy() -> bool:
    """Initialize DSPy with the Groq LM."""
    global _dspy_lm_configured
    if _dspy_lm_configured:
        return True
    
    if not OMNILEGAL_ENABLE_DSPY or not GROQ_API_KEY:
        return False
        
    try:
        import dspy
    except ImportError:
        print("Warning: 'dspy-ai' library not installed. Disabling DSPy pipeline.", file=sys.stderr)
        return False

    try:
        lm = dspy.LM(f"groq/{GROQ_MODEL}", api_key=GROQ_API_KEY)
        dspy.configure(lm=lm)
        _dspy_lm_configured = True
        return True
    except Exception as exc:
        print(f"Warning: DSPy LM configuration failed: {exc}", file=sys.stderr)
        return False


def get_jurisdiction_signature() -> type:
    import dspy

    class JurisdictionAnalysisSignature(dspy.Signature):
        """Analyze the provided legal sources under the specified jurisdiction using the IRAC method. Do not invent rules or case names."""
        
        jurisdiction = dspy.InputField(desc="The target jurisdiction for this analysis")
        question = dspy.InputField(desc="The legal question to answer")
        context = dspy.InputField(desc="Relevant source passages to synthesize")
        
        applicable_rules = dspy.OutputField(desc="List of applicable legal rules, treaties, or precedents")
        application = dspy.OutputField(desc="Application of the rules to the specific facts/question")
        conclusion = dspy.OutputField(desc="Must be 'lawful', 'unlawful', 'indeterminate', or 'lawful_if_conditions'")
        conditions_if_any = dspy.OutputField(desc="Any required conditions if conditional")
        confidence = dspy.OutputField(desc="Confidence score float between 0.0 and 1.0")
        
    return JurisdictionAnalysisSignature


def get_jurisdiction_module() -> type:
    import dspy
    JurisdictionAnalysisSignature = get_jurisdiction_signature()
    
    class JurisdictionAnalyzer(dspy.Module):
        def __init__(self):
            super().__init__()
            # TypedPredictor maps directly to a JSON-like schema representation
            self.predictor = dspy.TypedPredictor(JurisdictionAnalysisSignature)
            
        def forward(self, jurisdiction: str, question: str, context: str):
            return self.predictor(jurisdiction=jurisdiction, question=question, context=context)
            
    return JurisdictionAnalyzer


@lru_cache(maxsize=1)
def load_jurisdiction_analyzer():
    """
    Returns an instantiated (and potentially compiled) DSPy Module for IRAC analysis.
    Returns None if DSPy is disabled or errors occur.
    """
    if not _configure_dspy():
        return None

    try:
        JurisdictionAnalyzer = get_jurisdiction_module()
        module = JurisdictionAnalyzer()
        
        if OMNILEGAL_DSPY_USE_COMPILED:
            path = Path(OMNILEGAL_DSPY_COMPILED_PATH)
            if path.exists():
                print(f"[DSPy Modes] Loading compiled analyzer from {path.name}", file=sys.stderr)
                module.load(str(path))
            else:
                print(f"[DSPy Modes] Compiled analyzer not found at {path.name}. Running uncompiled default prompt.", file=sys.stderr)
        else:
            print("[DSPy Modes] Compiled analyzer disabled in config. Running uncompiled default prompt.", file=sys.stderr)
            
        return module
    except Exception as exc:
        print(f"Warning: Failed to load DSPy JurisdictionAnalyzer: {exc}", file=sys.stderr)
        return None
