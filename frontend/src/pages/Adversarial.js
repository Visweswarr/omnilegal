import React, { useState } from "react";
import { findAdversarial, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { Swords, Target, Skull, ExternalLink, Save, AlertOctagon } from "lucide-react";

const SAMPLE = "My client published a critical news article exposing alleged corruption by a sitting politician. We argue Section 499 IPC defamation should not apply because the article is journalism on matters of public interest, fully protected under Article 19(1)(a) and the actual-malice standard.";

export default function Adversarial() {
  const [claim, setClaim] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const run = async () => {
    if (!claim.trim()) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const out = await findAdversarial(claim.trim());
      setData(out);
    } catch (e) { setError(e?.response?.data?.detail || e?.message || "Failed."); }
    finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("redteam", `Adversarial — ${(data.core_claim || claim).slice(0, 80)}`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="adversarial-page">
      <MonoLabel>Pillar 14 · State-of-the-art</MonoLabel>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight mb-2">Adversarial Case Finder</h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Paste your argument or position. We invert it into the strongest opposing thesis,
        run that across Indian Kanoon, CourtListener, EUR-Lex and HUDOC, and surface the
        precedents your opponent will weaponise against you — ranked by predicted damage.
      </p>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7 space-y-3">
          <textarea
            value={claim}
            onChange={(e) => setClaim(e.target.value)}
            rows={7}
            placeholder="State your legal claim or position…"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans text-sm focus:border-verdict-gold outline-none"
            data-testid="adversarial-claim-input"
          />
          <div className="flex flex-wrap gap-2">
            <button onClick={run} disabled={loading || !claim.trim()} data-testid="adversarial-run-btn"
              className="px-5 py-2.5 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2">
              <Swords className="w-4 h-4" strokeWidth={2} />
              {loading ? "Hunting counter-precedents…" : "Find counter-precedents"}
            </button>
            <button onClick={() => setClaim(SAMPLE)} data-testid="adversarial-sample-btn"
              className="px-5 py-2.5 border border-white/15 text-paper-300 font-mono text-xs uppercase tracking-widest2 hover:border-white/40">
              Load sample
            </button>
          </div>
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="border border-white/10 p-5 text-sm text-paper-300 leading-relaxed">
            <div className="flex items-center gap-2 mb-2"><Target className="w-4 h-4 text-verdict-gold" /><span className="font-mono uppercase tracking-widest2 text-xs text-paper-100">Why this beats ChatGPT</span></div>
            ChatGPT can rephrase your claim. It cannot deterministically search Indian Kanoon's actual database for the worst recent decision against you, link to it, and quote the line opposing counsel will weaponise. We do.
          </div>
        </div>
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {loading && <div className="mt-8"><Spinner label="Inverting claim · Searching live registries · Scoring damage" /></div>}

      {data && (
        <div className="mt-10 space-y-8" data-testid="adversarial-results">
          <div className="border border-verdict-red/40 bg-verdict-red/5 p-6">
            <Badge tone="red"><Skull className="w-3 h-3" /> Kill Thesis</Badge>
            <p className="mt-3 text-paper-100 font-serif text-xl leading-snug">{data.kill_thesis}</p>
            {data.summary && <p className="mt-4 text-paper-300 leading-relaxed">{data.summary}</p>}

            <div className="mt-5 grid grid-cols-2 md:grid-cols-4 gap-px bg-white/10 border border-white/10">
              <Tile k="Candidates" v={data.candidates_retrieved} />
              <Tile k="Ranked" v={data.ammunition_count} />
              <Tile k="Sources hit" v={(data.sources_queried || []).length} />
              <Tile k="Jurisdictions" v={(data.jurisdictions_attacked || []).length} />
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-4">
              <MonoLabel>Top counter-precedents</MonoLabel>
              <button onClick={onSave} data-testid="adversarial-save-btn"
                className="text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5">
                <Save className="w-3 h-3" /> {saved ? "Saved" : "Save to library"}
              </button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10">
              {(data.counter_precedents || []).map((c, i) => (
                <a href={c.url} target="_blank" rel="noopener noreferrer" key={i}
                   className="block bg-ink-900 hover:bg-ink-800 p-5 transition-colors"
                   data-testid={`adversarial-card-${i}`}>
                  <div className="flex items-center justify-between mb-2">
                    <Badge tone={c.damage_score >= 0.8 ? "red" : c.damage_score >= 0.5 ? "amber" : "default"}>
                      <AlertOctagon className="w-3 h-3" />
                      Damage {(c.damage_score * 100).toFixed(0)}%
                    </Badge>
                    <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{c.source}</span>
                  </div>
                  <h3 className="font-serif text-lg text-paper-100 mb-2 leading-snug">{c.title}</h3>
                  {c.quote_to_weaponise && (
                    <blockquote className="border-l-2 border-verdict-red pl-3 text-sm italic text-paper-200 mt-2">
                      "{c.quote_to_weaponise}"
                    </blockquote>
                  )}
                  <p className="text-xs text-paper-400 mt-3 leading-relaxed">{c.exploitation}</p>
                  <div className="flex items-center gap-2 mt-3 text-xs font-mono text-paper-300">
                    {c.is_overruled && <Badge tone="amber">Possibly overruled</Badge>}
                    {c.date && <span>{c.date}</span>}
                    <span className="ml-auto inline-flex items-center gap-1 group-hover:text-verdict-gold">
                      Open <ExternalLink className="w-3 h-3" />
                    </span>
                  </div>
                </a>
              ))}
              {(data.counter_precedents || []).length === 0 && (
                <div className="bg-ink-900 p-8 text-center text-paper-400 col-span-full">No counter-precedents passed the damage threshold.</div>
              )}
            </div>
          </div>

          <div className="text-xs font-mono text-paper-500">
            <span className="text-paper-400">Search terms:</span> {(data.search_terms || []).join(" · ")}
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ k, v }) {
  return (
    <div className="bg-ink-900 p-4">
      <div className="font-mono text-2xl text-paper-100">{v ?? 0}</div>
      <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mt-1">{k}</div>
    </div>
  );
}
