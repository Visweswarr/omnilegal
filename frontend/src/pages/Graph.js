import React, { useMemo, useState } from "react";
import { Network, Save } from "lucide-react";
import { buildGraph, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const KIND_COLOR = {
  topic:           "#D97706",
  document:        "#94A3B8",
  us_case:         "#22C55E",
  uk_case:         "#3B82F6",
  named_case:      "#8B5CF6",
  echr_case:       "#06B6D4",
  usc:             "#EAB308",
  indian_section:  "#F97316",
  treaty_article:  "#EC4899",
};

const EDGE_COLOR = {
  anchored_in:  "#3F3F46",
  loose_mention:"#27272A",
  cites:        "#71717A",
  follows:      "#22C55E",
  overrules:    "#EF4444",
  distinguishes:"#F59E0B",
  criticises:   "#A855F7",
};

// Simple deterministic radial layout
function layoutGraph(nodes, edges, width = 900, height = 560) {
  if (!nodes || nodes.length === 0) return [];
  const seed = nodes.find(n => n.is_seed) || nodes[0];
  const others = nodes.filter(n => n.id !== seed.id);
  const cx = width / 2;
  const cy = height / 2;
  const positioned = [{ ...seed, x: cx, y: cy }];
  others.forEach((n, i) => {
    const angle = (i / Math.max(1, others.length)) * Math.PI * 2;
    const ring = 1 + Math.floor(i / 12);
    const r = 130 + ring * 90;
    positioned.push({ ...n, x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) });
  });
  return positioned;
}

export default function Graph() {
  const [seed, setSeed] = useState("");
  const [data, setData] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);
  const [savedId, setSavedId] = useState(null);

  const submit = async () => {
    if (!seed.trim()) return;
    setBusy(true); setError(null); setData(null); setSelected(null); setSavedId(null);
    try {
      setData(await buildGraph(seed, 40));
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Graph build failed.");
    } finally { setBusy(false); }
  };

  const positioned = useMemo(() => layoutGraph(data?.nodes || [], data?.edges || []), [data]);
  const byId = useMemo(() => {
    const m = new Map();
    positioned.forEach(n => m.set(n.id, n));
    return m;
  }, [positioned]);

  const onSave = async () => {
    if (!data) return;
    try {
      const r = await saveReport("graph", `Citation graph — ${seed}`, data);
      setSavedId(r.id);
    } catch (e) { setError(e?.response?.data?.detail || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="graph-page">
      <div className="flex items-center gap-3 mb-2">
        <Network className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 07 · Citation Graph</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        See how cases <span className="text-verdict-gold">cite</span> each other.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        Type a topic or case name. We extract every citation across the local corpus,
        classify each edge (cites / follows / overrules / distinguishes), and render a graph.
      </p>

      <div className="mt-8 flex gap-3">
        <input
          value={seed} onChange={e => setSeed(e.target.value)}
          placeholder="Seed: e.g. Miranda v. Arizona"
          data-testid="graph-seed"
          className="flex-1 bg-transparent border border-white/10 px-3 py-2 text-paper-100"
        />
        <button
          onClick={submit} disabled={busy || !seed}
          data-testid="graph-submit"
          className="px-6 py-2 bg-verdict-gold text-ink-900 font-mono text-xs uppercase tracking-widest2 disabled:opacity-40"
        >
          {busy ? "Building…" : "Build graph"}
        </button>
      </div>

      {busy && <div className="mt-8"><Spinner label="Building citation graph…" /></div>}
      <ErrorBlock error={error} />

      {data && !data.error && (
        <>
          {data.seed_resolved ? (
            <div className="mt-6 border border-verdict-gold/40 bg-verdict-gold/5 px-4 py-3 text-sm">
              <span className="font-mono text-[10px] uppercase tracking-widest2 text-verdict-gold">Resolved as</span>
              <div className="mt-1 font-serif text-paper-100">{data.seed_display}</div>
              {data.seed_citation && (
                <div className="text-xs font-mono text-paper-400 mt-1">{data.seed_citation}</div>
              )}
            </div>
          ) : (
            <div className="mt-6 border border-white/10 bg-ink-800/40 px-4 py-3 text-sm text-paper-400">
              <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-300">Loose mode</span>
              <span className="ml-2">No canonical case matched — graph shows whatever the retriever returned for "{data.seed}". Edges are <em>loose mentions</em>, not real citations.</span>
            </div>
          )}
          {data.resolution === "matched_no_anchors" && (
            <div className="mt-3 border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-sm text-amber-200">
              Resolved to <strong>{data.seed_canonical}</strong> but no passage in the local corpus actually mentions it. Nothing real to graph — try a different seed or ingest the source.
            </div>
          )}
          {data.stats?.cap_hit && (
            <div className="mt-3 border border-amber-500/40 bg-amber-500/5 px-4 py-3 text-xs font-mono text-amber-200">
              ⚠ Node cap hit at {data.stats.max_nodes} — graph is truncated.
            </div>
          )}

          <div className="mt-6 grid md:grid-cols-[1fr_320px] gap-4">
            <div className="border border-white/10 bg-ink-800/40 relative" style={{ height: 600 }}>
              <svg viewBox="0 0 900 560" className="w-full h-full">
                {(data.edges || []).map((e, i) => {
                  const a = byId.get(e.from); const b = byId.get(e.to);
                  if (!a || !b) return null;
                  return (
                    <line key={i} x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                      stroke={EDGE_COLOR[e.type] || "#52525B"} strokeWidth={1} opacity={0.55} />
                  );
                })}
                {positioned.map(n => (
                  <g key={n.id} onClick={() => setSelected(n)} style={{ cursor: "pointer" }}>
                    <circle cx={n.x} cy={n.y}
                      r={4 + Math.min(14, (n.weight || 1) * 2)}
                      fill={KIND_COLOR[n.kind] || "#94A3B8"}
                      stroke={selected?.id === n.id ? "#FFF" : "#0A0A0A"}
                      strokeWidth={selected?.id === n.id ? 2 : 1} />
                    <text x={n.x + 8} y={n.y - 8} fontSize="9" fill="#E5E7EB"
                      style={{ fontFamily: "JetBrains Mono, monospace", pointerEvents: "none" }}>
                      {(n.label || "").slice(0, 36)}
                    </text>
                  </g>
                ))}
              </svg>
            </div>

            <div className="border border-white/10 p-4">
              <MonoLabel>Selected</MonoLabel>
              {selected ? (
                <>
                  <div className="font-serif text-lg text-paper-100">{selected.label}</div>
                  <div className="mt-2 flex flex-wrap gap-2">
                    <Badge tone="gold">{selected.kind}</Badge>
                    {selected.jurisdiction && <Badge tone="gray">{selected.jurisdiction}</Badge>}
                    {selected.year && <Badge tone="default">{selected.year}</Badge>}
                  </div>
                  <p className="mt-3 text-sm text-paper-400">
                    Inbound weight: {selected.weight}
                  </p>
                  <button
                    onClick={() => { setSeed(selected.label); submit(); }}
                    className="mt-4 px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300"
                  >
                    Re-seed from this node
                  </button>
                </>
              ) : (
                <p className="text-sm text-paper-400">Click any node to inspect.</p>
              )}

              <div className="mt-6">
                <MonoLabel>Stats</MonoLabel>
                <ul className="text-xs font-mono text-paper-300 space-y-0.5">
                  <li>Nodes: {data.stats?.node_count}{data.stats?.cap_hit ? ` (cap ${data.stats?.max_nodes})` : ""}</li>
                  <li>Edges: {data.stats?.edge_count}</li>
                  <li>Anchor passages: {data.stats?.anchor_passages} / {data.stats?.passages_total}</li>
                  <li>Resolution: {data.resolution || (data.seed_resolved ? "matched" : "loose")}</li>
                </ul>
              </div>

              <button
                onClick={onSave}
                data-testid="graph-save"
                className="mt-6 w-full px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 inline-flex items-center justify-center gap-2"
              >
                <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0,8)}` : "Save to library"}
              </button>
            </div>
          </div>

          <Section title="Edge legend" eyebrow="Type">
            <div className="flex flex-wrap gap-3 text-xs font-mono text-paper-300">
              {Object.entries(EDGE_COLOR).map(([k, c]) => (
                <span key={k} className="inline-flex items-center gap-2">
                  <span className="inline-block w-4 h-0.5" style={{ background: c }} />
                  {k}
                </span>
              ))}
            </div>
          </Section>
        </>
      )}
    </div>
  );
}
