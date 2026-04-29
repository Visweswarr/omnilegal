# Implementation Tasks

- [x] Create `pages/2_📂_Corpus_Explorer.py`
    - [x] Implement FAISS docstore inspection logic
    - [x] Optimize: Use `NoOpEmbeddings` to avoid heavy model load
    - [x] Robustness: Use `regex=False` in search to prevent crashes
    - [x] UI: Truncate "Text Snippet" in dataframe for better readability
    - [x] Create search and metadata filters (source, jurisdiction, page)
    - [x] Display source file status from `config.py`
- [x] Create `pages/1_👑_Supreme_Omni_Model.py`
    - [x] Implement orchestration logic using `st.status`
    - [x] Call `retrieve_passages`, `answer_question`, `run_model_council`, and `build_debate_card`
    - [x] Grounding: Update synthesis prompt to include and require citations
    - [x] Build tabbed UI for multiple model outputs
    - [x] Cleanup: Use `answer_question` in UI
- [x] Update `app.py`
    - [x] Update landing page description and metrics
- [x] Verification
    - [x] Verify Page 1 synthesis prompt includes [Source, Page] citation requirements
    - [x] Verify Page 2 snippet truncation and regex-safe search

## All-Corpus Knowledge Upgrade

- [x] Add curated corpus catalog with normalized record metadata
- [x] Add JSON/JSONL, CSV, XLSX, TXT, TXT-directory, and PDF ingestion paths
- [x] Add collection-aware FAISS build/load path
- [x] Add filter-aware multi-collection retrieval
- [x] Update Corpus Explorer for collection, source repo, language, jurisdiction, and task-family filters
- [x] Add retrieval smoke evaluation CLI
- [x] Add reranker training triple preparation and Hugging Face Jobs payload scaffolding
- [x] Add Kaggle/Colab reranker training script and model-selection runbook
- [x] Add optional Gemma 4 SFT dataset preparation and Kaggle/Colab QLoRA script
- [x] Build sample local collection indices for `core_legal_en`, `eu_multilingual`, and `cn_legal`
- [x] Add smoke tests for catalog normalization, XLSX loading, metadata filters, and reranker script generation
