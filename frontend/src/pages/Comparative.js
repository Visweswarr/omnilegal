import React, { useState, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Scale, Send, Save, GitMerge, AlertTriangle, CheckCircle, MinusCircle, Network, PrinterIcon, BarChart2 } from "lucide-react";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { compareJurisdictions, saveReport } from "../lib/api";

const JURISDICTIONS = [
  { key: "india",         label: "India",             flag: "🇮🇳" },
  { key: "us",            label: "United States",      flag: "🇺🇸" },
  { key: "uk",            label: "United Kingdom",     flag: "🇬🇧" },
  { key: "eu",            label: "European Union",     flag: "🇪🇺" },
  { key: "international", label: "International/UN",   flag: "🌐" },
];

const SAMPLES = [
  "Compare the right to privacy under Indian, US, and UK constitutional law.",
  "How do India, EU, and US law treat data localisation obligations?",
  "Compare arbitration enforcement standards under Indian, US, and UK law.",
  "Right to silence and self-incrimination: compare India, US, and UK approaches.",
];

const CONCLUSION_STYLES = {
  lawful:            { tone: "green",   icon: CheckCircle },
  lawful_if_conditions: { tone: "amber", icon: MinusCircle },
  unlawful:          { tone: "red",     icon: AlertTriangle },
  indeterminate:     { tone: "gray",    icon: MinusCircle },
  recognized:        { tone: "green",   icon: CheckCircle },
  partially_recognized: { tone: "amber", icon: MinusCircle },
  not_recognized:    { tone: "red",     icon: AlertTriangle },
  qualified:         { tone: "amber",   icon: MinusCircle },
};

// ── Heat Map ──────────────────────────────────────────────────────────────

const HEAT_CONFIG = {
  full:          { bg: "bg-emerald-900/60",  border: "border-emerald-500/60",  text: "text-emerald-300",  label: "Full",          dot: "bg-emerald-400" },
  partial:       { bg: "bg-amber-900/50",    border: "border-amber-500/50",    text: "text-amber-300",    label: "Partial",       dot: "bg-amber-400" },
  none:          { bg: "bg-rose-900/50",     border: "border-rose-500/50",     text: "text-rose-300",     label: "None",          dot: "bg-rose-400" },
  indeterminate: { bg: "bg-zinc-800/60",     border: "border-zinc-600/50",     text: "text-zinc-400",     label: "?",             dot: "bg-zinc-500" },
};

const JUR_FLAGS = { India: "🇮🇳", "United States": "🇺🇸", "United Kingdom": "🇬🇧", "European Union": "🇪🇺", "International (UN/Treaties)": "🌐", "International": "🌐" };
const JUR_SHORT = { India: "India", "United States": "USA", "United Kingdom": "UK", "European Union": "EU", "International (UN/Treaties)": "Intl.", "International": "Intl." };

function HeatMap({ heatMap, query }) {
  const printRef = useRef(null);
  const dims   = heatMap.dimensions || [];
  const cells  = heatMap.cells || {};
  const jurs   = Object.keys(cells);
  if (!dims.length || !jurs.length) return null;

  const handlePrint = () => {
    const el = printRef.current;
    if (!el) return;
    const w = window.open("", "_blank");
    w.document.write(`
      <html><head><title>OmniLegal · Jurisdictional Heat Map</title>
      <style>
        body { font-family: 'Georgia', serif; padding: 32px; color: #111; background: #fff; }
        h1 { font-size: 22px; font-weight: bold; margin-bottom: 4px; }
        .query { font-size: 13px; color: #555; margin-bottom: 20px; font-style: italic; }
        table { border-collapse: collapse; width: 100%; font-size: 12px; }
        th { background: #1a1a1a; color: #fff; padding: 8px 12px; text-align: left; font-weight: 600; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
        td { padding: 8px 12px; border: 1px solid #e5e7eb; vertical-align: middle; }
        .jur-cell { font-weight: 600; font-size: 13px; }
        .full { background: #d1fae5; color: #065f46; font-weight: 600; }
        .partial { background: #fef3c7; color: #92400e; font-weight: 600; }
        .none { background: #fee2e2; color: #991b1b; font-weight: 600; }
        .indeterminate { background: #f3f4f6; color: #6b7280; }
        .verdict { margin-top: 16px; padding: 12px; background: #f9fafb; border-left: 4px solid #374151; font-size: 13px; color: #374151; }
        .footer { margin-top: 20px; font-size: 10px; color: #9ca3af; }
        .legend { display: flex; gap: 20px; margin-bottom: 12px; font-size: 11px; }
        .legend span { display: inline-flex; align-items: center; gap: 4px; }
      </style></head><body>
      <h1>Jurisdictional Recognition Heat Map</h1>
      <div class="query">${query}</div>
      <div class="legend">
        <span><span style="display:inline-block;width:10px;height:10px;background:#d1fae5;border:1px solid #6ee7b7"></span> Full Recognition</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#fef3c7;border:1px solid #fcd34d"></span> Partial</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#fee2e2;border:1px solid #fca5a5"></span> None</span>
        <span><span style="display:inline-block;width:10px;height:10px;background:#f3f4f6;border:1px solid #d1d5db"></span> Indeterminate</span>
      </div>
      ${el.innerHTML}
      ${heatMap.summary_verdict ? `<div class="verdict"><strong>Summary:</strong> ${heatMap.summary_verdict}</div>` : ""}
      <div class="footer">Generated by OmniLegal v3 · ${new Date().toLocaleDateString()}</div>
      </body></html>`);
    w.document.close();
    w.focus();
    w.print();
  };

  return (
    <div className="border border-white/10 bg-ink-900" data-testid="heat-map-section">
      {/* Header */}
      <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BarChart2 className="w-4 h-4 text-verdict-gold" strokeWidth={1.5} />
          <MonoLabel>Jurisdictional Recognition Heat Map</MonoLabel>
        </div>
        <div className="flex items-center gap-4">
          {/* Legend */}
          <div className="hidden md:flex items-center gap-3 text-[10px] font-mono text-paper-400">
            {Object.entries(HEAT_CONFIG).map(([k, v]) => (
              <span key={k} className="flex items-center gap-1">
                <span className={`w-2 h-2 rounded-full inline-block ${v.dot}`} />
                {k === "indeterminate" ? "?" : v.label}
              </span>
            ))}
          </div>
          <button
            onClick={handlePrint}
            className="flex items-center gap-1.5 text-[10px] font-mono uppercase tracking-widest2 text-paper-400 hover:text-verdict-gold"
            data-testid="heat-map-print-btn"
          >
            <PrinterIcon className="w-3 h-3" />
            Brief
          </button>
        </div>
      </div>

      {/* Grid */}
      <div className="overflow-x-auto" ref={printRef}>
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b border-white/10">
              <th className="px-5 py-3 text-left font-mono text-[10px] uppercase tracking-widest2 text-paper-500 w-36">
                Jurisdiction
              </th>
              {dims.map(d => (
                <th key={d} className="px-4 py-3 text-left font-mono text-[10px] uppercase tracking-widest2 text-paper-400">
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {jurs.map((jur, ri) => {
              const flag = JUR_FLAGS[jur] || "⚖";
              const short = JUR_SHORT[jur] || jur;
              return (
                <tr
                  key={jur}
                  className={`border-b border-white/5 ${ri % 2 === 0 ? "bg-ink-900" : "bg-ink-800/40"}`}
                  data-testid={`heat-row-${ri}`}
                >
                  <td className="px-5 py-4">
                    <span className="mr-2">{flag}</span>
                    <span className="font-medium text-paper-100">{short}</span>
                  </td>
                  {dims.map(d => {
                    const val = (cells[jur]?.[d] || "indeterminate").toLowerCase();
                    const cfg = HEAT_CONFIG[val] || HEAT_CONFIG.indeterminate;
                    return (
                      <td key={d} className="px-4 py-4">
                        <span
                          className={`inline-flex items-center gap-1.5 px-3 py-1 border text-xs font-semibold ${cfg.bg} ${cfg.border} ${cfg.text}`}
                          title={`${jur} — ${d}: ${val}`}
                        >
                          <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${cfg.dot}`} />
                          {cfg.label}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Summary verdict */}
      {heatMap.summary_verdict && (
        <div className="px-6 py-4 border-t border-white/10 flex items-start gap-3">
          <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 mt-0.5 shrink-0">Summary</span>
          <p className="text-sm text-paper-200 leading-relaxed">{heatMap.summary_verdict}</p>
        </div>
      )}
    </div>
  );
}

const VERDICT_TONES = {
  alignment:          "green",
  qualified_alignment:"amber",
  conflict_detected:  "red",
  neutral_or_unknown: "gray",
};

function getConclusionStyle(conclusion = "") {
  const lower = conclusion.toLowerCase();
  if (lower.includes("partially_recognized") || lower.includes("partially recognized") || lower.includes("qualified"))
    return CONCLUSION_STYLES.lawful_if_conditions;
  if (lower.includes("not_recognized") || lower.includes("not recognized") || lower.includes("unlawful") || lower.includes("none"))
    return CONCLUSION_STYLES.unlawful;
  if (lower.startsWith("lawful_if") || lower.startsWith("lawful if"))
    return CONCLUSION_STYLES.lawful_if_conditions;
  if (lower.startsWith("lawful") || lower.includes("recognized") || lower.includes("full"))
    return CONCLUSION_STYLES.lawful;
  return CONCLUSION_STYLES.indeterminate;
}

function IracCard({ block, index }) {
  const [expanded, setExpanded] = useState(false);
  const style = getConclusionStyle(block.conclusion || "");
  const Icon = style.icon;
  const conf = typeof block.confidence === "number"
    ? `${(block.confidence * 100).toFixed(0)}%`
    : "—";

  return (
    <div className="border border-white/10 bg-ink-900 flex flex-col" data-testid={`irac-card-${index}`}>
      {/* header */}
      <div className="px-5 py-4 border-b border-white/10 flex items-start justify-between gap-3">
        <div>
          <MonoLabel>Jurisdiction {index + 1}</MonoLabel>
          <h3 className="font-serif text-xl text-paper-100">{block.jurisdiction || "—"}</h3>
        </div>
        <div className="flex flex-col items-end gap-1 shrink-0">
          <Badge tone={style.tone}>
            <Icon className="w-3 h-3 mr-1" strokeWidth={2} />
            {(block.conclusion || "indeterminate").split("—")[0].trim().slice(0, 40)}
          </Badge>
          <span className="text-[10px] font-mono text-paper-400">conf {conf}</span>
        </div>
      </div>

      {/* body */}
      <div className="px-5 py-4 flex-1 space-y-4 text-sm text-paper-300">
        {block.issue && (
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Issue</span>
            <p className="text-paper-200 leading-relaxed">{block.issue}</p>
          </div>
        )}
        {block.rule && (
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Rule</span>
            <p className="leading-relaxed">{block.rule}</p>
          </div>
        )}
        {block.application && (
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Application</span>
            <p className="leading-relaxed">{block.application}</p>
          </div>
        )}
        {block.conditions_if_any && (
          <div className="border-l-2 border-verdict-amber pl-3">
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Conditions</span>
            <p className="text-paper-300 leading-relaxed">{block.conditions_if_any}</p>
          </div>
        )}
        {block.error && (
          <div className="border border-verdict-red/30 bg-verdict-red/10 px-3 py-2 text-verdict-red text-xs font-mono">
            {block.error}
          </div>
        )}

        {/* Key authorities */}
        {(block.key_authorities || []).length > 0 && (
          <div>
            <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">Key Authorities</span>
            <ul className="space-y-0.5">
              {(block.key_authorities || []).map((a, i) => (
                <li key={i} className="text-xs text-paper-300 before:content-['›'] before:mr-1 before:text-verdict-gold">{a}</li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* passages toggle */}
      {(block.passages || []).length > 0 && (
        <div className="border-t border-white/10">
          <button
            onClick={() => setExpanded(e => !e)}
            className="w-full px-5 py-2.5 text-left font-mono text-[10px] uppercase tracking-widest2 text-paper-400 hover:text-paper-200 flex items-center justify-between"
            data-testid={`irac-passages-toggle-${index}`}
          >
            <span>{block.passages.length} Source{block.passages.length !== 1 ? "s" : ""}</span>
            <span>{expanded ? "▲" : "▼"}</span>
          </button>
          {expanded && (
            <ul className="divide-y divide-white/5 px-5 pb-4">
              {block.passages.map((p, i) => (
                <li key={i} className="py-2 text-xs">
                  <span className="font-mono text-paper-100">{p.marker} · {p.source_name}</span>
                  <span className="font-mono text-paper-400 ml-2">{p.jurisdiction || "—"}</span>
                  {p.excerpt && (
                    <p className="text-paper-400 mt-1 line-clamp-2">{p.excerpt}</p>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

export default function Comparative() {
  const [query, setQuery]             = useState("");
  const [selected, setSelected]       = useState(["india", "us", "uk"]);
  const [loading, setLoading]         = useState(false);
  const [data, setData]               = useState(null);
  const [error, setError]             = useState(null);
  const [saved, setSaved]             = useState(false);
  const [showTable, setShowTable]     = useState(false);

  const toggle = (key) =>
    setSelected(s => s.includes(key) ? s.filter(k => k !== key) : [...s, key]);

  const run = async () => {
    if (!query.trim() || selected.length < 1) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const res = await compareJurisdictions(query.trim(), selected);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Comparison failed.");
    } finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("atlas", `Comparative — ${query.slice(0, 80)}`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="comparative-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <Scale className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 19 · Comparative IRAC</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight leading-tight mb-2">
        Parallel IRAC<br className="hidden md:block" />
        <span className="text-verdict-gold">across jurisdictions.</span>
      </h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Ask a legal question. Select jurisdictions. We retrieve primary sources per jurisdiction,
        traverse the Kuzu citation graph for cross-border precedents, and run simultaneous
        IRAC analyses — then synthesise agreements, conflicts, and gaps.
      </p>

      {/* Input */}
      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-8 space-y-3">
          <textarea
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => e.key === "Enter" && e.ctrlKey && run()}
            rows={3}
            placeholder="e.g. Compare the right to privacy under Indian, US, and UK constitutional law…"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans text-sm focus:border-verdict-gold outline-none resize-none"
            data-testid="comparative-query-input"
          />

          {/* Sample queries */}
          <div className="flex flex-wrap gap-2">
            {SAMPLES.map((s, i) => (
              <button
                key={i}
                onClick={() => setQuery(s)}
                className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 border border-white/10 px-2.5 py-1 hover:border-verdict-gold/50 hover:text-verdict-gold truncate max-w-[220px]"
                data-testid={`comparative-sample-${i}`}
              >
                {s.slice(0, 42)}…
              </button>
            ))}
          </div>
        </div>

        {/* Jurisdiction picker */}
        <div className="col-span-12 lg:col-span-4">
          <MonoLabel>Select jurisdictions</MonoLabel>
          <div className="space-y-1.5" data-testid="comparative-jurisdiction-picker">
            {JURISDICTIONS.map(j => (
              <button
                key={j.key}
                onClick={() => toggle(j.key)}
                data-testid={`jur-toggle-${j.key}`}
                className={`w-full flex items-center gap-3 px-4 py-2.5 border transition-colors ${
                  selected.includes(j.key)
                    ? "border-verdict-gold/60 bg-verdict-gold/10 text-paper-100"
                    : "border-white/10 bg-ink-900 text-paper-300 hover:border-white/30"
                }`}
              >
                <span className="text-base">{j.flag}</span>
                <span className="text-sm font-medium">{j.label}</span>
                {selected.includes(j.key) && (
                  <span className="ml-auto text-verdict-gold font-mono text-[10px]">✓</span>
                )}
              </button>
            ))}
          </div>
          <button
            onClick={run}
            disabled={loading || !query.trim() || selected.length === 0}
            className="mt-4 w-full bg-verdict-gold text-ink-900 py-3 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center justify-center gap-2"
            data-testid="comparative-run-btn"
          >
            <Send className="w-4 h-4" />
            {loading ? "Running parallel IRAC…" : `Compare ${selected.length} jurisdiction${selected.length !== 1 ? "s" : ""}`}
          </button>
        </div>
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {loading && (
        <div className="mt-8">
          <Spinner label={`Retrieving sources · Traversing citation graph · IRAC for ${selected.length} jurisdictions · Building heat map…`} />
        </div>
      )}

      {/* Results */}
      {data && (
        <div className="mt-10 space-y-10" data-testid="comparative-results">

          {/* Heat Map — prominent first-glance summary */}
          {data.heat_map?.dimensions?.length > 0 && (
            <HeatMap heatMap={data.heat_map} query={data.query} />
          )}

          {/* Models + graph stats */}
          <div className="flex flex-wrap items-center gap-2">
            {(data.used_models || []).map((m, i) => (
              <Badge key={i} tone="default">{m}</Badge>
            ))}
            {data.graph_stats?.documents > 0 && (
              <Badge tone="default">
                <Network className="w-3 h-3 mr-1" />
                Graph: {data.graph_stats.documents} docs · {data.graph_stats.edges} edges
              </Badge>
            )}
            <button
              onClick={onSave}
              data-testid="comparative-save-btn"
              className="ml-auto text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5"
            >
              <Save className="w-3 h-3" /> {saved ? "Saved" : "Save report"}
            </button>
          </div>

          {/* IRAC grid */}
          <div>
            <MonoLabel>Per-jurisdiction IRAC analysis</MonoLabel>
            <div className={`grid gap-px bg-white/10 border border-white/10 ${
              data.irac_blocks?.length === 2 ? "grid-cols-1 md:grid-cols-2" :
              data.irac_blocks?.length >= 3 ? "grid-cols-1 md:grid-cols-2 xl:grid-cols-3" :
              "grid-cols-1"
            }`}>
              {(data.irac_blocks || []).map((block, i) => (
                <IracCard key={i} block={block} index={i} />
              ))}
            </div>
          </div>

          {/* Synthesis */}
          {data.synthesis && (
            <div className="border border-white/10 bg-ink-900 p-6 space-y-5" data-testid="comparative-synthesis">
              <div className="flex items-center gap-3">
                <GitMerge className="w-4 h-4 text-verdict-gold" strokeWidth={1.5} />
                <MonoLabel>Cross-jurisdiction synthesis</MonoLabel>
              </div>

              {data.synthesis.international_rule_summary && (
                <div>
                  <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-500 block mb-1">International Baseline Rule</span>
                  <p className="text-paper-200 text-sm leading-relaxed">{data.synthesis.international_rule_summary}</p>
                </div>
              )}

              {(data.synthesis.agreements || []).length > 0 && (
                <div>
                  <span className="font-mono text-[10px] uppercase tracking-widest2 text-verdict-green block mb-1">Agreements</span>
                  <ul className="space-y-1">
                    {data.synthesis.agreements.map((a, i) => (
                      <li key={i} className="text-sm text-paper-300 flex gap-2">
                        <CheckCircle className="w-3.5 h-3.5 text-verdict-green mt-0.5 shrink-0" />
                        {a}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {(data.synthesis.disagreements || []).length > 0 && (
                <div>
                  <span className="font-mono text-[10px] uppercase tracking-widest2 text-verdict-red block mb-1">Disagreements / Conflicts</span>
                  <ul className="space-y-1">
                    {data.synthesis.disagreements.map((d, i) => (
                      <li key={i} className="text-sm text-paper-300 flex gap-2">
                        <AlertTriangle className="w-3.5 h-3.5 text-verdict-red mt-0.5 shrink-0" />
                        {d}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {(data.synthesis.gaps || []).length > 0 && (
                <div>
                  <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400 block mb-1">Gaps / Thin Coverage</span>
                  <ul className="space-y-1">
                    {data.synthesis.gaps.map((g, i) => (
                      <li key={i} className="text-xs text-paper-400 font-mono">{g}</li>
                    ))}
                  </ul>
                </div>
              )}

              {data.synthesis.vclt_article_27_warning && (
                <div className="border border-verdict-amber/30 bg-verdict-amber/10 px-4 py-3 text-sm text-verdict-amber flex gap-2">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span>{data.synthesis.vclt_article_27_warning}</span>
                </div>
              )}
            </div>
          )}

          {/* Kuzu cross-citations */}
          {(data.cross_citations || []).length > 0 && (
            <div data-testid="comparative-cross-citations">
              <MonoLabel>Citation Graph — Cross-jurisdiction precedents</MonoLabel>
              <p className="text-xs text-paper-400 mb-3">Sources cited by documents from 2+ jurisdictions in the corpus.</p>
              <div className="space-y-px bg-white/10 border border-white/10">
                {data.cross_citations.slice(0, 10).map((cc, i) => (
                  <div key={i} className="bg-ink-900 px-5 py-3 flex items-start gap-4" data-testid={`cross-cite-${i}`}>
                    <Network className="w-4 h-4 text-verdict-gold mt-0.5 shrink-0" strokeWidth={1.5} />
                    <div className="flex-1 min-w-0">
                      <span className="font-serif text-paper-100 text-sm">{cc.cited_source}</span>
                      {cc.cited_jurisdiction && (
                        <span className="ml-2 text-[10px] font-mono text-paper-400">{cc.cited_jurisdiction}</span>
                      )}
                      <div className="mt-1 flex flex-wrap gap-1">
                        {(cc.citing_jurisdictions || []).map((j, k) => (
                          <Badge key={k} tone="default">{j}</Badge>
                        ))}
                        <span className="text-[10px] font-mono text-paper-500">{cc.edge_count} edge{cc.edge_count !== 1 ? "s" : ""}</span>
                      </div>
                      {(cc.citation_strings || []).length > 0 && (
                        <p className="text-[11px] text-paper-500 mt-1 font-mono truncate">
                          {cc.citation_strings.join(" · ")}
                        </p>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Comparison table */}
          {data.comparison_table_markdown && (
            <div data-testid="comparative-table">
              <div className="flex items-center justify-between mb-2">
                <MonoLabel>Side-by-side comparison table</MonoLabel>
                <button
                  onClick={() => setShowTable(t => !t)}
                  className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 hover:text-verdict-gold"
                  data-testid="comparative-toggle-table"
                >
                  {showTable ? "Hide" : "Show"}
                </button>
              </div>
              {showTable && (
                <div className="overflow-x-auto border border-white/10 bg-ink-900 p-4">
                  <article className="prose prose-invert max-w-none prose-table:text-sm prose-td:text-paper-300 prose-th:text-paper-100">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {data.comparison_table_markdown}
                    </ReactMarkdown>
                  </article>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
