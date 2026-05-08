import React, { useState } from "react";
import { analyzeDrift, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { TrendingUp, TrendingDown, Minus, Sparkles, Save, ExternalLink, History } from "lucide-react";

const VERDICT_STYLES = {
  strengthening: { tone: "green", icon: TrendingUp, label: "STRENGTHENING" },
  fading:        { tone: "red", icon: TrendingDown, label: "FADING" },
  overruled:     { tone: "red", icon: TrendingDown, label: "OVERRULED" },
  emerging:      { tone: "gold", icon: Sparkles, label: "EMERGING" },
  stable:        { tone: "default", icon: Minus, label: "STABLE" },
  no_data:       { tone: "gray", icon: Minus, label: "NO DATA" },
};

const SAMPLES = ["right to privacy", "basic structure doctrine", "qualified immunity", "Miranda warning", "stop and frisk"];

export default function Drift() {
  const [q, setQ] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const run = async (override) => {
    const query = (override || q).trim();
    if (!query) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const out = await analyzeDrift(query);
      setData(out);
    } catch (e) { setError(e?.response?.data?.detail || e?.message || "Failed."); }
    finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("doctrine", `Drift — ${data.query}`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  const maxCount = Math.max(1, ...(data?.buckets || []).map(b => b.count || 0));

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="drift-page">
      <MonoLabel>Pillar 16 · State-of-the-art</MonoLabel>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight mb-2">Authority Drift Tracker</h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Pick a doctrine, statute or seminal case. We hit Indian Kanoon and CourtListener with
        decade-by-decade date filters and count actual citation hits — producing a real
        time-series of how the authority's influence has shifted, plus a verdict.
      </p>

      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="e.g. right to privacy"
          className="flex-1 min-w-[260px] bg-ink-800 border border-white/10 px-4 py-2.5 text-paper-100 outline-none focus:border-verdict-gold"
          data-testid="drift-query-input"
        />
        <button onClick={() => run()} disabled={loading || !q.trim()} data-testid="drift-run-btn"
          className="px-5 py-2.5 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center gap-2">
          <History className="w-4 h-4" />
          {loading ? "Counting…" : "Track drift"}
        </button>
      </div>
      <div className="flex flex-wrap gap-2 text-xs font-mono mb-6">
        {SAMPLES.map(s => (
          <button key={s} onClick={() => { setQ(s); run(s); }} data-testid={`drift-sample-${s.replace(/\s/g, '-')}`}
            className="px-2.5 py-1 border border-white/10 text-paper-300 hover:border-verdict-gold hover:text-verdict-gold uppercase tracking-widest2">
            {s}
          </button>
        ))}
      </div>

      {error && <ErrorBlock error={error} />}
      {loading && <div className="mt-8"><Spinner label="Hitting Indian Kanoon · Hitting CourtListener · 14 buckets in parallel" /></div>}

      {data && (() => {
        const style = VERDICT_STYLES[data.verdict] || VERDICT_STYLES.no_data;
        const Icon = style.icon;
        return (
          <div className="mt-10 space-y-8" data-testid="drift-results">
            <div className="border border-white/10 p-6 flex items-start gap-4">
              <Icon className="w-8 h-8 text-verdict-gold mt-1" strokeWidth={1.5} />
              <div className="flex-1">
                <Badge tone={style.tone}>{style.label}</Badge>
                <h2 className="mt-2 font-serif text-2xl text-paper-100">{data.query}</h2>
                <p className="mt-2 text-paper-300">{data.narrative}</p>
                <div className="mt-3 text-xs font-mono uppercase tracking-widest2 text-paper-400">
                  {data.total_hits?.toLocaleString()} total hits · {(data.registries || []).join(", ")} · {data.elapsed_seconds}s
                </div>
              </div>
              <button onClick={onSave} data-testid="drift-save-btn"
                className="text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5">
                <Save className="w-3 h-3" /> {saved ? "Saved" : "Save"}
              </button>
            </div>

            <div>
              <MonoLabel>Citation velocity by decade</MonoLabel>
              <div className="border border-white/10 p-6">
                <div className="grid grid-cols-7 gap-1 items-end h-56">
                  {(data.buckets || []).map((b, i) => {
                    const h = Math.max(2, Math.round(((b.count || 0) / maxCount) * 100));
                    return (
                      <div key={i} className="flex flex-col items-center justify-end h-full" data-testid={`drift-bar-${b.decade}`}>
                        <div className="text-[10px] font-mono text-paper-300 mb-1">{(b.count || 0).toLocaleString()}</div>
                        <div className="w-full bg-verdict-gold transition-all" style={{ height: `${h}%` }} />
                        <div className="mt-2 text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{b.decade}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {(data.most_recent_citations || []).length > 0 && (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <CitationList title="Most recent" items={data.most_recent_citations || []} />
                <CitationList title="Earliest"    items={data.oldest_citations || []} />
              </div>
            )}
          </div>
        );
      })()}
    </div>
  );
}

function CitationList({ title, items }) {
  return (
    <div>
      <MonoLabel>{title}</MonoLabel>
      <div className="border border-white/10">
        {items.map((c, i) => (
          <a key={i} href={c.url} target="_blank" rel="noopener noreferrer"
             className="block border-b border-white/5 last:border-0 p-3 hover:bg-ink-800">
            <div className="font-sans text-sm text-paper-100 leading-snug">{c.title}</div>
            <div className="mt-1 text-xs font-mono text-paper-400">{c.date} · {c.source}</div>
          </a>
        ))}
        {!items.length && <div className="p-4 text-sm text-paper-400">None.</div>}
      </div>
    </div>
  );
}
