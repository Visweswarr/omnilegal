import React, { useState } from "react";
import { stressTest, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { TestTube, AlertTriangle, ExternalLink, Save, Beaker } from "lucide-react";

const SAMPLE = `Section 66A. Punishment for sending offensive messages through communication service, etc.- Any person who sends, by means of a computer resource or a communication device,- (a) any information that is grossly offensive or has menacing character; or (b) any information which he knows to be false, but for the purpose of causing annoyance, inconvenience, danger, obstruction, insult, injury, criminal intimidation, enmity, hatred or ill will, persistently makes by making use of such computer resource or a communication device, shall be punishable with imprisonment for a term which may extend to three years and with fine.`;

const COVERAGE_TONES = { covered: "green", borderline: "amber", gap: "red" };

export default function Stress() {
  const [clause, setClause] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const run = async () => {
    if (!clause.trim()) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const out = await stressTest(clause.trim());
      setData(out);
    } catch (e) { setError(e?.response?.data?.detail || e?.message || "Failed."); }
    finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("diff", `Stress — ${(data.clause_summary || clause).slice(0, 80)}`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="stress-page">
      <MonoLabel>Pillar 18 · State-of-the-art</MonoLabel>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight mb-2">Statute Stress Test</h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Paste a statute clause. We generate boundary fact patterns at the edge of the rule's
        literal text, classify each as covered / borderline / gap, and probe Indian Kanoon and
        CourtListener for cases that may have actually decided each hypothetical.
      </p>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7 space-y-3">
          <textarea
            value={clause}
            onChange={(e) => setClause(e.target.value)}
            rows={9}
            placeholder="Paste the statutory clause to stress-test…"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans text-sm focus:border-verdict-gold outline-none"
            data-testid="stress-clause-input"
          />
          <div className="flex flex-wrap gap-2">
            <button onClick={run} disabled={loading || !clause.trim()} data-testid="stress-run-btn"
              className="px-5 py-2.5 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center gap-2">
              <TestTube className="w-4 h-4" />
              {loading ? "Stressing…" : "Stress test the clause"}
            </button>
            <button onClick={() => setClause(SAMPLE)} data-testid="stress-sample-btn"
              className="px-5 py-2.5 border border-white/15 text-paper-300 font-mono text-xs uppercase tracking-widest2 hover:border-white/40">
              Load sample (IT Act §66A)
            </button>
          </div>
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="border border-white/10 p-5 text-sm text-paper-300 leading-relaxed">
            <div className="flex items-center gap-2 mb-2"><Beaker className="w-4 h-4 text-verdict-gold" /><span className="font-mono uppercase tracking-widest2 text-xs text-paper-100">Adversarial drafting probe</span></div>
            We deliberately probe the edges. Each hypothetical is paired with live registry hits — so
            ambiguities the legislature missed but courts already encountered surface immediately.
          </div>
        </div>
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {loading && <div className="mt-8"><Spinner label="Generating hypotheticals · Probing registries · Classifying coverage" /></div>}

      {data && (
        <div className="mt-10 space-y-8" data-testid="stress-results">
          <div className="border border-white/10 p-6">
            <Badge tone="gold">Clause summary</Badge>
            <p className="mt-3 text-paper-100 font-serif text-lg leading-snug">{data.clause_summary}</p>
            <div className="mt-4 grid grid-cols-3 gap-px bg-white/10 border border-white/10">
              <Tile k="Covered"    v={data.coverage_distribution?.covered || 0}    tone="green" />
              <Tile k="Borderline" v={data.coverage_distribution?.borderline || 0} tone="amber" />
              <Tile k="Gap"        v={data.coverage_distribution?.gap || 0}        tone="red" />
            </div>
          </div>

          <div className="flex items-center justify-between">
            <MonoLabel>Boundary hypotheticals</MonoLabel>
            <button onClick={onSave} data-testid="stress-save-btn"
              className="text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5">
              <Save className="w-3 h-3" /> {saved ? "Saved" : "Save"}
            </button>
          </div>

          <div className="space-y-px bg-white/10 border border-white/10">
            {(data.hypotheticals || []).map((h, i) => (
              <div key={i} className="bg-ink-900 p-5" data-testid={`stress-hypo-${i}`}>
                <div className="flex items-center gap-3 flex-wrap">
                  <Badge tone={COVERAGE_TONES[h.literal_coverage] || "default"}>
                    {h.literal_coverage?.toUpperCase()}
                  </Badge>
                  <span className="text-[10px] font-mono text-paper-400">#{h.id ?? i + 1}</span>
                  <span className="text-[10px] font-mono text-paper-400">{h.live_hits_count ?? 0} live hits</span>
                </div>
                <p className="mt-2 text-paper-100 leading-relaxed">{h.fact_pattern}</p>
                {h.why && <p className="mt-2 text-sm text-paper-300 leading-relaxed">{h.why}</p>}
                {(h.live_hits || []).length > 0 && (
                  <div className="mt-3 space-y-1">
                    {(h.live_hits || []).slice(0, 3).map((hit, j) => (
                      <a key={j} href={hit.url} target="_blank" rel="noopener noreferrer"
                         className="block text-xs text-paper-300 hover:text-verdict-gold flex items-start gap-2">
                        <ExternalLink className="w-3 h-3 mt-0.5 shrink-0" />
                        <span>{hit.title}{hit.date && <span className="text-paper-500"> · {hit.date}</span>}</span>
                      </a>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          {(data.drafting_flaws || []).length > 0 && (
            <div>
              <MonoLabel>Drafting flaws</MonoLabel>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10">
                {(data.drafting_flaws || []).map((fl, i) => (
                  <div key={i} className="bg-ink-900 p-4" data-testid={`stress-flaw-${i}`}>
                    <div className="flex items-center gap-2 text-verdict-red mb-1">
                      <AlertTriangle className="w-3 h-3" />
                      <code className="text-sm">{fl.phrase}</code>
                    </div>
                    <p className="text-sm text-paper-300 leading-relaxed">{fl.issue}</p>
                    {fl.fix_suggestion && <p className="mt-2 text-sm text-verdict-green leading-relaxed">→ {fl.fix_suggestion}</p>}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Tile({ k, v, tone }) {
  const colorMap = { green: "text-verdict-green", red: "text-verdict-red", amber: "text-verdict-amber" };
  return (
    <div className="bg-ink-900 p-4">
      <div className={`font-mono text-2xl ${colorMap[tone] || "text-paper-100"}`}>{v}</div>
      <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mt-1">{k}</div>
    </div>
  );
}
