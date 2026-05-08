import React, { useState } from "react";
import { scanSentinel, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";
import { ShieldAlert, AlertOctagon, ExternalLink, Save, FileWarning } from "lucide-react";

const SAMPLE = `Privacy Policy

This policy applies to data collected by Acme Inc. We may transfer personal data outside India to US-based servers operated by AWS. By using the service, users grant blanket consent for any purpose. We use AI-driven automated decision making for hiring decisions and process facial recognition data for security. Section 124A of the IPC may apply to user-generated content. We rely on standard contractual clauses for transfers to the United States. Users in California have CPRA rights including 'do not sell my personal information'.`;

const SEV_TONES = { blocking: "red", high: "red", medium: "amber", low: "default" };
const SEV_ORDER = { blocking: 0, high: 1, medium: 2, low: 3 };

export default function Sentinel() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState(false);

  const run = async () => {
    if (!text.trim()) return;
    setLoading(true); setError(null); setData(null); setSaved(false);
    try {
      const out = await scanSentinel(text.trim());
      setData(out);
    } catch (e) { setError(e?.response?.data?.detail || e?.message || "Failed."); }
    finally { setLoading(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      await saveReport("forensics", `Sentinel — risk ${(data.risk_score * 100).toFixed(0)}%`, data);
      setSaved(true);
    } catch (e) { setError(e?.message || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-10 max-w-7xl mx-auto" data-testid="sentinel-page">
      <MonoLabel>Pillar 17 · State-of-the-art</MonoLabel>
      <h1 className="font-serif text-4xl md:text-5xl text-paper-100 tracking-tight mb-2">Compliance Sentinel</h1>
      <p className="text-paper-300 max-w-3xl mb-8 leading-relaxed">
        Paste a contract, privacy policy or regulation. We scan against a curated catalogue
        of pending and recent legal changes — DPDP India 2025, EU AI Act phases, GDPR/Schrems II,
        US state privacy laws, MiCA, NIS2 — and flag every clause doomed by upcoming law,
        each with a precise remediation.
      </p>

      <div className="grid grid-cols-12 gap-6">
        <div className="col-span-12 lg:col-span-7 space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            placeholder="Paste contract or policy text…"
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans text-sm focus:border-verdict-gold outline-none"
            data-testid="sentinel-text-input"
          />
          <div className="flex flex-wrap gap-2">
            <button onClick={run} disabled={loading || !text.trim()} data-testid="sentinel-run-btn"
              className="px-5 py-2.5 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber disabled:opacity-40 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4" />
              {loading ? "Scanning…" : "Run sentinel scan"}
            </button>
            <button onClick={() => setText(SAMPLE)} data-testid="sentinel-sample-btn"
              className="px-5 py-2.5 border border-white/15 text-paper-300 font-mono text-xs uppercase tracking-widest2 hover:border-white/40">
              Load sample
            </button>
          </div>
        </div>
        <div className="col-span-12 lg:col-span-5">
          <div className="border border-white/10 p-5 text-sm text-paper-300 leading-relaxed">
            <div className="flex items-center gap-2 mb-2">
              <FileWarning className="w-4 h-4 text-verdict-gold" />
              <span className="font-mono uppercase tracking-widest2 text-xs text-paper-100">17+ rule catalogue</span>
            </div>
            DPDP India · EU AI Act · GDPR/Schrems II · DSA · DMA · NIS2 · CPRA · multi-state US
            privacy · BNS replacement · OECD Pillar Two · MiCA · UK Online Safety Act · CSRD ·
            SEC climate disclosure. Each matched span is LLM-validated to avoid false positives.
          </div>
        </div>
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {loading && <div className="mt-8"><Spinner label="Pattern matching · LLM disambiguation · Severity scoring" /></div>}

      {data && (
        <div className="mt-10 space-y-8" data-testid="sentinel-results">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-px bg-white/10 border border-white/10">
            <Tile k="Rules checked" v={data.rules_checked} />
            <Tile k="Pattern hits" v={data.raw_pattern_hits} />
            <Tile k="Confirmed findings" v={data.confirmed_findings} />
            <Tile k="Risk score"
                  v={`${Math.round((data.risk_score || 0) * 100)}%`}
                  tone={data.risk_score >= 0.7 ? "red" : data.risk_score >= 0.4 ? "amber" : "green"} />
            <Tile k="Blocking" v={data.severity_counts?.blocking || 0} tone={data.severity_counts?.blocking ? "red" : "default"} />
          </div>

          <div className="flex items-center justify-between">
            <MonoLabel>Findings — sorted by severity</MonoLabel>
            <button onClick={onSave} data-testid="sentinel-save-btn"
              className="text-xs font-mono uppercase tracking-widest2 text-paper-300 hover:text-verdict-gold flex items-center gap-1.5">
              <Save className="w-3 h-3" /> {saved ? "Saved" : "Save"}
            </button>
          </div>

          <div className="space-y-px bg-white/10 border border-white/10">
            {[...(data.findings || [])].sort((a,b)=> (SEV_ORDER[a.severity]||9)-(SEV_ORDER[b.severity]||9)).map((f, i) => (
              <div key={i} className="bg-ink-900 p-5" data-testid={`sentinel-finding-${i}`}>
                <div className="flex items-center gap-3 flex-wrap">
                  <Badge tone={SEV_TONES[f.severity] || "default"}>
                    <AlertOctagon className="w-3 h-3" /> {f.severity?.toUpperCase()}
                  </Badge>
                  <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{f.jurisdiction}</span>
                  <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">eff. {f.effective_date}</span>
                  <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">conf {(Number(f.confidence)*100).toFixed(0)}%</span>
                </div>
                <h3 className="mt-2 font-serif text-lg text-paper-100">{f.title}</h3>

                <div className="mt-3 border-l-2 border-verdict-amber pl-3 text-sm">
                  <div className="text-xs font-mono text-paper-400 mb-1">Matched in your text:</div>
                  <code className="text-paper-100 bg-ink-800 px-2 py-0.5 inline-block">{f.match_text}</code>
                </div>

                {f.explanation && <p className="mt-3 text-sm text-paper-300 leading-relaxed">{f.explanation}</p>}

                <div className="mt-3 border-l-2 border-verdict-green pl-3">
                  <div className="text-xs font-mono uppercase tracking-widest2 text-verdict-green mb-1">Remediation</div>
                  <p className="text-sm text-paper-200 leading-relaxed">{f.remediation}</p>
                </div>

                <a href={f.url} target="_blank" rel="noopener noreferrer"
                   className="mt-3 inline-flex items-center gap-1.5 text-xs font-mono text-paper-300 hover:text-verdict-gold">
                  <ExternalLink className="w-3 h-3" /> Read the source
                </a>
              </div>
            ))}
            {(!data.findings || data.findings.length === 0) && (
              <div className="bg-ink-900 p-8 text-center text-paper-400">
                No legal time-bombs detected in the supplied text.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Tile({ k, v, tone }) {
  const colorMap = { green: "text-verdict-green", red: "text-verdict-red", amber: "text-verdict-amber" };
  return (
    <div className="bg-ink-900 p-5">
      <div className={`font-mono text-2xl ${colorMap[tone] || "text-paper-100"}`}>{v}</div>
      <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mt-2">{k}</div>
    </div>
  );
}
