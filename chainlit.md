# OmniLegal — Legal Research Console

A grounded, persona-aware research console for **international, comparative, and jurisdiction-specific** legal questions.

## Personas

| Persona | Voice | Best for |
|---------|-------|----------|
| **Tourist** | Plain English, action-oriented | Travellers, expats, on-the-ground rights |
| **Law Student** | Strict IRAC with citations | Memos, moots, exam practice |
| **Researcher** | Doctrinal, comparative, deep | Policy work, scholarship, treaty analysis |
| **Layman** | Conversational, no jargon | Anyone curious without legal training |

## How it works

1. **Retrieve.** Hybrid dense + lexical search over an indexed corpus that includes Malcolm Shaw's *International Law*, the UN Charter, ICCPR, ICESCR, the Constitution of India, and a curated case-law catalog.
2. **Synthesize.** Persona-tuned prompt + Claude Sonnet 4.5 (Emergent universal key) draft a `[S#]`-grounded answer.
3. **Verify.** Citation grading + repair pass; if retrieval is sparse, **Gemini 2.5 Flash** automatically fills in as the always-on knowledge fallback (transparently labelled).

## Try it

- *I'm an Indian citizen stopped by traffic police in Russia. What are my rights?* — Tourist mode
- *Brief Tinoco Arbitration on state recognition.* — Law Student mode
- *Compare extraterritorial jurisdiction doctrine in the US, EU and India.* — Researcher mode
- *Explain jus cogens like I'm five.* — Layman mode

---

*This tool provides legal **information** for research purposes only — not legal advice. Outputs may contain errors even when citations are provided. Always verify every source directly. This system does not create an attorney-client relationship. Consult a qualified lawyer licensed in the relevant jurisdiction before acting.*
