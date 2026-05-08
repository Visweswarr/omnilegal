import React, { useState } from "react";
import { History, Save, ExternalLink } from "lucide-react";
import { trackDoctrine, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const POSTURE_TONES = {
  introduced: "gold",
  expanded:   "green",
  narrowed:   "amber",
  applied:    "default",
  overruled:  "red",
};

const POPULAR = [
  { d: "basic structure",         j: "India" },
  { d: "chilling effect",         j: "United States" },
  { d: "margin of appreciation",  j: "ECHR" },
  { d: "proportionality",         j: "ECHR" },
  { d: "Miranda warnings",        j: "United States" },
  { d: "doctrine of necessity",   j: "Comparative" },
];

export default function TimeMachine() {
  const [doctrine, setDoctrine]     = useState("");
  const [jurisdiction, setJ]        = useState("Comparative");
  const [data, setData]             = useState(null);
  const [busy, setBusy]             = useState(false);
  const [error, setError]           = useState(null);
  const [savedId, setSavedId]       = useState(null);

  const submit = async () => {
    if (!doctrine.trim()) return;
    setBusy(true); setError(null); setData(null); setSavedId(null);
    try {
      setData(await trackDoctrine(doctrine, jurisdiction));
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Doctrine tracking failed.");
    } finally { setBusy(false); }
  };

  const onSave = async () => {
    if (!data) return;
    try {
      const r = await saveReport("doctrine", `${doctrine} (${jurisdiction})`, data);
      setSavedId(r.id);
    } catch (e) { setError(e?.response?.data?.detail || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-6xl mx-auto" data-testid="timemachine-page">
      <div className="flex items-center gap-3 mb-2">
        <History className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 08 · Doctrine Time Machine</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Track a doctrine across <span className="text-verdict-gold">time</span>.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Pick a doctrine and a jurisdiction. We trace which case introduced it, expanded
        it, narrowed it, applied it, or overruled it.
      </p>

      <div className="mt-8 grid md:grid-cols-[1fr_240px_auto] gap-3">
        <input
          value={doctrine} onChange={e => setDoctrine(e.target.value)}
          placeholder="Doctrine, e.g. basic structure"
          data-testid="time-doctrine"
          className="bg-transparent border border-white/10 px-3 py-2 text-paper-100"
        />
        <input
          value={jurisdiction} onChange={e => setJ(e.target.value)}
          placeholder="Jurisdiction"
          data-testid="time-jurisdiction"
          className="bg-transparent border border-white/10 px-3 py-2 text-paper-100"
        />
        <button
          onClick={submit} disabled={busy || !doctrine}
          data-testid="time-submit"
          className="px-6 py-2 bg-verdict-gold text-ink-900 font-mono text-xs uppercase tracking-widest2 disabled:opacity-40"
        >
          {busy ? "Tracing…" : "Trace"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        {POPULAR.map(p => (
          <button
            key={p.d}
            onClick={() => { setDoctrine(p.d); setJ(p.j); }}
            className="px-2 py-1 font-mono text-[10px] uppercase tracking-widest2 border border-white/10 text-paper-300 hover:border-verdict-gold/60"
          >
            {p.d} · {p.j}
          </button>
        ))}
      </div>

      {busy && <div className="mt-8"><Spinner label="Tracing doctrine…" /></div>}
      <ErrorBlock error={error} />

      {data && !data.error && (
        <>
          <Section title="Narrative arc" eyebrow={data.jurisdiction}>
            <div className="border border-white/10 bg-ink-800/40 p-5">
              {data.inception_case && (
                <div className="mb-3"><MonoLabel>Inception</MonoLabel><span className="font-serif text-lg text-paper-100">{data.inception_case}</span></div>
              )}
              <p className="text-paper-200 leading-relaxed">{data.summary}</p>
              {data.current_status && (
                <div className="mt-3 text-sm text-paper-400 italic">Today: {data.current_status}</div>
              )}
              <button
                onClick={onSave}
                data-testid="time-save"
                className="mt-4 px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 inline-flex items-center gap-2"
              >
                <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0,8)}` : "Save to library"}
              </button>
            </div>
          </Section>

          <Section title="Timeline" eyebrow={`${data.milestones?.length || 0} milestones`}>
            <ol className="relative border-l border-white/10 ml-3 space-y-6 pl-6">
              {(data.milestones || []).map((m, i) => (
                <li key={i} className="relative">
                  <span className="absolute -left-8 top-1 w-3 h-3 bg-verdict-gold border border-ink-900" />
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-mono text-2xl text-verdict-gold">{m.year || "—"}</span>
                    <span className="font-serif text-lg text-paper-100">{m.case}</span>
                    <Badge tone={POSTURE_TONES[m.posture] || "default"}>{m.posture}</Badge>
                    {m.court && <Badge tone="gray">{m.court}</Badge>}
                  </div>
                  <p className="mt-1 text-sm text-paper-300">{m.summary}</p>
                  {m.citation && (
                    <a href={m.citation} target="_blank" rel="noreferrer"
                       className="mt-1 inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-widest2 text-verdict-gold">
                      Source <ExternalLink className="w-3 h-3" />
                    </a>
                  )}
                </li>
              ))}
            </ol>
          </Section>
        </>
      )}
    </div>
  );
}
