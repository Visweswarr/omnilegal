import React, { useState } from "react";
import { GitCompare, Save } from "lucide-react";
import { compareDiff, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const KIND_TONES = {
  unchanged: "border-white/10 text-paper-400",
  added:     "border-verdict-green/60 bg-verdict-green/10 text-verdict-green",
  removed:   "border-verdict-red/60 bg-verdict-red/10 text-verdict-red",
  reworded:  "border-verdict-amber/60 bg-verdict-amber/10 text-verdict-amber",
};

export default function Diff() {
  const [left, setLeft]   = useState("");
  const [right, setRight] = useState("");
  const [leftLabel, setLeftLabel]   = useState("Original (Left)");
  const [rightLabel, setRightLabel] = useState("Amended (Right)");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [hideUnchanged, setHideUnchanged] = useState(false);
  const [savedId, setSavedId] = useState(null);

  const submit = async () => {
    if (!left.trim() || !right.trim()) return;
    setBusy(true); setError(null); setData(null); setSavedId(null);
    try {
      setData(await compareDiff(left, right, leftLabel, rightLabel));
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Diff failed.");
    } finally { setBusy(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      const r = await saveReport("diff", `${leftLabel} vs ${rightLabel}`, data);
      setSavedId(r.id);
    } catch (e) {
      setError(e?.response?.data?.detail || "Save failed.");
    }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="diff-page">
      <div className="flex items-center gap-3 mb-2">
        <GitCompare className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 09 · Statute Diff Engine</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Diff any two laws.<br className="hidden md:block" /> See exactly what <span className="text-verdict-gold">changed</span>.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Paste two versions of a statute, regulation, or treaty article. We diff them
        deterministically and show what changed legally — scope, obligations, penalties, defences.
      </p>

      <div className="mt-8 grid md:grid-cols-2 gap-4">
        <div>
          <MonoLabel>Left</MonoLabel>
          <input
            value={leftLabel}
            onChange={(e) => setLeftLabel(e.target.value)}
            data-testid="diff-left-label"
            className="w-full bg-transparent border border-white/10 px-3 py-2 mb-2 text-sm text-paper-100"
          />
          <textarea
            value={left} onChange={(e) => setLeft(e.target.value)}
            data-testid="diff-left-text"
            placeholder="Paste original text…"
            className="w-full h-72 bg-ink-800/40 border border-white/10 p-3 font-mono text-sm text-paper-100"
          />
        </div>
        <div>
          <MonoLabel>Right</MonoLabel>
          <input
            value={rightLabel}
            onChange={(e) => setRightLabel(e.target.value)}
            data-testid="diff-right-label"
            className="w-full bg-transparent border border-white/10 px-3 py-2 mb-2 text-sm text-paper-100"
          />
          <textarea
            value={right} onChange={(e) => setRight(e.target.value)}
            data-testid="diff-right-text"
            placeholder="Paste amended/comparison text…"
            className="w-full h-72 bg-ink-800/40 border border-white/10 p-3 font-mono text-sm text-paper-100"
          />
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
          onClick={submit} disabled={busy || !left || !right}
          data-testid="diff-submit"
          className="px-6 py-2 bg-verdict-gold text-ink-900 font-mono text-xs uppercase tracking-widest2 disabled:opacity-40"
        >
          {busy ? "Diffing…" : "Compare"}
        </button>
        <label className="flex items-center gap-2 font-mono text-xs uppercase tracking-widest2 text-paper-400">
          <input type="checkbox" checked={hideUnchanged}
            onChange={(e) => setHideUnchanged(e.target.checked)}
            data-testid="diff-hide-unchanged"
          />
          Hide unchanged
        </label>
        {data && (
          <button
            onClick={onSave}
            data-testid="diff-save-report"
            className="ml-auto px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 flex items-center gap-2"
          >
            <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0, 8)}` : "Save to library"}
          </button>
        )}
      </div>

      {busy && <div className="mt-8"><Spinner label="Computing diff…" /></div>}
      <ErrorBlock error={error} />

      {data && !data.error && (
        <>
          <Section title="What changed legally" eyebrow="Impact">
            <div className="border border-white/10 bg-ink-800/40 p-5">
              <p className="text-paper-100 leading-relaxed">{data.impact?.summary}</p>
              <div className="grid md:grid-cols-2 gap-4 mt-5 text-sm">
                {["scope_change", "obligation_change", "penalty_change", "defences_change"].map(k => (
                  data.impact?.[k] ? (
                    <div key={k} className="border border-white/10 p-3">
                      <MonoLabel>{k.replace(/_/g, " ")}</MonoLabel>
                      <p className="text-paper-200 text-sm">{data.impact[k]}</p>
                    </div>
                  ) : null
                ))}
              </div>
              {data.impact?.authority_changes?.length > 0 && (
                <div className="mt-5">
                  <MonoLabel>Authority changes</MonoLabel>
                  <ul className="space-y-1 text-sm font-mono text-paper-300">
                    {data.impact.authority_changes.map((a, i) => (
                      <li key={i}>
                        {a.quote_left && <span className="text-verdict-red">− {a.quote_left}</span>}{" "}
                        {a.quote_right && <span className="text-verdict-green">+ {a.quote_right}</span>}{" "}
                        <span className="text-paper-400">— {a.note}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Section>

          <Section title="Side-by-side diff" eyebrow={`${data.counts?.added || 0}+ / ${data.counts?.removed || 0}- / ${data.counts?.reworded || 0}~`}>
            <div className="grid md:grid-cols-2 gap-3">
              {data.diff_chunks
                .filter(c => !hideUnchanged || c.kind !== "unchanged")
                .map((c, i) => (
                  <React.Fragment key={i}>
                    <div className={`border p-3 text-sm font-mono whitespace-pre-wrap ${KIND_TONES[c.kind]}`}>
                      <div className="text-[10px] uppercase tracking-widest2 mb-1 opacity-70">{c.kind}</div>
                      {c.left || <span className="opacity-40">—</span>}
                    </div>
                    <div className={`border p-3 text-sm font-mono whitespace-pre-wrap ${KIND_TONES[c.kind]}`}>
                      <div className="text-[10px] uppercase tracking-widest2 mb-1 opacity-70">{c.kind}</div>
                      {c.right || <span className="opacity-40">—</span>}
                    </div>
                  </React.Fragment>
                ))}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
