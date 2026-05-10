import React, { useState } from "react";
import { Clock, Send, ChevronLeft, ChevronRight, TrendingUp, TrendingDown, Minus, Network, BarChart2, PrinterIcon } from "lucide-react";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { runLongitudinal } from "../lib/api";

const JURISDICTIONS = [
  { key: "india",         label: "India",           flag: "🇮🇳" },
  { key: "us",            label: "United States",    flag: "🇺🇸" },
  { key: "uk",            label: "United Kingdom",   flag: "🇬🇧" },
  { key: "eu",            label: "European Union",   flag: "🇪🇺" },
  { key: "international", label: "International/UN", flag: "🌐" },
];

const PRESETS = [
  { key: "century",  label: "4 Eras (Century)",  desc: "Pre-1945 · 1945-1970 · 1970-2000 · 2000-Now" },
  { key: "postwar",  label: "5 Decades (Postwar)", desc: "1945-1960 · 1960-1980 · 1980-2000 · 2000-2015 · 2015-Now" },
  { key: "modern",   label: "4 Decades (Modern)", desc: "1990-2000 · 2000-2010 · 2010-2020 · 2020-Now" },
];

const SAMPLES = [
  "Right to privacy under constitutional law",
  "Erga omnes obligations in international law",
  "Corporate liability for human rights violations",
  "Data protection and privacy rights",
  "Death penalty — constitutional and treaty obligations",
  "Recognition of same-sex relationships",
];

const HEAT_CFG = {
  full:          { bg: "bg-emerald-900/60", border: "border-emerald-500/60", text: "text-emerald-300", dot: "bg-emerald-400", label: "Full"    },
  partial:       { bg: "bg-amber-900/50",   border: "border-amber-500/50",   text: "text-amber-300",   dot: "bg-amber-400",   label: "Partial" },
  none:          { bg: "bg-rose-900/50",    border: "border-rose-500/50",    text: "text-rose-300",    dot: "bg-rose-400",    label: "None"    },
  indeterminate: { bg: "bg-zinc-800/60",    border: "border-zinc-600/50",    text: "text-zinc-400",    dot: "bg-zinc-500",    label: "?"       },
};

const JUR_FLAGS = {
  India: "🇮🇳", "United States": "🇺🇸", "United Kingdom": "🇬🇧",
  "European Union": "🇪🇺", "International (UN/Treaties)": "🌐", "International": "🌐",
};

const TREND_ICONS = {
  up:     <TrendingUp    className="w-3 h-3 text-emerald-400 inline" />,
  down:   <TrendingDown  className="w-3 h-3 text-rose-400 inline" />,
  stable: <Minus         className="w-3 h-3 text-zinc-400 inline" />,
};

// ── Period heat map card ──────────────────────────────────────────────────

function PeriodCard({ slot, isActive, onClick }) {
  const { period, heat_map, trend, irac_blocks } = slot;
  const dims  = heat_map?.dimensions || [];
  const cells = heat_map?.cells || {};
  const jurs  = Object.keys(cells);

  return (
    <div
      className={`border transition-all cursor-pointer ${
        isActive
          ? "border-verdict-gold bg-ink-800"
          : "border-white/10 bg-ink-900 hover:border-white/30"
      }`}
      onClick={onClick}
      data-testid={`period-card-${period.replace(/\s+/g, "-")}`}
    >
      {/* Period header */}
      <div className={`px-4 py-3 border-b ${isActive ? "border-verdict-gold/40" : "border-white/10"}`}>
        <div className="flex items-center justify-between">
          <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400">{period}</span>
          {isActive && <span className="text-verdict-gold text-[10px] font-mono">▶ active</span>}
        </div>
        {heat_map?.summary_verdict && (
          <p className="text-[11px] text-paper-300 mt-1 line-clamp-2">{heat_map.summary_verdict}</p>
        )}
      </div>

      {/* Mini heat grid */}
      {dims.length > 0 && jurs.length > 0 ? (
        <div className="p-3">
          <div className="grid gap-0.5" style={{ gridTemplateColumns: `auto repeat(${dims.length}, 1fr)` }}>
            {/* Dimension headers */}
            <div />
            {dims.map(d => (
              <div key={d} className="text-[8px] font-mono text-paper-500 text-center truncate px-0.5">{d.slice(0,8)}</div>
            ))}
            {/* Jurisdiction rows */}
            {jurs.map(jur => (
              <React.Fragment key={jur}>
                <div className="text-[9px] text-paper-400 pr-1 self-center">{JUR_FLAGS[jur] || "⚖"}</div>
                {dims.map(d => {
                  const val = (cells[jur]?.[d] || "indeterminate").toLowerCase();
                  const cfg = HEAT_CFG[val] || HEAT_CFG.indeterminate;
                  // Trend overlay
                  const trendVal = (trend || {})[jur]?.[d];
                  return (
                    <div
                      key={d}
                      className={`w-full h-4 border flex items-center justify-center ${cfg.bg} ${cfg.border}`}
                      title={`${jur} — ${d}: ${val}`}
                    >
                      {trendVal && trendVal !== "stable" ? (
                        <span className="text-[7px]">{trendVal === "up" ? "↑" : "↓"}</span>
                      ) : (
                        <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                      )}
                    </div>
                  );
                })}
              </React.Fragment>
            ))}
          </div>
        </div>
      ) : (
        <div className="px-3 py-4 text-[10px] text-paper-500 font-mono text-center">
          {(irac_blocks || []).length > 0 ? "Heat map generating…" : "No data"}
        </div>
      )}
    </div>
  );
}

// ── IRAC detail panel ─────────────────────────────────────────────────────

function IracDetail({ slot }) {
  const [openIdx, setOpenIdx] = useState(null);
  if (!slot) return null;
  const { period, irac_blocks, heat_map, trend } = slot;
  const dims  = heat_map?.dimensions || [];
  const cells = heat_map?.cells || {};

  return (
    <div className="space-y-4" data-testid="longitudinal-detail-panel">
      <div className="flex items-center gap-3">
        <Clock className="w-4 h-4 text-verdict-gold" strokeWidth={1.5} />
        <MonoLabel>{period} — Detailed IRAC Analysis</MonoLabel>
      </div>

      {/* Full heat map for this period */}
      {dims.length > 0 && Object.keys(cells).length > 0 && (
        <div className="overflow-x-auto border border-white/10 bg-ink-900">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-white/10">
                <th className="px-4 py-2.5 text-left font-mono text-[10px] uppercase tracking-widest2 text-paper-500 w-32">Jurisdiction</th>
                {dims.map(d => (
                  <th key={d} className="px-3 py-2.5 text-left font-mono text-[10px] uppercase tracking-widest2 text-paper-400">{d}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(cells).map(([jur, cell], ri) => (
                <tr key={jur} className={`border-b border-white/5 ${ri % 2 === 0 ? "" : "bg-ink-800/30"}`}>
                  <td className="px-4 py-3">
                    <span className="mr-1.5">{JUR_FLAGS[jur] || "⚖"}</span>
                    <span className="text-paper-100 text-sm font-medium">{jur}</span>
                  </td>
                  {dims.map(d => {
                    const val = (cell[d] || "indeterminate").toLowerCase();
                    const cfg = HEAT_CFG[val] || HEAT_CFG.indeterminate;
                    const trendVal = (trend || {})[jur]?.[d];
                    return (
                      <td key={d} className="px-3 py-3">
                        <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 border text-xs font-semibold ${cfg.bg} ${cfg.border} ${cfg.text}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${cfg.dot}`} />
                          {cfg.label}
                          {trendVal && trendVal !== "stable" && (
                            <span className="ml-0.5 text-[9px]">{trendVal === "up" ? "↑" : "↓"}</span>
                          )}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {heat_map?.summary_verdict && (
        <p className="text-sm text-paper-200 border-l-2 border-verdict-gold/40 pl-4 leading-relaxed">
          {heat_map.summary_verdict}
        </p>
      )}

      {/* IRAC accordions */}
      <div className="space-y-1">
        {(irac_blocks || []).map((b, i) => (
          <div key={i} className="border border-white/10 bg-ink-900" data-testid={`long-irac-${i}`}>
            <button
              onClick={() => setOpenIdx(openIdx === i ? null : i)}
              className="w-full flex items-center justify-between px-5 py-3 text-left hover:bg-ink-800/40"
            >
              <div className="flex items-center gap-3">
                <span>{JUR_FLAGS[b.jurisdiction] || "⚖"}</span>
                <span className="font-medium text-paper-100">{b.jurisdiction}</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-xs text-paper-400 max-w-[280px] truncate">{b.conclusion}</span>
                <span className="text-paper-500">{openIdx === i ? "▲" : "▼"}</span>
              </div>
            </button>
            {openIdx === i && (
              <div className="px-5 pb-5 space-y-3 border-t border-white/10 pt-3 text-sm text-paper-300">
                {b.rule && (
                  <div>
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Rule</span>
                    <p className="leading-relaxed">{b.rule}</p>
                  </div>
                )}
                {b.application && (
                  <div>
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Application</span>
                    <p className="leading-relaxed">{b.application}</p>
                  </div>
                )}
                {(b.key_authorities || []).length > 0 && (
                  <div>
                    <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Key Authorities</span>
                    <ul className="space-y-0.5">
                      {b.key_authorities.map((a, j) => (
                        <li key={j} className="text-xs text-paper-300 before:content-['›'] before:mr-1 before:text-verdict-gold">{a}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {b.error && <p className="text-xs text-verdict-red font-mono">{b.error}</p>}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Trend summary ─────────────────────────────────────────────────────────

function TrendSummary({ timeline }) {
  if (!timeline || timeline.length < 2) return null;
  const last = timeline[timeline.length - 1];
  const trend = last.trend || {};
  const dims  = last.heat_map?.dimensions || [];
  if (!Object.keys(trend).length) return null;

  return (
    <div className="border border-white/10 bg-ink-900 p-5" data-testid="trend-summary">
      <MonoLabel>Evolution Trend — {timeline[0].period} → {last.period}</MonoLabel>
      <div className="mt-3 space-y-2">
        {Object.entries(trend).map(([jur, dimTrends]) => {
          const ups   = Object.values(dimTrends).filter(v => v === "up").length;
          const downs = Object.values(dimTrends).filter(v => v === "down").length;
          if (!ups && !downs) return null;
          return (
            <div key={jur} className="flex items-center gap-3 text-sm">
              <span className="w-28 text-paper-200">{JUR_FLAGS[jur] || "⚖"} {jur}</span>
              <div className="flex gap-2">
                {ups > 0 && (
                  <span className="flex items-center gap-1 text-emerald-400 text-xs">
                    <TrendingUp className="w-3 h-3" /> +{ups} dimension{ups !== 1 ? "s" : ""}
                  </span>
                )}
                {downs > 0 && (
                  <span className="flex items-center gap-1 text-rose-400 text-xs">
                    <TrendingDown className="w-3 h-3" /> -{downs} dimension{downs !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function Longitudinal() {
  const [query,    setQuery]    = useState("");
  const [selected, setSelected] = useState(["india", "us", "uk"]);
  const [preset,   setPreset]   = useState("century");
  const [loading,  setLoading]  = useState(false);
  const [data,     setData]     = useState(null);
  const [error,    setError]    = useState(null);
  const [activeIdx, setActiveIdx] = useState(0);

  const toggle = k => setSelected(s => s.includes(k) ? s.filter(x => x !== k) : [...s, k]);

  const run = async () => {
    if (!query.trim() || !selected.length) return;
    setLoading(true); setError(null); setData(null);
    try {
      const res = await runLongitudinal(query.trim(), selected, null, preset);
      setData(res);
      setActiveIdx(0);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Longitudinal analysis failed.");
    } finally { setLoading(false); }
  };

  const totalPeriods = (data?.timeline || []).length;

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="longitudinal-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <Clock className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 20 · Longitudinal Heat Maps</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight leading-tight mb-2">
        How has the law<br className="hidden md:block" />
        <span className="text-verdict-gold">evolved over time?</span>
      </h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Select a legal concept and jurisdictions, then choose a time span.
        We run parallel IRAC analyses for each era — constrained to the legal
        landscape of that period — and generate a colour-coded heat map showing
        how recognition evolved.
      </p>

      {/* Input panel */}
      <div className="grid grid-cols-12 gap-6 mb-8">
        {/* Query */}
        <div className="col-span-12 lg:col-span-7 space-y-3">
          <textarea
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && e.ctrlKey && run()}
            rows={2}
            placeholder="e.g. Right to privacy under constitutional law"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 text-sm focus:border-verdict-gold outline-none resize-none"
            data-testid="longitudinal-query-input"
          />
          <div className="flex flex-wrap gap-2">
            {SAMPLES.map((s, i) => (
              <button
                key={i}
                onClick={() => setQuery(s)}
                className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 border border-white/10 px-2.5 py-1 hover:border-verdict-gold/50 hover:text-verdict-gold truncate max-w-[200px]"
                data-testid={`long-sample-${i}`}
              >{s.slice(0, 40)}…</button>
            ))}
          </div>

          {/* Period preset */}
          <div>
            <MonoLabel>Time span</MonoLabel>
            <div className="grid grid-cols-3 gap-2 mt-1">
              {PRESETS.map(p => (
                <button
                  key={p.key}
                  onClick={() => setPreset(p.key)}
                  data-testid={`preset-${p.key}`}
                  className={`border px-3 py-2.5 text-left transition-colors ${
                    preset === p.key
                      ? "border-verdict-gold/60 bg-verdict-gold/10 text-paper-100"
                      : "border-white/10 bg-ink-900 text-paper-400 hover:border-white/30"
                  }`}
                >
                  <div className="text-xs font-medium">{p.label}</div>
                  <div className="text-[10px] text-paper-500 mt-0.5">{p.desc}</div>
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Jurisdiction picker */}
        <div className="col-span-12 lg:col-span-5">
          <MonoLabel>Jurisdictions</MonoLabel>
          <div className="space-y-1.5 mt-1" data-testid="long-jurisdiction-picker">
            {JURISDICTIONS.map(j => (
              <button
                key={j.key}
                onClick={() => toggle(j.key)}
                data-testid={`long-jur-${j.key}`}
                className={`w-full flex items-center gap-3 px-4 py-2.5 border transition-colors ${
                  selected.includes(j.key)
                    ? "border-verdict-gold/60 bg-verdict-gold/10 text-paper-100"
                    : "border-white/10 bg-ink-900 text-paper-300 hover:border-white/30"
                }`}
              >
                <span>{j.flag}</span>
                <span className="text-sm font-medium">{j.label}</span>
                {selected.includes(j.key) && <span className="ml-auto text-verdict-gold font-mono text-[10px]">✓</span>}
              </button>
            ))}
          </div>
          <button
            onClick={run}
            disabled={loading || !query.trim() || !selected.length}
            className="mt-4 w-full bg-verdict-gold text-ink-900 py-3 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center justify-center gap-2"
            data-testid="longitudinal-run-btn"
          >
            <Clock className="w-4 h-4" />
            {loading ? "Analysing across time…" : `Run timeline (${
              PRESETS.find(p => p.key === preset)?.label || preset
            })`}
          </button>
        </div>
      </div>

      {error && <ErrorBlock error={error} />}
      {loading && (
        <Spinner label={`Running IRAC for ${selected.length} jurisdictions × ${
          PRESETS.find(p => p.key === preset)?.desc?.split("·").length || 4
        } periods…`} />
      )}

      {/* Results */}
      {data && data.timeline?.length > 0 && (
        <div className="space-y-8" data-testid="longitudinal-results">
          {/* Header row */}
          <div className="flex flex-wrap items-center gap-3">
            <MonoLabel>Timeline: {data.periods_used?.join(" · ")}</MonoLabel>
            {data.graph_stats?.documents > 0 && (
              <Badge tone="default">
                <Network className="w-3 h-3 mr-1" />
                {data.graph_stats.documents} docs · {data.graph_stats.edges} edges
              </Badge>
            )}
          </div>

          {/* Period cards (mini heat maps) */}
          <div>
            <MonoLabel>Period overview — click a card to explore</MonoLabel>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mt-2">
              {data.timeline.map((slot, i) => (
                <PeriodCard
                  key={slot.period}
                  slot={slot}
                  isActive={activeIdx === i}
                  onClick={() => setActiveIdx(i)}
                />
              ))}
            </div>

            {/* Navigation arrows */}
            <div className="flex items-center gap-3 mt-3">
              <button
                onClick={() => setActiveIdx(i => Math.max(0, i - 1))}
                disabled={activeIdx === 0}
                className="flex items-center gap-1 text-paper-400 hover:text-verdict-gold disabled:opacity-30 text-sm font-mono"
                data-testid="period-prev-btn"
              >
                <ChevronLeft className="w-4 h-4" /> Prev
              </button>
              <span className="text-paper-500 text-xs font-mono">
                {activeIdx + 1} / {totalPeriods}
              </span>
              <button
                onClick={() => setActiveIdx(i => Math.min(totalPeriods - 1, i + 1))}
                disabled={activeIdx >= totalPeriods - 1}
                className="flex items-center gap-1 text-paper-400 hover:text-verdict-gold disabled:opacity-30 text-sm font-mono"
                data-testid="period-next-btn"
              >
                Next <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Active period detail */}
          {data.timeline[activeIdx] && (
            <IracDetail slot={data.timeline[activeIdx]} />
          )}

          {/* Overall trend summary */}
          <TrendSummary timeline={data.timeline} />
        </div>
      )}
    </div>
  );
}
