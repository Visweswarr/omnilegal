import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Scale, Send, Save, GitMerge, AlertTriangle, CheckCircle, MinusCircle, Network } from "lucide-react";
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
};

const VERDICT_TONES = {
  alignment:          "green",
  qualified_alignment:"amber",
  conflict_detected:  "red",
  neutral_or_unknown: "gray",
};

function getConclusionStyle(conclusion = "") {
  const lower = conclusion.toLowerCase();
  if (lower.startsWith("lawful_if") || lower.startsWith("lawful if"))
    return CONCLUSION_STYLES.lawful_if_conditions;
  if (lower.startsWith("lawful"))   return CONCLUSION_STYLES.lawful;
  if (lower.startsWith("unlawful")) return CONCLUSION_STYLES.unlawful;
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
          <Spinner label={`Retrieving sources · Traversing citation graph · Generating IRAC for ${selected.length} jurisdictions…`} />
        </div>
      )}

      {/* Results */}
      {data && (
        <div className="mt-10 space-y-10" data-testid="comparative-results">

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
