import React, { useState, useMemo } from "react";
import { ShieldCheck, Stamp, AlertTriangle, FileSearch, Copy } from "lucide-react";
import { verifyForensics } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

const SAMPLE = `In Maneja v. Maneja, 50 U.S. 75 (1957), the Supreme Court held that custodial interrogation requires Miranda warnings. Section 124A of the Indian Penal Code criminalises sedition. Article 19(2) of the Constitution permits reasonable restrictions on free speech. The European Court of Human Rights ruled in Klass v. Germany [1978] ECHR 4 that secret surveillance is permissible only with adequate safeguards.`;

const STATUS_TONES = {
  verified:     { tone: "green",  label: "Verified" },
  partial:      { tone: "amber",  label: "Partial"  },
  suspicious:   { tone: "red",    label: "Suspicious" },
  hallucinated: { tone: "red",    label: "Hallucinated" },
  not_found:    { tone: "red",    label: "Not found" },
  no_citations: { tone: "gray",   label: "No citation" },
};

export default function Forensics() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setData(null);
    try {
      const res = await verifyForensics(text);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Forensics failed");
    } finally { setBusy(false); }
  };

  const annotated = useMemo(() => {
    if (!data?.annotated_segments) return null;
    return data.annotated_segments.map((seg, i) => (
      <mark key={i} className={`${seg.status}-mark`} data-testid={`forensics-segment-${seg.status}`}>
        {seg.sentence}{" "}
      </mark>
    ));
  }, [data]);

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="forensics-page">
      <div className="flex items-center gap-3 mb-2">
        <ShieldCheck className="w-5 h-5 text-verdict-green" strokeWidth={1.5} />
        <Badge tone="green">Pillar 02 · Citation Forensics</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Verify any legal text.<br className="hidden md:block" /> Even one written by another <span className="text-verdict-gold">AI</span>.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl">
        Paste any legal prose. We extract every citation, retrieve the closest passages from our 22-collection corpus,
        score n-gram overlap, and grade each claim — verified, partial, suspicious, or hallucinated.
        OmniLegal is the trust layer for legal AI.
      </p>

      <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div>
          <div className="flex items-center justify-between mb-2">
            <MonoLabel>Input · Paste suspect text</MonoLabel>
            <button
              onClick={() => setText(SAMPLE)}
              className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 hover:text-paper-100"
              data-testid="forensics-sample-btn"
            >
              Load sample
            </button>
          </div>
          <textarea
            className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold min-h-[260px] leading-relaxed"
            placeholder="Paste a paragraph of legal text. Citations like 'Section 124A IPC', 'Article 19(2)', '50 U.S. 75', or '[2019] EWHC 123' will be extracted automatically."
            value={text}
            onChange={e => setText(e.target.value)}
            data-testid="forensics-input"
          />
          <div className="mt-3 flex items-center gap-3">
            <button
              onClick={submit}
              disabled={busy}
              className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50 inline-flex items-center gap-2"
              data-testid="forensics-verify-btn"
            >
              <FileSearch className="w-4 h-4" strokeWidth={2} /> {busy ? "Auditing…" : "Audit citations"}
            </button>
            <button
              onClick={() => { setText(""); setData(null); setError(null); }}
              className="px-4 py-3 border border-white/10 text-paper-300 hover:bg-white/5"
              data-testid="forensics-reset-btn"
            >
              Reset
            </button>
          </div>
          {busy && <div className="mt-4"><Spinner label="Cross-referencing corpus…" /></div>}
          {error && <div className="mt-4"><ErrorBlock error={error} /></div>}
        </div>

        <div className="border border-white/10 bg-ink-800 p-5 min-h-[260px]" data-testid="forensics-output">
          <div className="flex items-center justify-between mb-3">
            <MonoLabel>Annotated rendering</MonoLabel>
            {data && (
              <span className="verdict-stamp inline-flex items-center gap-2 border-2 border-verdict-gold text-verdict-gold px-2 py-0.5 font-mono text-[10px] uppercase tracking-widest2">
                <Stamp className="w-3 h-3" strokeWidth={2} />
                {data.overall_grade.replace(/_/g, " ")}
              </span>
            )}
          </div>
          {data ? (
            <div className="font-serif text-lg leading-relaxed text-paper-200 max-w-prose" data-testid="forensics-annotated">
              {annotated}
            </div>
          ) : (
            <div className="text-paper-400 text-sm">Run an audit to see citations highlighted in green (verified), amber (partial), or red (hallucinated / not found).</div>
          )}
        </div>
      </div>

      {data && (
        <div className="mt-10 grid grid-cols-1 lg:grid-cols-3 gap-px bg-white/10 border border-white/10">
          <Stat label="Sentences"   value={data.summary?.total_sentences} />
          <Stat label="Citations"   value={data.summary?.total_citations} />
          <Stat label="Trust score" value={`${(data.overall_score * 100).toFixed(0)}%`} highlight />
          <Stat label="Verified"    value={data.summary?.verified}     tone="green" />
          <Stat label="Partial"     value={data.summary?.partial}      tone="amber" />
          <Stat label="Suspicious"  value={data.summary?.suspicious}   tone="red"   />
          <Stat label="Hallucinated"value={data.summary?.hallucinated} tone="red"   />
          <Stat label="Not found"   value={data.summary?.not_found}    tone="red"   />
          <Stat label="No citations"value={data.summary?.no_citations} tone="gray"  />
        </div>
      )}

      {data && data.claims?.length > 0 && (
        <div className="mt-10">
          <MonoLabel>Claim-by-claim verdict ({data.claims.length})</MonoLabel>
          <div className="grid grid-cols-1 gap-px bg-white/10 border border-white/10">
            {data.claims.map((c, i) => {
              const t = STATUS_TONES[c.status] || STATUS_TONES.no_citations;
              return (
                <div key={i} className="bg-ink-900 p-5" data-testid={`forensics-claim-${i}`}>
                  <div className="flex flex-wrap items-center gap-2 mb-2">
                    <Badge tone={t.tone}>{t.label}</Badge>
                    <span className="font-mono text-xs text-paper-400">overlap · {(c.overlap * 100).toFixed(0)}%</span>
                    <span className="font-mono text-xs text-paper-400 border border-white/10 px-1.5">{c.citation_kind}</span>
                    <span className="font-mono text-xs text-paper-200">{c.citation_text}</span>
                  </div>
                  <div className="font-serif text-paper-200 mb-2">{c.sentence}</div>
                  {c.best_match && (
                    <div className="border-l-2 border-verdict-gold pl-3 py-2 bg-ink-800">
                      <div className="font-mono text-[10px] text-paper-400 uppercase tracking-widest2 mb-1">
                        Closest match · {c.best_match.source_name}
                        {c.best_match.page && ` · p.${c.best_match.page}`}
                        {c.best_match.jurisdiction && ` · ${c.best_match.jurisdiction}`}
                      </div>
                      <div className="text-sm text-paper-300">{c.best_match.excerpt}</div>
                    </div>
                  )}
                  {!c.best_match && c.status === "not_found" && (
                    <div className="border border-verdict-red/40 bg-verdict-red/10 px-3 py-2 text-xs text-verdict-red flex items-center gap-2">
                      <AlertTriangle className="w-3 h-3" /> No matching passage in any of the 22 collections.
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, tone, highlight }) {
  const klass = tone === "green" ? "text-verdict-green"
             : tone === "amber" ? "text-verdict-amber"
             : tone === "red"   ? "text-verdict-red"
             : tone === "gray"  ? "text-paper-400"
             : "text-paper-100";
  return (
    <div className="bg-ink-900 p-5">
      <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mb-1">{label}</div>
      <div className={`font-mono text-2xl ${highlight ? "text-verdict-gold" : klass}`}>{value ?? "—"}</div>
    </div>
  );
}
