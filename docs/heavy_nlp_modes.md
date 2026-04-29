# Heavy NLP Modes

OmniLegal implements a graceful-degradation strategy for heavy machine learning and NLP components. By default, the system boots into "light mode," which is fast, strictly heuristic-based, and crash-proof. 

You can enable more robust feature flags to toggle the following NLP tools sequentially. These are loaded efficiently thanks to a centralized loader (`src/models/heavy_nlp.py`). 

## Flags and Fallbacks

1. **Master Switch**
   - `OMNILEGAL_ENABLE_HEAVY_MODELS`: Master toggle. Setting this to `0` forcibly bypasses all heavy components, keeping the system lightweight for local debugging and Chainlit interaction. If enabled, the granular toggles below determine the specific capabilities active in the pipeline.

2. **Component Granularity**

| HEAVY COMPONENT | DEFAULT MODE | ENABLE FLAG | LIGHT FALLBACK | LOAD STRATEGY |
|---|---|---|---|---|
| spaCy legal NER | Disabled | `OMNILEGAL_ENABLE_LEGAL_NER` | Exact regex substring scan & Conceptual fuzzy match | Tries `en_legal_ner_trf`, falls back to `en_core_web_sm`, cleanly degrades. |
| GLiNER | Disabled | `OMNILEGAL_ENABLE_GLINER` | Skips broad entity tagging but heuristic categorization continues | In-process instantiation. Registers early failures so loop-invocations skip repeated load retries. |
| Zero-shot classifier | Disabled | `OMNILEGAL_ENABLE_ZERO_SHOT` | Keyword and length analysis (Regex fallback rules) | HuggingFace pipeline (`DeBERTa`). Gracefully bypasses if `transformers` missing. |
| LLM entity extractor| Disabled | `OMNILEGAL_ENABLE_LLM_ENTITY_EXTRACTION` | Relies on internal heuristic jurisdiction/temporal analysis | Currently unused directly (reserved for explicit LLM extraction scaling). |
| NLI / entailment verifier | Disabled | `OMNILEGAL_ENABLE_NLI_VERIFIER` | String matching / `_lexical_support_ratio` comparison | Verifies the factual overlap. Fails softly returning `None` and falls back to text overlap rules. |

## Dependencies

Heavy models assume the presence of `torch`, `transformers`, `spacy`, and `gliner`. If you have the flags enabled but the libraries are missing, the system will *not* crash your application. Instead, it will output a warning describing the missing component and seamlessly degrade to the `LIGHT FALLBACK` logic documented above.
