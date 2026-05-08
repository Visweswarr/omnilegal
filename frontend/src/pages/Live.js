import React, { useState } from "react";
import { Radio, ExternalLink, Calendar, Building2, Globe2 } from "lucide-react";
import { searchLive } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

const SOURCES = [
  { key: "indian_kanoon", label: "Indian Kanoon",  juris: "India" },
  { key: "courtlistener", label: "CourtListener",  juris: "United States" },
  { key: "govinfo",       label: "GovInfo",         juris: "United States" },
  { key: "eurlex",        label: "EUR-Lex",         juris: "European Union" },
  { key: "hudoc",         label: "HUDOC",           juris: "ECHR" },
  { key: "un_treaties",   label: "UN Treaty Index", juris: "International" },
];

const EXAMPLES = [
  "freedom of expression",
  "encryption export",
  "war crimes universal jurisdiction",
  "right to be forgotten",
  "death penalty drug offences",
  "indigenous peoples land rights",
];

function relativeDate(dateStr) {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;
  const days = Math.floor((Date.now() - d.getTime()) / (1000 * 60 * 60 * 24));
  if (days < 0) return d.toLocaleDateString();
  if (days === 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 30)  return `${days} days ago`;
  if (days < 365) return `${Math.floor(days / 30)} months ago`;
  return `${Math.floor(days / 365)} years ago`;
}

export default function Live() {
  const [query, setQuery] = useState("");
  const [enabled, setEnabled] = useState(SOURCES.map(s => s.key));
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const toggle = (key) => {
    setEnabled(curr => curr.includes(key) ? curr.filter(k => k !== key) : [...curr, key]);
  };

  const submit = async () => {
    if (!query.trim()) return;
    setBusy(true); setError(null); setData(null);
    try {
      const res = await searchLive(query.trim(), enabled, 5);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Live search failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="live-page">
      <div className="flex items-center gap-3 mb-2">
        <Radio className="w-5 h-5 text-verdict-amber" strokeWidth={1.5} />
        <Badge tone="amber">Pillar 04 · Live Authority Engine</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Real-time queries.<br className="hidden md:block" /> <span className="text-verdict-gold">Six</span> primary registries.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl">
        ChatGPT's knowledge is frozen. OmniLegal goes live — concurrent queries against Indian Kanoon,
        CourtListener, GovInfo, EUR-Lex, HUDOC, and the UN Treaty Index. Time-stamped, dated, dated.
      </p>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
        <input
          className="bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold"
          placeholder="e.g. freedom of expression"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          data-testid="live-query-input"
        />
        <button
          onClick={submit}
          disabled={busy || enabled.length === 0}
          className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50"
          data-testid="live-search-btn"
        >
          {busy ? "Searching…" : "Run live search"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mr-2 self-center">Sources</span>
        {SOURCES.map(s => (
          <button
            key={s.key}
            onClick={() => toggle(s.key)}
            className={`text-xs font-mono uppercase tracking-widest2 px-2 py-1 border ${
              enabled.includes(s.key)
                ? "border-verdict-gold text-verdict-gold bg-verdict-gold/10"
                : "border-white/10 text-paper-400"
            }`}
            data-testid={`live-source-${s.key}`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mr-2 self-center">Examples</span>
        {EXAMPLES.map(ex => (
          <button
            key={ex}
            onClick={() => setQuery(ex)}
            className="text-xs font-mono text-paper-300 border border-white/10 px-2 py-1 hover:border-verdict-gold hover:text-paper-100"
            data-testid={`live-example-${ex.replace(/\s/g, "-").toLowerCase()}`}
          >
            {ex}
          </button>
        ))}
      </div>

      {busy && <div className="mt-6"><Spinner label="Hitting six registries in parallel…" /></div>}
      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}

      {data && (
        <div className="mt-10">
          <div className="flex flex-wrap items-center gap-3 mb-6" data-testid="live-meta">
            <Badge tone="gold">{data.total} hits</Badge>
            <Badge tone="default">{(data.elapsed_seconds || 0).toFixed(2)}s</Badge>
            {Object.entries(data.errors || {}).map(([k, v]) => (
              <Badge key={k} tone="red">{k}: {String(v).slice(0, 80)}</Badge>
            ))}
          </div>

          {/* Per-source breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-white/10 border border-white/10 mb-8">
            {SOURCES.map(s => {
              const hits = data.by_source?.[s.key] || [];
              return (
                <div key={s.key} className="bg-ink-900 p-4" data-testid={`live-source-summary-${s.key}`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-300">{s.label}</span>
                    <span className="font-mono text-paper-100">{hits.length}</span>
                  </div>
                  <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{s.juris}</div>
                </div>
              );
            })}
          </div>

          {/* Combined feed */}
          <div className="space-y-px">
            {data.results?.map((r, i) => (
              <a
                key={i}
                href={r.url}
                target="_blank"
                rel="noreferrer noopener"
                className="block bg-ink-900 hover:bg-ink-800 border border-white/10 p-5 group"
                data-testid={`live-hit-${i}`}
              >
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <Badge tone="gold">{r.source}</Badge>
                  <Badge tone="default">{r.kind}</Badge>
                  {r.jurisdiction && (
                    <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 inline-flex items-center gap-1">
                      <Globe2 className="w-3 h-3" /> {r.jurisdiction}
                    </span>
                  )}
                  {r.date && (
                    <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 inline-flex items-center gap-1">
                      <Calendar className="w-3 h-3" /> {relativeDate(r.date)}
                    </span>
                  )}
                  {r.court && (
                    <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 inline-flex items-center gap-1">
                      <Building2 className="w-3 h-3" /> {r.court}
                    </span>
                  )}
                  <ExternalLink className="ml-auto w-3.5 h-3.5 text-paper-400 group-hover:text-verdict-gold" />
                </div>
                <div className="font-serif text-lg text-paper-100 leading-snug">{r.title}</div>
                {r.snippet && <div className="mt-2 text-sm text-paper-300 line-clamp-3">{r.snippet}</div>}
              </a>
            ))}
            {data.results?.length === 0 && (
              <div className="border border-white/10 p-8 text-center text-paper-400 text-sm">
                No live hits returned. Try a different query or enable more sources.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
