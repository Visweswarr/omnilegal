import React, { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ExternalLink } from "lucide-react";
import { getShare } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

function renderPayload(record) {
  const p = record.payload || {};
  if (record.kind === "diff" && p.impact) {
    return (
      <>
        <div className="font-serif text-lg text-paper-100 mb-2">{p.impact.summary}</div>
        <div className="font-mono text-xs text-paper-400 mb-4">
          {(p.counts?.added || 0)}+ / {(p.counts?.removed || 0)}- / {(p.counts?.reworded || 0)}~
        </div>
        <div className="grid md:grid-cols-2 gap-2 text-sm font-mono">
          {(p.diff_chunks || []).filter(c => c.kind !== "unchanged").slice(0, 24).map((c, i) => (
            <React.Fragment key={i}>
              <div className="border border-verdict-red/40 bg-verdict-red/5 p-2 whitespace-pre-wrap">{c.left || "—"}</div>
              <div className="border border-verdict-green/40 bg-verdict-green/5 p-2 whitespace-pre-wrap">{c.right || "—"}</div>
            </React.Fragment>
          ))}
        </div>
      </>
    );
  }
  if (record.kind === "doctrine" && Array.isArray(p.milestones)) {
    return (
      <ol className="space-y-3">
        {p.milestones.map((m, i) => (
          <li key={i} className="border-l-2 border-verdict-gold pl-3">
            <span className="font-mono text-verdict-gold mr-2">{m.year || "—"}</span>
            <span className="font-serif text-paper-100">{m.case}</span>
            <div className="text-sm text-paper-300 mt-1">{m.summary}</div>
          </li>
        ))}
      </ol>
    );
  }
  return (
    <pre className="text-xs font-mono text-paper-300 overflow-x-auto whitespace-pre-wrap max-h-[700px]">
      {JSON.stringify(p, null, 2)}
    </pre>
  );
}

export default function Share() {
  const { token } = useParams();
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    (async () => {
      setBusy(true);
      try { setData(await getShare(token)); }
      catch (e) { setError(e?.response?.data?.detail || "Share link is invalid or expired."); }
      finally { setBusy(false); }
    })();
  }, [token]);

  return (
    <div className="px-6 md:px-12 py-12 max-w-5xl mx-auto" data-testid="share-page">
      <Badge tone="gold">Public share · read-only</Badge>
      {busy && <div className="mt-8"><Spinner label="Loading shared report…" /></div>}
      <ErrorBlock error={error} />

      {data && (
        <>
          <h1 className="font-serif text-3xl md:text-4xl tracking-tight text-paper-100 mt-3 leading-tight">
            {data.title}
          </h1>
          <div className="mt-2 flex items-center gap-3 font-mono text-[10px] uppercase tracking-widest2 text-paper-400">
            <Badge tone="default">{data.kind}</Badge>
            <span>{new Date(data.created_at * 1000).toLocaleString()}</span>
          </div>

          <div className="mt-8 border border-white/10 bg-ink-800/40 p-4">
            <MonoLabel>Payload</MonoLabel>
            {renderPayload(data)}
          </div>
        </>
      )}
    </div>
  );
}
