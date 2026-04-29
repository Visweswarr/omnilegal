# OmniLegal Codex — Quality-First Legal Research

**Multi-model council architecture**: parallel AI drafters → source critics → judge synthesis.

## Answer Modes (auto-detected)

| Mode | Best for |
|------|----------|
| 🌍 **Tourist / Practical** | Rights, steps, and what NOT to do — in plain language |
| 📚 **Law Student / Case Law** | IRAC analysis, case citations, procedural posture |
| ⚖️ **Comparative Research** | Side-by-side comparison across jurisdictions |
| 🔍 **Source Discovery** | Raw authority listing with tier classification |

## Example Queries

- *I am an Indian citizen stopped by traffic police in Russia. What are my rights?*
- *Explain BNS Section 69 and its implications*
- *Analyse the Tinoco Arbitration and its significance for state recognition*
- *Compare murder sentencing across US, UK, and India*
- *What laws should a tourist know before visiting Japan?*

## How it Works

1. **Query Analysis** — classifies intent, extracts entities and ISO codes
2. **Hybrid Retrieval** — hard-filtered vector search across 20+ legal collections with a 40s deadline
3. **Multi-Model Council** — 2–3 LLMs draft in parallel, then source critic + legal-risk critic review
4. **Citation Verification** — eyecite reporter matching + CourtListener API + retrieval cross-reference
5. **Judge Synthesis** — final authoritative answer removing any fabricated or unsupported claims

## Tips

- Upload a PDF to add it to your personal corpus (replaces nothing — additive only)
- Reply `SHORT` or `LONG` to adjust answer length after asking

---

*This tool provides legal **information** for research purposes only — not legal advice. Outputs may contain errors even when citations are provided. Always verify every source directly. This system does not create an attorney-client relationship. Consult a qualified lawyer licensed in the relevant jurisdiction before acting.*
