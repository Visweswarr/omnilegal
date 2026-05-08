import React, { useState } from "react";
import { Swords, Save } from "lucide-react";
import { analyzeRedteam, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const SAMPLE = `The defendant claims that the contract was unconscionable because the arbitration clause was buried in fine print and required arbitration in a distant forum. However, the plaintiff argues the clause is valid and binding because both parties signed the contract and the terms were available for review.`;

const MODES = [
  { key: "argument", label: "Argument" },
  { key: "contract", label: "Contract" },
  { key: "treaty",   label: "Treaty"   },
];

export default function Redteam() {
  const [text, setText] = useState("");
  const [mode, setMode] = useState("argument");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [savedId, setSavedId] = useState(null);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setData(null); setSavedId(null);
    try {
      setData(await analyzeRedteam(text, mode));
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Red team failed.");
    } finally { setBusy(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      const r = await saveReport("redteam", `Red team — ${mode}`, data);
      setSavedId(r.id);
    } catch (e) {
      setError(e?.response?.data?.detail || "Save failed.");
    }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="redteam-page">
      <div className="flex items-center gap-3 mb-2">
        <Swords className="w-5 h-5 text-verdict-red" strokeWidth={1.5} />
        <Badge tone="red">Pillar 11 · Argument Workbench</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Find the <span className="text-verdict-red">cracks</span> in any argument.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Paste an opponent's argument, a contract clause, or a treaty article. We surface
        weak points, the strongest 5 counter-arguments, exploitable loopholes, and the
        precedents that hurt them most.
      </p>

      <div className="mt-8 flex items-center gap-2">
        {MODES.map(m => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            data-testid={`redteam-mode-${m.key}`}
            className={`px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 border ${
              mode === m.key
                ? "border-verdict-red text-verdict-red bg-verdict-red/10"
                : "border-white/10 text-paper-300"
            }`}
          >
            {m.label}
          </button>
        ))}
        <button
          onClick={() => setText(SAMPLE)}
          className="ml-auto px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 border border-white/10 text-paper-300"
        >
          Load sample
        </button>
      </div>

      <textarea
        value={text} onChange={(e) => setText(e.target.value)}
        data-testid="redteam-input"
        placeholder="Paste argument, contract clause, or treaty article…"
        className="mt-3 w-full h-56 bg-ink-800/40 border border-white/10 p-3 font-mono text-sm text-paper-100"
      />

      <div className="mt-3 flex items-center gap-3">
        <button
          onClick={submit} disabled={busy || !text}
          data-testid="redteam-submit"
          className="px-6 py-2 bg-verdict-red text-paper-100 font-mono text-xs uppercase tracking-widest2 disabled:opacity-40"
        >
          {busy ? "Analysing…" : "Run red team"}
        </button>
        {data && !data.error && (
          <button
            onClick={onSave}
            data-testid="redteam-save"
            className="ml-auto px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 flex items-center gap-2"
          >
            <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0,8)}` : "Save to library"}
          </button>
        )}
      </div>

      {busy && <div className="mt-8"><Spinner label="Hunting weaknesses…" /></div>}
      <ErrorBlock error={error} />

      {data && !data.error && (
        <>
          <Section title="Executive summary" eyebrow="Verdict">
            <div className="border border-white/10 bg-ink-800/40 p-5 text-paper-100 leading-relaxed">
              {data.summary}
            </div>
          </Section>

          <Section title="Weak points" eyebrow={`${data.weak_points?.length || 0} found`}>
            <div className="grid md:grid-cols-2 gap-3">
              {(data.weak_points || []).map((w, i) => (
                <div key={i} className="border border-verdict-amber/40 bg-verdict-amber/5 p-4">
                  <Badge tone="amber">{w.weakness_type}</Badge>
                  <blockquote className="mt-2 text-sm font-serif italic text-paper-200 border-l-2 border-verdict-amber/60 pl-3">
                    "{w.quote}"
                  </blockquote>
                  <p className="mt-2 text-sm text-paper-300">{w.why}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Counter-arguments" eyebrow={`${data.counter_arguments?.length || 0} rebuttals`}>
            <div className="space-y-3">
              {(data.counter_arguments || []).map((c, i) => (
                <div key={i} className="border border-white/10 p-4">
                  <div className="font-serif text-lg text-paper-100 leading-snug">{c.point}</div>
                  <p className="mt-2 text-sm text-paper-300">{c.elaboration}</p>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {(c.anchor_citations || []).map((a, j) => (
                      <Badge key={j} tone="gray">{a}</Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Loopholes" eyebrow={`${data.loopholes?.length || 0}`}>
            <div className="grid md:grid-cols-2 gap-3">
              {(data.loopholes || []).map((l, i) => (
                <div key={i} className="border border-verdict-red/50 bg-verdict-red/5 p-4">
                  <blockquote className="text-sm font-serif italic text-paper-200 border-l-2 border-verdict-red/60 pl-3">
                    "{l.quote}"
                  </blockquote>
                  <p className="mt-2 text-sm text-paper-300">{l.exploitation_pattern}</p>
                </div>
              ))}
            </div>
          </Section>

          <Section title="Best precedents for rebuttal" eyebrow="Authority rail">
            <div className="grid md:grid-cols-3 gap-3">
              {(data.best_precedents_for_rebuttal || []).map((p, i) => (
                <div key={i} className="border border-white/10 p-3">
                  <div className="font-mono text-xs uppercase tracking-widest2 text-verdict-gold">
                    {(p.relevance_score * 100 || 0).toFixed(0)}% relevant
                  </div>
                  <div className="font-serif text-base text-paper-100 mt-1">{p.cite}</div>
                  <p className="mt-1 text-xs text-paper-400">{p.why_relevant}</p>
                </div>
              ))}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
