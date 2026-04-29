"""Test all 7 precision fixes in retriever_node.py"""
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.pipeline.retriever_node import (
    _hard_filter_collections,
    _extract_key_terms,
    _extract_query_phrases,
    _compute_dynamic_min_overlap,
    _keyword_anchor_filter,
    _negative_keyword_penalty,
    _build_query_variants,
    _get_jurisdiction_filtered_synonyms,
    _enforce_source_diversity,
    _compute_retrieval_confidence,
)

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS: {name}")
        passed += 1
    else:
        print(f"  FAIL: {name} — {detail}")
        failed += 1


# ═══════════════════════════════════════════════════════════════════
# FIX 1: Dynamic min overlap
# ═══════════════════════════════════════════════════════════════════
print("FIX 1 — Dynamic min overlap")
terms_8 = {"speech", "india", "freedom", "expression", "article", "amendment", "first", "right"}
min_ov = _compute_dynamic_min_overlap(terms_8)
print(f"  8 terms -> min_overlap = {min_ov}")
test("8 terms -> min=max(2, 8*0.3)=max(2,2)=2", min_ov == 2)

terms_10 = terms_8 | {"constitutional", "fundamental"}
min_ov = _compute_dynamic_min_overlap(terms_10)
print(f"  10 terms -> min_overlap = {min_ov}")
test("10 terms -> min=max(2, 10*0.3)=3", min_ov == 3)

# Now prove "freedom of movement in canada" fails with dynamic overlap
key_terms = _extract_key_terms("freedom of speech in India", ["IN"])
print(f"  Key terms for 'freedom of speech in India': {key_terms}")
phrases = _extract_query_phrases("freedom of speech in India")
passages = [
    {"text": "freedom of movement in canada", "metadata": {}},
    {"text": "freedom of speech and expression under Article 19 in India", "metadata": {"collection": "NATIONAL_IN"}},
]
min_ov = _compute_dynamic_min_overlap(key_terms)
print(f"  Min overlap for {len(key_terms)} terms = {min_ov}")
filtered = _keyword_anchor_filter(passages, key_terms, phrases, "freedom of speech in India")
surviving = [h["text"][:40] for h in filtered]
print(f"  Surviving: {surviving}")
test("'freedom of movement' rejected (only 'freedom' overlap < min)", len(filtered) == 1, f"got {len(filtered)}: {surviving}")
test("Article 19 passage survived", any("Article 19" in h["text"] for h in filtered))


# ═══════════════════════════════════════════════════════════════════
# FIX 2: Jurisdiction-aware synonyms
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 2 — Jurisdiction-aware synonyms")

# India query: should get "article 19" but NOT "first amendment"
india_syns = _get_jurisdiction_filtered_synonyms("freedom of speech", ["IN"])
print(f"  India synonyms: {india_syns}")
test("'article 19' included for India", any("article 19" in s for s in india_syns))
test("'first amendment' excluded for India", all("first amendment" not in s for s in india_syns))

# US query: should get "first amendment" but NOT "article 19"
us_syns = _get_jurisdiction_filtered_synonyms("freedom of speech", ["US"])
print(f"  US synonyms: {us_syns}")
test("'first amendment' included for US", any("first amendment" in s for s in us_syns))
test("'article 19' excluded for US", all("article 19" not in s for s in us_syns))

# No jurisdiction: only universal
no_jur_syns = _get_jurisdiction_filtered_synonyms("freedom of speech", [])
print(f"  No-jurisdiction synonyms: {no_jur_syns}")
test("Only universal syns returned", all("amendment" not in s and "article 19" not in s for s in no_jur_syns))

# Key terms should reflect jurisdiction
india_terms = _extract_key_terms("freedom of speech in India", ["IN"])
us_terms = _extract_key_terms("freedom of speech in US", ["US"])
test("India terms include 'article' (from article 19)", "article" in india_terms)
test("India terms exclude 'amendment'", "amendment" not in india_terms)
test("US terms include 'amendment'", "amendment" in us_terms)

# Query variants also jurisdiction-aware
india_variants = _build_query_variants("freedom of speech in India", ["conceptual"], ["IN"])
print(f"  India query variants:")
for v in india_variants:
    print(f'    "{v}"')
test("No 'first amendment' in India variants", all("first amendment" not in v for v in india_variants))
test("Has 'article 19' in India variants", any("article 19" in v for v in india_variants))


# ═══════════════════════════════════════════════════════════════════
# FIX 3: Phrase-level matching
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 3 — Phrase-level matching")
phrases = _extract_query_phrases("what is erga omnes in international law")
print(f"  Phrases: {phrases}")
test("'erga omnes' detected as phrase", "erga omnes" in phrases)

# Phrase match should boost survival even with low word overlap
key_terms = _extract_key_terms("what is erga omnes", [])
phrases = _extract_query_phrases("what is erga omnes")
passages = [
    # Has exact phrase match
    {"text": "The concept of erga omnes was established by the ICJ", "metadata": {}},
    # Has only word 'erga' + 'omnes' separately (still matches)
    {"text": "erga omnes obligations are fundamental in international law", "metadata": {}},
]
filtered = _keyword_anchor_filter(passages, key_terms, phrases, "what is erga omnes")
test("Both passages survive (phrase boost)", len(filtered) == 2, f"got {len(filtered)}")
if filtered:
    test("First passage has phrase_bonus", filtered[0].get("phrase_bonus", 0) > 0)


# ═══════════════════════════════════════════════════════════════════
# FIX 4: Source diversity
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 4 — Source diversity enforcement")
passages = [
    {"text": "Shaw chapter 1" + "x" * 80, "score": 0.9, "metadata": {"collection": "SHAW_PRIVATE", "doc_type": "textbook"}},
    {"text": "Shaw chapter 2" + "x" * 80, "score": 0.85, "metadata": {"collection": "SHAW_PRIVATE", "doc_type": "textbook"}},
    {"text": "Shaw chapter 3" + "x" * 80, "score": 0.8, "metadata": {"collection": "SHAW_PRIVATE", "doc_type": "textbook"}},
    {"text": "ICJ case holding" + "x" * 80, "score": 0.5, "metadata": {"collection": "CASE_LAW", "doc_type": "case_law"}},
    {"text": "ICCPR article text" + "x" * 80, "score": 0.4, "metadata": {"collection": "INTL_TREATIES", "doc_type": "treaty"}},
]
diverse = _enforce_source_diversity(passages)
diverse_types = [p["metadata"].get("doc_type", "") for p in diverse]
print(f"  Before diversity: {[p['metadata'].get('doc_type') for p in passages]}")
print(f"  After diversity: {diverse_types}")
test("Has textbook passage", "textbook" in diverse_types)
test("Has case_law passage", "case_law" in diverse_types)
test("Has treaty passage", "treaty" in diverse_types)
test("Total count preserved", len(diverse) == len(passages))


# ═══════════════════════════════════════════════════════════════════
# FIX 5: Negative keyword filtering
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 5 — Negative keyword penalty")
penalty = _negative_keyword_penalty("freedom of speech in india", "property tax assessment and zoning")
print(f"  'freedom of speech' + 'property tax zoning' text -> penalty = {penalty}")
test("Strong penalty (2 neg terms)", penalty <= -5.0)

penalty_clean = _negative_keyword_penalty("freedom of speech in india", "right to expression under constitution")
print(f"  'freedom of speech' + clean text -> penalty = {penalty_clean}")
test("No penalty for clean passage", penalty_clean == 0.0)

penalty_single = _negative_keyword_penalty("freedom of speech in india", "property rights under constitution")
print(f"  'freedom of speech' + 'property' text -> penalty = {penalty_single}")
test("Moderate penalty (1 neg term)", penalty_single == -2.0)


# ═══════════════════════════════════════════════════════════════════
# FIX 6: Confidence scoring
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 6 — Confidence scoring")

# Good retrieval
good_passages = [
    {"text": "...", "score": 0.8, "term_overlap": 5},
    {"text": "...", "score": 0.7, "term_overlap": 4},
    {"text": "...", "score": 0.6, "term_overlap": 3},
]
conf = _compute_retrieval_confidence(good_passages, {"a", "b", "c", "d", "e"})
print(f"  Good retrieval: level={conf['level']}, score={conf['score']}")
test("High confidence for good retrieval", conf["level"] == "high")

# Bad retrieval
bad_passages = [
    {"text": "...", "score": 0.1, "term_overlap": 1},
]
conf_bad = _compute_retrieval_confidence(bad_passages, {"a", "b", "c", "d", "e", "f", "g", "h"})
print(f"  Bad retrieval: level={conf_bad['level']}, score={conf_bad['score']}")
test("Low confidence for bad retrieval", conf_bad["level"] == "low")

# Empty retrieval
conf_empty = _compute_retrieval_confidence([], {"a", "b"})
test("Low confidence for empty", conf_empty["level"] == "low" and conf_empty["score"] == 0.0)


# ═══════════════════════════════════════════════════════════════════
# FIX 7: Explainability
# ═══════════════════════════════════════════════════════════════════
print("\nFIX 7 — Explainability (selection_reason)")
key_terms = _extract_key_terms("freedom of speech in India", ["IN"])
phrases = _extract_query_phrases("freedom of speech in India")
passages = [
    {"text": "Article 19 guarantees freedom of speech and expression in India", "metadata": {"collection": "NATIONAL_IN"}},
]
filtered = _keyword_anchor_filter(passages, key_terms, phrases, "freedom of speech in India")
if filtered:
    reason = filtered[0].get("selection_reason", "")
    print(f"  Reason: {reason}")
    test("Has selection_reason", bool(reason))
    test("Reason mentions matched terms", "matched" in reason)
    test("Reason mentions phrases", "phrases" in reason)
    test("Reason mentions collection", "collection" in reason)
else:
    test("Passage survived anchor filter", False, "was filtered out")


# ═══════════════════════════════════════════════════════════════════
# INTEGRATION: Full pipeline simulation
# ═══════════════════════════════════════════════════════════════════
print("\n=== INTEGRATION: Full scenario simulation ===")
print("\nScenario: 'freedom of speech in India'")
key_terms = _extract_key_terms("freedom of speech in India", ["IN"])
phrases = _extract_query_phrases("freedom of speech in India")
print(f"  Key terms ({len(key_terms)}): {key_terms}")
print(f"  Phrases: {phrases}")
print(f"  Min overlap: {_compute_dynamic_min_overlap(key_terms)}")
test("No 'amendment' (US-only)", "amendment" not in key_terms)
test("Has 'article' (India's article 19)", "article" in key_terms)

passages = [
    {"text": "Article 19(1)(a) guarantees freedom of speech and expression to all citizens of India", "metadata": {"collection": "NATIONAL_IN", "jurisdiction": "in"}},
    {"text": "Freedom of expression is a fundamental right under the Indian Constitution", "metadata": {"collection": "COMMENTARY", "doc_type": "commentary"}},
    {"text": "California First Amendment case on property rights and free press", "metadata": {"collection": "CASE_LAW", "jurisdiction": "us"}},
    {"text": "NATO defense expenditure analysis report 2024", "metadata": {"source_name": "NATO"}},
    {"text": "Freedom of movement in Canadian immigration policy", "metadata": {"collection": "NATIONAL_CA"}},
    {"text": "Tax assessment property valuation methods freedom clause", "metadata": {"collection": "COMMENTARY"}},
]

filtered = _keyword_anchor_filter(passages, key_terms, phrases, "freedom of speech in India")
surviving = [(h["text"][:50], h.get("term_overlap"), h.get("neg_penalty")) for h in filtered]
print(f"\n  Survived anchor filter ({len(filtered)}/{len(passages)}):")
for text, ov, neg in surviving:
    print(f"    [{ov} terms, neg={neg}] {text}...")

test("Article 19 passage survived", any("Article 19" in h["text"] for h in filtered))
test("Commentary passage survived", any("fundamental right" in h["text"] for h in filtered))
test("California case rejected or penalized", not any("California" in h["text"] and h.get("neg_penalty", 0) == 0 for h in filtered))
test("NATO rejected", not any("NATO" in h["text"] for h in filtered))
test("Canadian freedom rejected (only 1 overlap)", not any("Canadian" in h["text"] for h in filtered))


# Summary
print(f"\n{'='*60}")
print(f"RESULTS: {passed} passed, {failed} failed")
if failed:
    sys.exit(1)
