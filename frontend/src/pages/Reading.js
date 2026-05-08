import React, { useState } from "react";
import { Highlighter, Save } from "lucide-react";
import { annotateReading, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const SAMPLE = `In Smith v. Jones, the court applied the doctrine of stare decisis to bind itself to its earlier ruling in Doe v. Roe. The defendant's mens rea was held to be a matter of fact for the jury under Section 302 of the Penal Code.

Article 19 of the Constitution permits reasonable restrictions on free speech, but those restrictions are subject to the proportionality test. The court found that the chilling effect of the impugned provision was disproportionate.`;

function renderParagraph(p) {
  if (!p.spans || p.spans.length === 0) return p.text;
  const out = [];
  let cursor = 0;
  p.spans.forEach((sp, i) => {
    if (sp.span_start > cursor) out.push(p.text.slice(cursor, sp.span_start));
    out.push(
      <mark key={i} title={sp.gloss}
        className={`px-0.5 cursor-help ${
          sp.kind === "term"
            ? "bg-verdict-gold/20 border-b border-verdict-gold/60 text-paper-100"
            : "bg-verdict-green/15 border-b border-verdict-green/60 text-paper-100"
        }`}>
        {p.text.slice(sp.span_start, sp.span_end)}
      </mark>
    );
    cursor = sp.span_end;
  });
  if (cursor < p.text.length) out.push(p.text.slice(cursor));
  return out;
}

export default function Reading() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [activeIdx, setActiveIdx] = useState(0);
  const [savedId, setSavedId] = useState(null);

  const submit = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setData(null); setSavedId(null);
    try { setData(await annotateReading(text)); }
    catch (e) { setError(e?.response?.data?.detail || "Annotation failed."); }
    finally { setBusy(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      const r = await saveReport("reading", `Reading — ${new Date().toLocaleDateString()}`, data);
      setSavedId(r.id);
    } catch (e) { setError(e?.response?.data?.detail || "Save failed."); }
  };

  const activePara = data?.paragraphs?.[activeIdx];

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="reading-page">
      <div className="flex items-center gap-3 mb-2">
        <Highlighter className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 12 · Reading Studio</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Read like a <span className="text-verdict-gold">scholar</span>, not a layman.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Paste any case or statute. We auto-annotate every legal term, every citation, and
        produce a one-line summary for each paragraph.
      </p>

      <div className="mt-8 flex gap-2">
        <button
          onClick={() => setText(SAMPLE)}
          className="px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 border border-white/10 text-paper-300"
        >
          Load sample
        </button>
        <button
          onClick={submit} disabled={busy || !text}
          data-testid="reading-submit"
          className="ml-auto px-6 py-2 bg-verdict-gold text-ink-900 font-mono text-xs uppercase tracking-widest2 disabled:opacity-40"
        >
          {busy ? "Annotating…" : "Annotate"}
        </button>
      </div>

      <textarea
        value={text} onChange={(e) => setText(e.target.value)}
        data-testid="reading-input"
        placeholder="Paste a case, statute, or treaty…"
        className="mt-3 w-full h-56 bg-ink-800/40 border border-white/10 p-3 font-mono text-sm text-paper-100"
      />

      {busy && <div className="mt-8"><Spinner label="Annotating…" /></div>}
      <ErrorBlock error={error} />

      {data && !data.error && (
        <>
          <div className="mt-6 flex flex-wrap gap-3 text-xs font-mono text-paper-300">
            <Badge tone="gold">{data.stats?.term_count} terms</Badge>
            <Badge tone="green">{data.stats?.citation_count} citations</Badge>
            <Badge tone="default">{data.stats?.paragraph_count} paragraphs</Badge>
            <button onClick={onSave}
              className="ml-auto px-3 py-1.5 border border-white/10 hover:border-verdict-gold/60 inline-flex items-center gap-2">
              <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0,8)}` : "Save"}
            </button>
          </div>

          <div className="mt-6 grid md:grid-cols-[1fr_320px] gap-4">
            <div className="border border-white/10 bg-paper-100/5 p-6 max-h-[640px] overflow-y-auto">
              {(data.paragraphs || []).map((p, i) => (
                <p
                  key={i}
                  onClick={() => setActiveIdx(i)}
                  className={`mb-4 leading-relaxed font-serif text-lg cursor-pointer ${
                    i === activeIdx ? "text-paper-100" : "text-paper-300"
                  }`}
                >
                  {renderParagraph(p)}
                </p>
              ))}
            </div>

            <div className="border border-white/10 p-4 sticky top-20 self-start">
              <MonoLabel>Paragraph {activeIdx + 1}</MonoLabel>
              {activePara?.summary && (
                <p className="text-sm text-paper-200 italic mb-4">"{activePara.summary}"</p>
              )}
              <MonoLabel>Spans</MonoLabel>
              <ul className="space-y-2">
                {(activePara?.spans || []).map((s, i) => (
                  <li key={i} className="border border-white/10 p-2">
                    <div className="flex items-center gap-2">
                      <Badge tone={s.kind === "term" ? "gold" : "green"}>{s.kind}</Badge>
                      <span className="font-mono text-xs text-paper-200">{s.term}</span>
                    </div>
                    <p className="mt-1 text-xs text-paper-400">{s.gloss}</p>
                  </li>
                ))}
                {(activePara?.spans || []).length === 0 && (
                  <li className="text-xs text-paper-400">No spans detected.</li>
                )}
              </ul>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
