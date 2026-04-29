import os
from pathlib import Path

from src.env import load_environment

load_environment()

# Paths
ROOT_DIR = Path(__file__).parent.parent.parent  # NLP Legal Summarizer/
OMNILEGAL_DIR = ROOT_DIR / "omnilegal"

DATA_DIR = OMNILEGAL_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpus"
VECTOR_DB_DIR = DATA_DIR / "vector_db"
QDRANT_STORAGE_DIR = DATA_DIR / "qdrant_storage"
QDRANT_EMBEDDED_DIR = DATA_DIR / "qdrant_embedded"
CASELAWS_DIR = OMNILEGAL_DIR / "caselaws"
REMOTE_SOURCES_DIR = DATA_DIR / "remote_sources"
LOCAL_REFERENCES_DIR = DATA_DIR / "local_references"

os.makedirs(CORPUS_DIR, exist_ok=True)
os.makedirs(VECTOR_DB_DIR, exist_ok=True)
os.makedirs(QDRANT_EMBEDDED_DIR, exist_ok=True)
os.makedirs(REMOTE_SOURCES_DIR, exist_ok=True)
os.makedirs(LOCAL_REFERENCES_DIR, exist_ok=True)

# Source documents
CORPUS_FILES = {
    "indian_constitution": ROOT_DIR / "Indian Constitutition.pdf",
    "un_charter": ROOT_DIR / "uncharter.pdf",
    "iccpr": ROOT_DIR / "ccpr.pdf",
    "icescr": ROOT_DIR / "cescr.pdf",
    "malcolm_shaw": ROOT_DIR / "International Law (Malcolm N. Shaw).pdf",
}
CASE_LAW_JSONL = ROOT_DIR / "case_with_all_sources_with_companion_cases_tag.jsonl"


def get_available_corpus_files() -> dict[str, Path]:
    return {k: v for k, v in CORPUS_FILES.items() if v.exists()}


# Qdrant collections
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OMNILEGAL_VECTOR_BACKEND = os.getenv("OMNILEGAL_VECTOR_BACKEND", "server_qdrant").lower().replace("-", "_")
OMNILEGAL_QDRANT_EMBEDDED_PATH = Path(
    os.getenv("OMNILEGAL_QDRANT_EMBEDDED_PATH", str(QDRANT_EMBEDDED_DIR))
)
COLLECTION_INTL_TREATIES = "INTL_TREATIES"
COLLECTION_NATIONAL_IN = "NATIONAL_IN"
COLLECTION_NATIONAL_US = "NATIONAL_US"
COLLECTION_NATIONAL_UK = "NATIONAL_UK"
COLLECTION_NATIONAL_EU = "NATIONAL_EU"
COLLECTION_NATIONAL_RU = "NATIONAL_RU"
COLLECTION_NATIONAL_IL = "NATIONAL_IL"
COLLECTION_CASE_LAW = "CASE_LAW"
COLLECTION_SHAW_PRIVATE = "SHAW_PRIVATE"
COLLECTION_SHAW = COLLECTION_SHAW_PRIVATE  # Backward-compat alias.
COLLECTION_COMMENTARY = "COMMENTARY"
COLLECTION_REFERENCE_DATASET = "REFERENCE_DATASET"
COLLECTION_REFERENCE_DATASET_GLOBAL = "REFERENCE_DATASET_GLOBAL"
COLLECTION_REFERENCE_DATASET_EU = "REFERENCE_DATASET_EU"

# Granular production collections.  Legacy collection names above remain
# compatibility aliases; new ingestion should target these physical collections.
COLLECTION_CASE_LAW_GLOBAL = "CASE_LAW_GLOBAL"
COLLECTION_CASE_LAW_US = "CASE_LAW_US"
COLLECTION_CASE_LAW_IN = "CASE_LAW_IN"
COLLECTION_CASE_LAW_EU = "CASE_LAW_EU"
COLLECTION_CASE_LAW_UK = "CASE_LAW_UK"
COLLECTION_CASE_LAW_RU = "CASE_LAW_RU"
COLLECTION_CASE_LAW_IL = "CASE_LAW_IL"

COLLECTION_STATUTES_US = "STATUTES_US"
COLLECTION_STATUTES_IN = "STATUTES_IN"
COLLECTION_STATUTES_EU = "STATUTES_EU"
COLLECTION_STATUTES_UK = "STATUTES_UK"
COLLECTION_STATUTES_RU = "STATUTES_RU"
COLLECTION_STATUTES_IL = "STATUTES_IL"

COLLECTION_COMMENTARY_GLOBAL = "COMMENTARY_GLOBAL"

CASE_LAW_COLLECTIONS = [
    COLLECTION_CASE_LAW_GLOBAL,
    COLLECTION_CASE_LAW_US,
    COLLECTION_CASE_LAW_IN,
    COLLECTION_CASE_LAW_EU,
    COLLECTION_CASE_LAW_UK,
    COLLECTION_CASE_LAW_RU,
    COLLECTION_CASE_LAW_IL,
]

STATUTE_COLLECTIONS = [
    COLLECTION_STATUTES_US,
    COLLECTION_STATUTES_IN,
    COLLECTION_STATUTES_EU,
    COLLECTION_STATUTES_UK,
    COLLECTION_STATUTES_RU,
    COLLECTION_STATUTES_IL,
]

GRANULAR_COLLECTIONS = CASE_LAW_COLLECTIONS + STATUTE_COLLECTIONS + [COLLECTION_COMMENTARY_GLOBAL]

COLLECTION_ALIAS_MAP: dict[str, list[str]] = {
    COLLECTION_CASE_LAW: CASE_LAW_COLLECTIONS,
    COLLECTION_COMMENTARY: [COLLECTION_COMMENTARY_GLOBAL],
    COLLECTION_NATIONAL_US: [COLLECTION_STATUTES_US, COLLECTION_CASE_LAW_US],
    COLLECTION_NATIONAL_IN: [COLLECTION_NATIONAL_IN, COLLECTION_STATUTES_IN, COLLECTION_CASE_LAW_IN],
    COLLECTION_NATIONAL_UK: [COLLECTION_STATUTES_UK, COLLECTION_CASE_LAW_UK],
    COLLECTION_NATIONAL_EU: [COLLECTION_STATUTES_EU, COLLECTION_CASE_LAW_EU],
    COLLECTION_NATIONAL_RU: [COLLECTION_STATUTES_RU, COLLECTION_CASE_LAW_RU],
    COLLECTION_NATIONAL_IL: [COLLECTION_STATUTES_IL, COLLECTION_CASE_LAW_IL],
    COLLECTION_REFERENCE_DATASET: [COLLECTION_REFERENCE_DATASET_GLOBAL, COLLECTION_REFERENCE_DATASET_EU],
}

PRESERVED_CORPUS_COLLECTIONS = [
    COLLECTION_INTL_TREATIES,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_NATIONAL_IN,
]

POLLUTED_COLLECTIONS_TO_REBUILD = [
    COLLECTION_COMMENTARY,
    COLLECTION_NATIONAL_US,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_RU,
    COLLECTION_CASE_LAW,
]

ALL_COLLECTIONS = [
    COLLECTION_INTL_TREATIES,
    COLLECTION_NATIONAL_IN,
    COLLECTION_NATIONAL_US,
    COLLECTION_NATIONAL_UK,
    COLLECTION_NATIONAL_EU,
    COLLECTION_NATIONAL_RU,
    COLLECTION_NATIONAL_IL,
    COLLECTION_CASE_LAW,
    COLLECTION_SHAW_PRIVATE,
    COLLECTION_COMMENTARY,
    COLLECTION_REFERENCE_DATASET,
    COLLECTION_REFERENCE_DATASET_GLOBAL,
    COLLECTION_REFERENCE_DATASET_EU,
    *GRANULAR_COLLECTIONS,
]

# Which source files belong to which collection
COLLECTION_SOURCES: dict[str, list[str]] = {
    COLLECTION_INTL_TREATIES: ["un_charter", "iccpr", "icescr"],
    COLLECTION_NATIONAL_IN: ["indian_constitution"],
    COLLECTION_SHAW_PRIVATE: ["malcolm_shaw"],
}

# Embedding / reranker models
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
RERANKER = os.getenv("RERANKER", "BAAI/bge-reranker-v2-m3")
EMBEDDING_MODEL = EMBED_MODEL
RERANKER_MODEL = RERANKER
EMBEDDING_DIM = 1024

# Classification / NER models
CLASSIFIER_MODEL = "MoritzLaurer/deberta-v3-large-zeroshot-v2.0-c"
SPACY_NER_MODEL = os.getenv("SPACY_NER_MODEL", "en_legal_ner_trf")
SPACY_FALLBACK_MODEL = "en_core_web_sm"
GLINER_MODEL = "urchade/gliner_multi-v2.1"
NLI_MODEL = os.getenv("NLI_MODEL", "vectara/hallucination_evaluation_model")

# LLM
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_REFINER_MODEL = os.getenv("GEMINI_REFINER_MODEL", "gemini-2.5-flash-lite")
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-2.5-flash").split(",")
    if model.strip()
]
GEMINI_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS", "8"))
OMNILEGAL_ENABLE_GEMINI_FALLBACK = os.getenv("OMNILEGAL_ENABLE_GEMINI_FALLBACK", "1").lower() in {"1", "true", "yes"}
OMNILEGAL_GEMINI_FALLBACK_MODEL = os.getenv("OMNILEGAL_GEMINI_FALLBACK_MODEL", GEMINI_REFINER_MODEL)
OMNILEGAL_GEMINI_FALLBACK_MAX_CALLS_PER_HOUR = int(os.getenv("OMNILEGAL_GEMINI_FALLBACK_MAX_CALLS_PER_HOUR", "60"))
OMNILEGAL_GEMINI_FALLBACK_CACHE_PATH = os.getenv(
    "OMNILEGAL_GEMINI_FALLBACK_CACHE_PATH",
    str(OMNILEGAL_DIR / "artifacts" / "cache" / "gemini_fallback.sqlite"),
)
HF_TOKEN = os.getenv("HF_TOKEN", "")
OMNILEGAL_ENABLE_HF_PROVIDER = os.getenv("OMNILEGAL_ENABLE_HF_PROVIDER", "0").lower() in {"1", "true", "yes"}
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
_RAW_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
if not OPENAI_BASE_URL:
    if OPENROUTER_API_KEY or _RAW_OPENAI_API_KEY.startswith("sk-or-"):
        OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
    else:
        OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_API_KEY = (
    OPENROUTER_API_KEY
    if "openrouter.ai" in OPENAI_BASE_URL and OPENROUTER_API_KEY
    else (_RAW_OPENAI_API_KEY or OPENROUTER_API_KEY)
)
OPENAI_MODEL = os.getenv("OPENAI_MODEL", os.getenv("OMNILEGAL_OPENAI_MODEL", "")).strip()
OPENROUTER_PREFER_FREE_MODELS = os.getenv(
    "OPENROUTER_PREFER_FREE_MODELS",
    "1" if "openrouter.ai" in OPENAI_BASE_URL else "0",
).lower() in {"1", "true", "yes"}
OPENROUTER_FREE_MODEL_CANDIDATES = [
    model.strip()
    for model in os.getenv(
        "OPENROUTER_FREE_MODEL_CANDIDATES",
        (
            "minimax/minimax-m2.5:free,"
            "openai/gpt-oss-120b:free,"
            "nvidia/nemotron-3-super-120b-a12b:free,"
            "google/gemma-4-31b-it:free,"
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free,"
            "google/gemma-4-26b-a4b-it:free,"
            "qwen/qwen3-next-80b-a3b-instruct:free,"
            "qwen/qwen3-coder:free,"
            "openrouter/free"
        ),
    ).split(",")
    if model.strip()
]
OPENAI_MODEL_CANDIDATES = [
    model.strip()
    for model in os.getenv(
        "OPENAI_MODEL_CANDIDATES",
        (
            "~openai/gpt-latest,openai/gpt-5.5,openai/gpt-5.5-pro,"
            "~anthropic/claude-sonnet-latest,~google/gemini-pro-latest,"
            "openai/gpt-5.1,gpt-5.1,openai/gpt-5,gpt-5,"
            "anthropic/claude-sonnet-4.5,google/gemini-2.5-pro,"
            "deepseek/deepseek-v4-pro,deepseek/deepseek-r1,openai/o3,o3,"
            "openai/gpt-4.1,gpt-4.1"
        ),
    ).split(",")
    if model.strip()
]
OPENAI_COMPAT_MAX_MODELS = max(
    1,
    int(os.getenv("OMNILEGAL_OPENAI_MAX_MODELS", "4" if "openrouter.ai" in OPENAI_BASE_URL else "1")),
)
HF_INFERENCE_BASE_URL = os.getenv("HF_INFERENCE_BASE_URL", "https://router.huggingface.co/v1")
HF_INFERENCE_MODEL = os.getenv(
    "HF_INFERENCE_MODEL",
    "",
).strip()
DATAGOV_API_KEY = os.getenv("DATAGOV_API_KEY", "")
COURTLISTENER_TOKEN = os.getenv("COURTLISTENER_TOKEN", "")
GOVINFO_API_KEY = os.getenv("GOVINFO_API_KEY", "") or DATAGOV_API_KEY
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY", "") or DATAGOV_API_KEY
INDIAN_KANOON_API_TOKEN = (
    os.getenv("INDIAN_KANOON_API_TOKEN", "")
    or os.getenv("INDIAN_KANOON_API_KEY", "")
)
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "")
PISTE_API_KEY = os.getenv("PISTE_API_KEY", "")
PISTE_API_SECRET = os.getenv("PISTE_API_SECRET", "")
PISTE_CLIENT_ID = os.getenv("PISTE_CLIENT_ID", "")
PISTE_CLIENT_SECRET = os.getenv("PISTE_CLIENT_SECRET", "")
PISTE_ENV = os.getenv("PISTE_ENV", "production").strip().lower()
PISTE_OAUTH_URL = os.getenv(
    "PISTE_OAUTH_URL",
    "https://sandbox-oauth.piste.gouv.fr/api/oauth/token"
    if PISTE_ENV == "sandbox"
    else "https://oauth.piste.gouv.fr/api/oauth/token",
)
PISTE_API_BASE_URL = os.getenv(
    "PISTE_API_BASE_URL",
    "https://sandbox-api.piste.gouv.fr" if PISTE_ENV == "sandbox" else "https://api.piste.gouv.fr",
)
DEEPL_API_KEY = os.getenv("DEEPL_API_KEY", "")
AZURE_TRANSLATOR_KEY = os.getenv("AZURE_TRANSLATOR_KEY", "")
AZURE_TRANSLATOR_REGION = os.getenv("AZURE_TRANSLATOR_REGION", "")
GOOGLE_TRANSLATE_KEY = os.getenv("GOOGLE_TRANSLATE_KEY", "")
LEGAL_GPT2_LOCAL_DIR = Path(os.getenv("LEGAL_GPT2_LOCAL_DIR", str(ROOT_DIR)))
LEGAL_GPT2_WEIGHTS = LEGAL_GPT2_LOCAL_DIR / "pytorch_model.bin"
LEGAL_GPT2_CONFIG = LEGAL_GPT2_LOCAL_DIR / "config.json"
LEGAL_GPT2_TOKENIZER_MODEL = os.getenv("LEGAL_GPT2_TOKENIZER_MODEL", "gpt2")
OMNILEGAL_ENABLE_LEGAL_GPT2_QUERY_ASSIST = os.getenv(
    "OMNILEGAL_ENABLE_LEGAL_GPT2_QUERY_ASSIST",
    "1" if LEGAL_GPT2_WEIGHTS.exists() and LEGAL_GPT2_CONFIG.exists() else "0",
).lower() in {"1", "true", "yes"}
OMNILEGAL_LEGAL_GPT2_MAX_NEW_TOKENS = int(os.getenv("OMNILEGAL_LEGAL_GPT2_MAX_NEW_TOKENS", "20"))
GROQ_LLM = os.getenv("GROQ_LLM", "llama-3.3-70b-versatile")
GROQ_MODEL = GROQ_LLM
LOCAL_LLM = os.getenv("LOCAL_LLM", "qwen2.5:7b-instruct-q4_K_M")
# HuggingFace seq2seq model for council Expert 2 (separate from the Ollama LOCAL_LLM)
COUNCIL_EXPERT_2_MODEL = os.getenv("COUNCIL_EXPERT_2_MODEL", "google/flan-t5-base")

# Local production controls
OMNILEGAL_PRIVATE_CORPUS = os.getenv("OMNILEGAL_PRIVATE_CORPUS", "1").lower() not in {"0", "false", "no"}
OMNILEGAL_LOG_RETENTION_DAYS = int(os.getenv("OMNILEGAL_LOG_RETENTION_DAYS", "30"))
OMNILEGAL_QUALITY_MODE = os.getenv("OMNILEGAL_QUALITY_MODE", "quality_first").lower().replace("-", "_")

# Answer mode
OMNILEGAL_DEFAULT_ANSWER_MODE = os.getenv("OMNILEGAL_DEFAULT_ANSWER_MODE", "tourist_practical")

# Council configuration
OMNILEGAL_COUNCIL_DRAFTER_COUNT = int(os.getenv("OMNILEGAL_COUNCIL_DRAFTER_COUNT", "3"))
OMNILEGAL_COUNCIL_TIMEOUT_SECONDS = int(os.getenv("OMNILEGAL_COUNCIL_TIMEOUT_SECONDS", "30"))
OMNILEGAL_COUNCIL_ANONYMIZE = os.getenv("OMNILEGAL_COUNCIL_ANONYMIZE", "1").lower() in {"1", "true", "yes"}

# Retrieval deadlines
OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS = int(os.getenv("OMNILEGAL_RETRIEVAL_DEADLINE_SECONDS", "40"))
OMNILEGAL_SIMPLE_QUERY_DEADLINE_SECONDS = int(os.getenv("OMNILEGAL_SIMPLE_QUERY_DEADLINE_SECONDS", "12"))

# Embedding cache
OMNILEGAL_EMBEDDING_CACHE_PATH = os.getenv(
    "OMNILEGAL_EMBEDDING_CACHE_PATH",
    str(OMNILEGAL_DIR / "artifacts" / "cache" / "query_embeddings.sqlite"),
)

# Ollama
OMNILEGAL_OLLAMA_BASE_URL = os.getenv("OMNILEGAL_OLLAMA_BASE_URL", "http://localhost:11434")
OMNILEGAL_OLLAMA_MODEL = os.getenv("OMNILEGAL_OLLAMA_MODEL", "qwen2.5:7b-instruct")
OMNILEGAL_USE_DENSE_RETRIEVAL = os.getenv("OMNILEGAL_USE_DENSE_RETRIEVAL", "1").lower() in {"1", "true", "yes"}
OMNILEGAL_ENABLE_HEAVY_MODELS = os.getenv(
    "OMNILEGAL_ENABLE_HEAVY_MODELS",
    "0",
).lower() in {"1", "true", "yes"}

# DSPy Integration
OMNILEGAL_ENABLE_DSPY = os.getenv("OMNILEGAL_ENABLE_DSPY", "0").lower() in {"1", "true", "yes"}
OMNILEGAL_DSPY_USE_COMPILED = os.getenv("OMNILEGAL_DSPY_USE_COMPILED", "1").lower() in {"1", "true", "yes"}
OMNILEGAL_DSPY_COMPILED_PATH = os.getenv("OMNILEGAL_DSPY_COMPILED_PATH", str(OMNILEGAL_DIR / "artifacts" / "dspy" / "jurisdiction_tuned.json"))
OMNILEGAL_DSPY_TRAIN_DATA = os.getenv("OMNILEGAL_DSPY_TRAIN_DATA", str(OMNILEGAL_DIR / "data" / "dspy" / "train.jsonl"))
OMNILEGAL_DSPY_EVAL_DATA = os.getenv("OMNILEGAL_DSPY_EVAL_DATA", str(OMNILEGAL_DIR / "data" / "dspy" / "eval.jsonl"))

# Contextual Retrieval Layer
OMNILEGAL_ENABLE_CONTEXTUAL_RETRIEVAL = os.getenv("OMNILEGAL_ENABLE_CONTEXTUAL_RETRIEVAL", "1").lower() in {"1", "true", "yes"}
OMNILEGAL_CONTEXTUAL_PROVIDER = os.getenv("OMNILEGAL_CONTEXTUAL_PROVIDER", "gemini").lower()
OMNILEGAL_CONTEXTUAL_MODEL = os.getenv("OMNILEGAL_CONTEXTUAL_MODEL", "gemini-2.5-flash-lite")
OMNILEGAL_CONTEXTUAL_CACHE_DIR = os.getenv("OMNILEGAL_CONTEXTUAL_CACHE_DIR", str(OMNILEGAL_DIR / "artifacts" / "cache" / "contextual_summaries.sqlite"))
OMNILEGAL_CONTEXTUAL_MAX_DOC_CHARS = int(os.getenv("OMNILEGAL_CONTEXTUAL_MAX_DOC_CHARS", "30000"))
OMNILEGAL_CONTEXTUAL_SUMMARY_TARGET_TOKENS = int(os.getenv("OMNILEGAL_CONTEXTUAL_SUMMARY_TARGET_TOKENS", "100"))

# Fine-grained NLP toggles (override master switch if explicitly modified later, but default to master switch logic here)
OMNILEGAL_ENABLE_LEGAL_NER = os.getenv("OMNILEGAL_ENABLE_LEGAL_NER", str(OMNILEGAL_ENABLE_HEAVY_MODELS)).lower() in {"1", "true", "yes"}
OMNILEGAL_ENABLE_ZERO_SHOT = os.getenv("OMNILEGAL_ENABLE_ZERO_SHOT", str(OMNILEGAL_ENABLE_HEAVY_MODELS)).lower() in {"1", "true", "yes"}
OMNILEGAL_ENABLE_GLINER = os.getenv("OMNILEGAL_ENABLE_GLINER", str(OMNILEGAL_ENABLE_HEAVY_MODELS)).lower() in {"1", "true", "yes"}
OMNILEGAL_ENABLE_LLM_ENTITY_EXTRACTION = os.getenv("OMNILEGAL_ENABLE_LLM_ENTITY_EXTRACTION", "0").lower() in {"1", "true", "yes"}
OMNILEGAL_ENABLE_NLI_VERIFIER = os.getenv("OMNILEGAL_ENABLE_NLI_VERIFIER", str(OMNILEGAL_ENABLE_HEAVY_MODELS)).lower() in {"1", "true", "yes"}

OMNILEGAL_ENABLE_CITATION_SELF_CRITIQUE = os.getenv(
    "OMNILEGAL_ENABLE_CITATION_SELF_CRITIQUE",
    "0",
).lower() in {"1", "true", "yes"}
GROQ_REQUEST_TIMEOUT_SECONDS = float(os.getenv("GROQ_REQUEST_TIMEOUT_SECONDS", "8"))
CHAINLIT_STEP_TIMEOUT_SECONDS = int(os.getenv("CHAINLIT_STEP_TIMEOUT_SECONDS", "180"))
LANGFUSE_PUBLIC_KEY = os.getenv("LANGFUSE_PUBLIC_KEY", "")
LANGFUSE_SECRET_KEY = os.getenv("LANGFUSE_SECRET_KEY", "")
OMNILEGAL_REMOTE_BUDGET_GB = float(os.getenv("OMNILEGAL_REMOTE_BUDGET_GB", "50"))
OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE = int(os.getenv("OMNILEGAL_REMOTE_MAX_ITEMS_PER_SOURCE", "10"))
OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP = int(os.getenv("OMNILEGAL_REMOTE_FULL_SOURCE_ITEM_CAP", "1000000"))
OMNILEGAL_REMOTE_MIN_FREE_GB = float(os.getenv("OMNILEGAL_REMOTE_MIN_FREE_GB", "20"))

REMOTE_LICENSE_GATES = {
    "UK_FIND_CASE_LAW_LICENSE_CONFIRMED": os.getenv("UK_FIND_CASE_LAW_LICENSE_CONFIRMED", ""),
    "ITLOS_PERMISSION_CONFIRMED": os.getenv("ITLOS_PERMISSION_CONFIRMED", ""),
    "ICRC_PERMISSION_CONFIRMED": os.getenv("ICRC_PERMISSION_CONFIRMED", ""),
    "PCA_PERMISSION_CONFIRMED": os.getenv("PCA_PERMISSION_CONFIRMED", ""),
    "HUDOC_PERMISSION_CONFIRMED": os.getenv("HUDOC_PERMISSION_CONFIRMED", ""),
    "ICC_LEGAL_TOOLS_PERMISSION_CONFIRMED": os.getenv("ICC_LEGAL_TOOLS_PERMISSION_CONFIRMED", ""),
    "ISRAEL_SUPREME_COURT_BULK_CONFIRMED": os.getenv("ISRAEL_SUPREME_COURT_BULK_CONFIRMED", ""),
}

LEGAL_RESEARCH_DISCLAIMER = (
    "*This tool provides legal information for research purposes only. "
    "It is not a substitute for advice from a qualified attorney. "
    "Outputs may contain errors even when citations are provided — always verify every source directly. "
    "This system does not create an attorney-client relationship. "
    "International law is complex and jurisdiction-specific; consult counsel licensed in the relevant jurisdiction before acting. "
    "Do not submit confidential or privileged information.*"
)

LEGAL_RESEARCH_SHORT_DISCLAIMER = (
    "This is not formal legal advice. Laws change and outcomes depend on specific facts. "
    "Consult a qualified lawyer in the relevant jurisdiction."
)

REQUIRED_RUNTIME_PACKAGES = [
    "chainlit",
    "qdrant_client",
    "langgraph",
    "groq",
    "spacy",
    "transformers",
    "FlagEmbedding",
    "gliner",
    "docling",
    "llama_index",
    "instructor",
    "dspy",
    "presidio_analyzer",
    "presidio_anonymizer",
    "anthropic",
    "ragas",
    "ollama",
    "langfuse",
    "gemini_sdk",
]

# Backward-compat aliases used by corpus_catalog.py and old CLI
DEFAULT_COLLECTIONS = ALL_COLLECTIONS
CHUNK_SIZE = 1024

# Chunking
TREATY_CHUNK_MAX_TOKENS = 1024
CASE_LAW_CHUNK_TOKENS = 700
SHAW_CHUNK_SIZES = [2048, 512, 128]
CHUNK_OVERLAP = 100

# Retrieval
RETRIEVAL_TOP_K_CANDIDATES = 50
RERANK_TOP_N = 10
RRF_K = 60

# Temporal scoring weights (Step 6)
TEMPORAL_ALPHA = 1.0   # rerank score
TEMPORAL_BETA = 0.15   # recency
TEMPORAL_GAMMA = 0.3   # landmark boost
TEMPORAL_DELTA = 0.2   # shaw_cited
TEMPORAL_EPSILON = 0.8  # overruled penalty

# Issue → collection routing table
ISSUE_COLLECTION_MAP: dict[str, list[str]] = {
    "use_of_force_jus_ad_bellum": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY, COLLECTION_NATIONAL_US],
    "ihl_jus_in_bello": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "human_rights": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "criminal_procedure": [
        COLLECTION_INTL_TREATIES,
        COLLECTION_COMMENTARY,
        COLLECTION_STATUTES_US,
        COLLECTION_STATUTES_IN,
        COLLECTION_STATUTES_UK,
        COLLECTION_STATUTES_RU,
        COLLECTION_STATUTES_IL,
        COLLECTION_CASE_LAW,
    ],
    "traffic_offences": [
        COLLECTION_INTL_TREATIES,
        COLLECTION_COMMENTARY,
        COLLECTION_STATUTES_US,
        COLLECTION_STATUTES_IN,
        COLLECTION_STATUTES_UK,
        COLLECTION_STATUTES_RU,
        COLLECTION_STATUTES_IL,
        COLLECTION_CASE_LAW,
    ],
    "immigration_and_mobility": [
        COLLECTION_INTL_TREATIES,
        COLLECTION_COMMENTARY,
        COLLECTION_STATUTES_US,
        COLLECTION_STATUTES_IN,
        COLLECTION_STATUTES_UK,
        COLLECTION_STATUTES_RU,
        COLLECTION_STATUTES_IL,
    ],
    "consular_assistance": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "law_of_the_sea": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW],
    "treaty_interpretation": [COLLECTION_INTL_TREATIES, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "state_responsibility": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "statehood_and_recognition": [COLLECTION_CASE_LAW, COLLECTION_INTL_TREATIES, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "named_case": [COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY, COLLECTION_INTL_TREATIES],
    "jurisdiction_and_immunity": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_NATIONAL_IN],
    "international_criminal_law": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW],
    "diplomatic_relations": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "international_environmental_law": [COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY],
    "trade_and_wto": [COLLECTION_INTL_TREATIES, COLLECTION_NATIONAL_EU, COLLECTION_COMMENTARY],
    "refugee_and_asylum": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "arms_control_and_disarmament": [COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY],
    "cyber_and_digital_law": [COLLECTION_INTL_TREATIES, COLLECTION_COMMENTARY],
    "general_international_law": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "erga_omnes_jus_cogens": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "territorial_sovereignty": [COLLECTION_INTL_TREATIES, COLLECTION_CASE_LAW, COLLECTION_SHAW_PRIVATE, COLLECTION_COMMENTARY],
    "default": [COLLECTION_INTL_TREATIES, COLLECTION_SHAW_PRIVATE, COLLECTION_CASE_LAW],
    "russia": [COLLECTION_NATIONAL_RU, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "ru": [COLLECTION_NATIONAL_RU, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "israel": [COLLECTION_NATIONAL_IL, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "il": [COLLECTION_NATIONAL_IL, COLLECTION_CASE_LAW, COLLECTION_COMMENTARY],
    "source_catalog": [COLLECTION_COMMENTARY, COLLECTION_CASE_LAW],
}

COLLECTION_PROFILES: dict[str, list[str]] = {
    "local-production": ALL_COLLECTIONS,
    "local-minimal": [COLLECTION_INTL_TREATIES, COLLECTION_NATIONAL_IN, COLLECTION_CASE_LAW_GLOBAL, COLLECTION_SHAW_PRIVATE],
}

# Phased remote ingestion: adapter labels grouped by build phase
INGESTION_PHASES: dict[int, list[str]] = {
    1: ["courtlistener_api", "cd_icj", "govinfo_api"],
    2: ["eurlex_cellar", "un_digital_library", "oai_pmh"],
    3: ["uk_legislation_api", "uk_find_caselaw", "india_aws_sc", "open_data_http"],
    4: ["ruslawod", "git_or_hf", "israel_versa"],
}
