import React, { useState } from "react";
import { BookOpen, Send, ShieldCheck } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { askResearch } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

const PERSONAS = [
  { key: "researcher",        label: "Researcher",        blurb: "Footnote-dense academic analysis." },
  { key: "law_student",       label: "Law Student",       blurb: "Strict IRAC. Exam-ready." },
  { key: "tourist",           label: "Tourist",           blurb: "Plain-English practical answers." },
  { key: "layman",            label: "Layman",            blurb: "Short sentences, concrete examples." },
  { key: "conflict_detector", label: "Conflict Detector", blurb: "Cross-jurisdiction comparison." },
];

const VERIFICATION_TONES = {
  high:     { tone: "green", label: "High trust"   },
  medium:   { tone: "amber", label: "Medium trust" },
  low:      { tone: "red",   label: "Low trust"    },
  no_claims_with_citations: { tone: "gray", label: "No citations" },
};

export default function Research() {
  const [persona, setPersona] = useState(PERSONAS[0]);
  const [query, setQuery]     = useState("");
  const [busy, setBusy]       = useState(false);
  const [data, setData]       = useState(null);
  const [error, setError]     = useState(null);

  const submit = async () => {
    if (!query.trim()) return;
    setBusy(true); setError(null); setData(null);
    try {
      const res = await askResearch(query.trim(), persona.key, 10);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Research failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="research-page">
      <div className="flex items-center gap-3 mb-2">
        <BookOpen className="w-5 h-5 text-paper-300" strokeWidth={1.5} />
        <Badge tone="default">Pillar 06 · Research Console</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Five personas. <br className="hidden md:block" /> One <span className="text-verdict-gold">verified</span> answer.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl">
        Ask anything. Pick a persona. Every answer comes with citation markers, retrieved passages, and an automatic
        verification audit — verified, partial, or flagged.
      </p>

      {/* Persona tabs */}
      <div className="mt-8 grid grid-cols-2 md:grid-cols-5 gap-px bg-white/10 border border-white/10" data-testid="research-personas">
        {PERSONAS.map(p => (
          <button
            key={p.key}
            onClick={() => setPersona(p)}
            data-testid={`research-persona-${p.key}`}
            className={`p-4 text-left transition-colors ${
              persona.key === p.key ? "bg-ink-800 text-paper-100" : "bg-ink-900 text-paper-300 hover:bg-ink-800/60"
            } border-l-4 ${persona.key === p.key ? "border-verdict-gold" : "border-transparent"}`}
          >
            <div className="font-serif text-lg leading-tight">{p.label}</div>
            <div className="text-[11px] text-paper-400 mt-1 font-mono uppercase tracking-widest2">{p.blurb}</div>
          </button>
        ))}
      </div>

      <div className="mt-6 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
        <input
          className="bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold"
          placeholder="Ask anything…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          data-testid="research-query-input"
        />
        <button
          onClick={submit}
          disabled={busy}
          className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50 inline-flex items-center gap-2"
          data-testid="research-ask-btn"
        >
          <Send className="w-4 h-4" /> {busy ? "Researching…" : "Ask"}
        </button>
      </div>

      {busy && <div className="mt-6"><Spinner label="Retrieving + reasoning + verifying…" /></div>}
      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}

      {data && (
        <div className="mt-10 grid grid-cols-1 lg:grid-cols-[3fr_2fr] gap-8">
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-4" data-testid="research-meta">
              <Badge tone="gold">{persona.label}</Badge>
              <Badge tone="default">{data.used_model}</Badge>
              {data.verification?.overall_grade && (
                <Badge tone={VERIFICATION_TONES[data.verification.overall_grade]?.tone || "gray"}>
                  <ShieldCheck className="w-3 h-3 mr-1" />
                  {VERIFICATION_TONES[data.verification.overall_grade]?.label || data.verification.overall_grade}
                </Badge>
              )}
            </div>
            <article className="prose prose-invert max-w-none font-serif leading-relaxed text-paper-200" data-testid="research-answer">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {data.answer || "(no answer)"}
              </ReactMarkdown>
            </article>

            {data.verification?.verified_claims?.length > 0 && (
              <div className="mt-8" data-testid="research-claims">
                <MonoLabel>Per-claim audit · {data.verification.summary?.total_claims}</MonoLabel>
                <div className="grid grid-cols-1 gap-px bg-white/10 border border-white/10">
                  {data.verification.verified_claims.map((c, i) => (
                    <div key={i} className="bg-ink-900 p-4">
                      <div className="flex items-center gap-2 mb-2">
                        <Badge tone={c.status === "verified" ? "green" : c.status === "partial" ? "amber" : "red"}>
                          {c.status}
                        </Badge>
                        <span className="font-mono text-[10px] text-paper-400">overlap {c.overlap_score}</span>
                        <span className="font-mono text-[10px] text-paper-300">{(c.citations || []).join(" · ")}</span>
                      </div>
                      <div className="text-sm text-paper-200 mb-1">{c.sentence}</div>
                      {c.supporting_excerpt && (
                        <div className="border-l-2 border-verdict-gold pl-3 mt-2 text-xs text-paper-400">
                          {c.supporting_excerpt}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Citations rail */}
          <aside className="lg:sticky lg:top-24 self-start max-h-[80vh] overflow-y-auto border border-white/10 bg-ink-900" data-testid="research-citations">
            <div className="px-4 py-3 border-b border-white/10">
              <MonoLabel>Citations · {(data.passages || []).length}</MonoLabel>
            </div>
            <ul className="divide-y divide-white/5">
              {(data.passages || []).map((p, i) => (
                <li key={i} className="px-4 py-3 text-xs">
                  <div className="font-mono text-paper-100">{p.marker} · {p.source_name}</div>
                  <div className="font-mono text-paper-400">{p.jurisdiction || "—"} · p.{p.page || "?"}</div>
                  <div className="text-paper-300 mt-1 line-clamp-3">{p.excerpt}</div>
                </li>
              ))}
            </ul>
          </aside>
        </div>
      )}
    </div>
  );
}
