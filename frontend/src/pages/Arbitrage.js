import React, { useState } from "react";
import { scanArbitrage, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { Globe, MapPin, ExternalLink, Save, Trophy, Compass } from "lucide-react";

const SAMPLE = "Operate a crypto exchange offering stablecoin swaps to retail users in EU, India, and the United States. Avoid securities-registration burdens and minimise data localisation costs.";

const POSTURE_STYLES = {
  favorable: { tone: "green", label: "FAVORABLE", color: "text-verdict-green" },
  neutral:   { tone: "default", label: "NEUTRAL",  color: "text-paper-200" },
  hostile:   { tone: "red", label: "HOSTILE",  color: "text-verdict-red" },
  no_data:   { tone: "gray", label: "NO DATA", color: "text-paper-400" },
};

export default function Arbitrage() {
  const [scenario, setScenario] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const run = async () => {
    if (!scenario.trim()) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const out = await scanArbitrage(scenario.trim());
      setData(out);
    } catch (e) { setError(e?.response?.data?.detail || e?.message || "Failed."); }
    finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("atlas", `Arbitrage — ${(data.scenario_summary || scenario).slice(0, 80)}`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="arbitrage-page">
      <MonoLabel>Pillar 15 · State-of-the-art</MonoLabel>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight mb-2">Jurisdiction Arbitrage</h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Describe a transaction. We extract its legal friction points, scan up to six
        jurisdictions in parallel against live primary registries, and produce a
        favorability matrix with verifiable citations for every cell.
      </p>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7 space-y-3">
          <textarea
            value={scenario}
            onChange={(e) => setScenario(e.target.value)}
            rows={6}
            placeholder="Describe your transaction or business scenario…"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans text-sm focus:border-verdict-gold outline-none"
            data-testid="arbitrage-scenario-input"
          />
          <div className="flex flex-wrap gap-2">
            <button onClick={run} disabled={loading || !scenario.trim()} data-testid="arbitrage-run-btn"
              className="px-5 py-2.5 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center gap-2">
              <Compass className="w-4 h-4" strokeWidth={2} />
              {loading ? "Scanning jurisdictions…" : "Scan jurisdictions"}
            </button>
            <button onClick={() => setScenario(SAMPLE)} data-testid="arbitrage-sample-btn"
              className="px-5 py-2.5 border border-white/15 text-paper-300 font-mono text-xs uppercase tracking-widest2 hover:border-white/40">
              Load sample
            </button>
          </div>
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="border border-white/10 p-5 text-sm text-paper-300 leading-relaxed">
            <div className="flex items-center gap-2 mb-2">
              <Globe className="w-4 h-4 text-verdict-gold" />
              <span className="font-mono uppercase tracking-widest2 text-xs text-paper-100">Why this beats ChatGPT</span>
            </div>
            ChatGPT will give a hand-wave per jurisdiction. We hit Indian Kanoon, CourtListener,
            GovInfo, EUR-Lex, HUDOC and the UN Treaty index in parallel — every cell links to a
            live primary source.
          </div>
        </div>
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {loading && <div className="mt-8"><Spinner label="Planning friction points · Scanning live registries · Synthesising verdicts" /></div>}

      {data && (
        <div className="mt-10 space-y-8" data-testid="arbitrage-results">
          {data.best_jurisdiction && (
            <div className="border border-verdict-gold/50 bg-verdict-gold/10 p-6 flex items-start gap-4">
              <Trophy className="w-6 h-6 text-verdict-gold mt-1" strokeWidth={1.5} />
              <div>
                <Badge tone="gold">Best jurisdiction</Badge>
                <h2 className="mt-2 font-serif text-2xl text-paper-100">{data.best_jurisdiction}</h2>
                <p className="text-sm text-paper-300 mt-1">Highest-confidence favorable posture across the scan.</p>
              </div>
              <button onClick={onSave} data-testid="arbitrage-save-btn"
                className="ml-auto text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5">
                <Save className="w-3 h-3" /> {saved ? "Saved" : "Save"}
              </button>
            </div>
          )}

          <div>
            <MonoLabel>Friction points detected</MonoLabel>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10">
              {(data.friction_points || []).map((fp, i) => (
                <div key={i} className="bg-ink-900 p-4">
                  <div className="font-serif text-paper-100 text-lg">{fp.name}</div>
                  <div className="text-xs font-mono text-paper-400 mt-1">queries: {(fp.queries || []).join(" · ")}</div>
                </div>
              ))}
            </div>
          </div>

          <div>
            <MonoLabel>Jurisdiction matrix</MonoLabel>
            <div className="space-y-px bg-white/10 border border-white/10">
              {(data.matrix || []).map((row, i) => {
                const v = row.verdict || {};
                const style = POSTURE_STYLES[v.posture] || POSTURE_STYLES.no_data;
                return (
                  <div key={i} className="bg-ink-900 p-5" data-testid={`arbitrage-row-${i}`}>
                    <div className="flex items-start gap-4">
                      <MapPin className={`w-4 h-4 mt-1 ${style.color}`} strokeWidth={1.5} />
                      <div className="flex-1">
                        <div className="flex items-center gap-3 flex-wrap">
                          <h3 className="font-serif text-xl text-paper-100">{row.jurisdiction_name}</h3>
                          <Badge tone={style.tone}>{style.label}</Badge>
                          <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">conf {(Number(v.confidence || 0) * 100).toFixed(0)}%</span>
                          <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">hits {row.live_hits_count}</span>
                        </div>
                        <p className="mt-2 text-sm text-paper-300 leading-relaxed">{v.rationale || "No rationale."}</p>
                        {(v.top_authorities || []).length > 0 && (
                          <ul className="mt-3 space-y-1">
                            {(v.top_authorities || []).slice(0, 4).map((a, j) => (
                              <li key={j} className="text-xs text-paper-300 flex items-start gap-2">
                                <ExternalLink className="w-3 h-3 mt-0.5 text-paper-400 shrink-0" />
                                <a href={a.url} target="_blank" rel="noopener noreferrer" className="hover:text-verdict-gold">
                                  <span className="text-paper-100">{a.title}</span>
                                  {a.why_it_matters && <span className="text-paper-400"> — {a.why_it_matters}</span>}
                                </a>
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-px bg-white/10 border border-white/10">
            <Tile k="Favorable" v={data.summary?.favorable || 0} tone="green" />
            <Tile k="Neutral"   v={data.summary?.neutral || 0} />
            <Tile k="Hostile"   v={data.summary?.hostile || 0} tone="red" />
            <Tile k="No data"   v={data.summary?.no_data || 0} />
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ k, v, tone }) {
  const colorMap = { green: "text-verdict-green", red: "text-verdict-red" };
  return (
    <div className="bg-ink-900 p-5">
      <div className={`font-mono text-3xl ${colorMap[tone] || "text-paper-100"}`}>{v}</div>
      <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mt-2">{k}</div>
    </div>
  );
}
