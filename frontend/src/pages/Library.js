import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Library as LibIcon, Trash2, Copy, ExternalLink } from "lucide-react";
import { listReports, deleteReport, getReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const KIND_TONES = {
  atlas: "gold", forensics: "green", advocacy: "amber",
  council: "default", diff: "gold", doctrine: "amber",
  graph: "default", redteam: "red", reading: "gold",
};

function renderPreview(record) {
  const p = record.payload || {};
  if (p._truncated) {
    return (
      <div className="text-xs font-mono text-verdict-amber mb-2">
        Note: payload was truncated for storage.
      </div>
    );
  }
  if (record.kind === "diff" && p.impact) {
    return (
      <div className="border border-white/10 bg-ink-800/40 p-4 space-y-2">
        <div className="font-serif text-base text-paper-100">{p.impact.summary}</div>
        <div className="text-xs font-mono text-paper-400">
          {(p.counts?.added || 0)}+ / {(p.counts?.removed || 0)}- / {(p.counts?.reworded || 0)}~
        </div>
      </div>
    );
  }
  if (record.kind === "doctrine" && Array.isArray(p.milestones)) {
    return (
      <ol className="border border-white/10 bg-ink-800/40 p-4 space-y-2 max-h-[500px] overflow-y-auto">
        {p.milestones.map((m, i) => (
          <li key={i} className="border-l-2 border-verdict-gold pl-3">
            <span className="font-mono text-verdict-gold mr-2">{m.year || "—"}</span>
            <span className="font-serif text-paper-100">{m.case}</span>
            <span className="ml-2 font-mono text-[10px] uppercase tracking-widest2 text-paper-400">{m.posture}</span>
          </li>
        ))}
      </ol>
    );
  }
  if (record.kind === "redteam" && p.summary) {
    return (
      <div className="border border-white/10 bg-ink-800/40 p-4 space-y-3">
        <p className="text-paper-100">{p.summary}</p>
        {p.counter_arguments?.length > 0 && (
          <ul className="text-sm text-paper-300 list-disc pl-5 space-y-1">
            {p.counter_arguments.slice(0, 5).map((c, i) => <li key={i}>{c.point}</li>)}
          </ul>
        )}
      </div>
    );
  }
  return (
    <pre className="border border-white/10 bg-ink-800/40 p-4 text-xs font-mono text-paper-300 overflow-x-auto whitespace-pre-wrap max-h-[600px]">
      {JSON.stringify(p, null, 2)}
    </pre>
  );
}

export default function Library() {
  const [items, setItems] = useState([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);
  const [opened, setOpened] = useState(null);
  const [filter, setFilter] = useState("");

  const refresh = async () => {
    setBusy(true);
    try { const r = await listReports(filter || ""); setItems(r.items || []); }
    catch (e) { setError(e?.response?.data?.detail || "Load failed."); }
    finally { setBusy(false); }
  };

  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [filter]);

  const onDelete = async (id) => {
    if (!window.confirm("Delete this saved report?")) return;
    try { await deleteReport(id); setItems(items.filter(x => x.id !== id)); }
    catch (e) { setError(e?.response?.data?.detail || "Delete failed."); }
  };

  const open = async (id) => {
    try { setOpened(await getReport(id)); }
    catch (e) { setError(e?.response?.data?.detail || "Open failed."); }
  };

  const shareUrl = (token) => `${window.location.origin}/share/${token}`;

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="library-page">
      <div className="flex items-center gap-3 mb-2">
        <LibIcon className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 13 · Library & Share</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Your saved <span className="text-verdict-gold">verdicts</span>.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Every Atlas, Forensics, Advocacy, Diff, Doctrine, Graph, Red Team and Reading
        report you save lands here. Each has a public read-only share link.
      </p>

      <div className="mt-8 flex flex-wrap gap-2">
        {["", "atlas", "forensics", "advocacy", "diff", "doctrine", "graph", "redteam", "reading", "council"].map(k => (
          <button
            key={k || "all"}
            onClick={() => setFilter(k)}
            className={`px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest2 border ${
              filter === k ? "border-verdict-gold text-verdict-gold" : "border-white/10 text-paper-300"
            }`}
          >
            {k || "all"}
          </button>
        ))}
      </div>

      {busy && <div className="mt-8"><Spinner label="Loading library…" /></div>}
      <ErrorBlock error={error} />

      <div className="mt-6 grid md:grid-cols-3 gap-3">
        {items.map(r => (
          <div key={r.id} className="border border-white/10 p-4 bg-ink-800/40">
            <div className="flex items-center justify-between gap-2">
              <Badge tone={KIND_TONES[r.kind] || "default"}>{r.kind}</Badge>
              <button onClick={() => onDelete(r.id)} className="text-paper-400 hover:text-verdict-red">
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>
            <h3 className="mt-2 font-serif text-lg text-paper-100 leading-snug">{r.title}</h3>
            <div className="mt-1 font-mono text-[10px] uppercase tracking-widest2 text-paper-400">
              {new Date(r.created_at * 1000).toLocaleString()}
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button onClick={() => open(r.id)}
                className="px-2 py-1 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300">
                Open
              </button>
              <Link to={`/share/${r.share_token}`}
                className="px-2 py-1 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 inline-flex items-center gap-1">
                <ExternalLink className="w-3 h-3" /> Share
              </Link>
              <button
                onClick={() => navigator.clipboard.writeText(shareUrl(r.share_token))}
                className="px-2 py-1 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 inline-flex items-center gap-1"
              >
                <Copy className="w-3 h-3" /> Copy link
              </button>
            </div>
          </div>
        ))}
        {!busy && items.length === 0 && (
          <div className="md:col-span-3 text-center text-paper-400 text-sm py-12">
            Nothing saved yet — every pillar page has a "Save to library" button.
          </div>
        )}
      </div>

      {opened && (
        <Section title={opened.title} eyebrow={opened.kind}>
          {renderPreview(opened)}
          <button onClick={() => setOpened(null)}
            className="mt-3 px-3 py-1.5 border border-white/10 font-mono text-[10px] uppercase tracking-widest2 text-paper-300">
            Close
          </button>
        </Section>
      )}
    </div>
  );
}
