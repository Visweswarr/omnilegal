import React, { useEffect, useState, useMemo } from "react";
import { ComposableMap, Geographies, Geography } from "react-simple-maps";
import { Globe, MapPin, ShieldAlert, X, ChevronRight, Stamp } from "lucide-react";
import { analyzeAtlas } from "../lib/api";
import { NUM_TO_A3 } from "../lib/isoNumericToA3";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

// Public-domain world TopoJSON
const GEO_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json";

const COLOR_BY_VERDICT = {
  legal:      { fill: "#0F2A18", border: "#16A34A" },
  restricted: { fill: "#3a2103", border: "#D97706" },
  illegal:    { fill: "#3b0d0d", border: "#DC2626" },
  no_data:    { fill: "#171717", border: "#2a2a2a" },
};

const EU_MEMBERS_A3 = [
  "AUT","BEL","BGR","HRV","CYP","CZE","DNK","EST","FIN","FRA","DEU","GRC","HUN",
  "IRL","ITA","LVA","LTU","LUX","MLT","NLD","POL","PRT","ROU","SVK","SVN","ESP","SWE"
];

const EXAMPLES = [
  "Death penalty for drug trafficking",
  "Encryption export controls",
  "Hate speech laws online",
  "Same-sex marriage recognition",
  "Strict abortion bans",
  "AUT","BEL","BGR","HRV","CYP","CZE","DNK","EST","FIN","FRA","DEU","GRC","HUN",
  "IRL","ITA","LVA","LTU","LUX","MLT","NLD","POL","PRT","ROU","SVK","SVN","ESP","SWE"
];

const EXAMPLES = [
  "Death penalty for drug trafficking",
  "Encryption export controls",
  "Hate speech laws online",
  "Same-sex marriage recognition",
  "Strict abortion bans",
  "Surveillance without warrant",
  "Forced disappearance",
  "Detention without trial",
];

export default function Atlas() {
  const [topic, setTopic] = useState("");
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [hovered, setHovered] = useState(null);
  const [active, setActive] = useState(null);

  const byA3 = useMemo(() => {
    const m = {};
    (data?.countries || []).forEach(c => {
      if (c.iso_a3 === "EUR") {
        EU_MEMBERS_A3.forEach(a3 => { m[a3] = c; });
      } else {
        m[c.iso_a3] = c;
      }
    });
    return m;
  }, [data]);

  const byName = useMemo(() => {
    const m = {};
    (data?.countries || []).forEach(c => {
      if (c.name) m[String(c.name).toLowerCase()] = c;
    });
    return m;
  }, [data]);

  const submit = async () => {
    if (!topic.trim()) return;
    setBusy(true); setError(null); setData(null); setActive(null);
    try {
      const res = await analyzeAtlas(topic.trim(), true);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Atlas failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="atlas-page">
      <div className="flex items-center gap-3 mb-2">
        <Globe className="w-5 h-5 text-verdict-gold" strokeWidth={1.5} />
        <Badge tone="gold">Pillar 01 · Conflict Atlas</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Color the world<br className="hidden md:block" /> by what's <span className="text-verdict-gold">legal</span>.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl">
        Type any legal topic. We retrieve grounded primary sources for India, US, UK, Russia, Israel, the EU,
        and France through live Legifrance when credentials are present, then color additional countries with clearly tagged inference.
      </p>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
        <input
          className="bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold"
          placeholder="e.g. death penalty for drug trafficking"
          value={topic}
          onChange={e => setTopic(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          data-testid="atlas-topic-input"
        />
        <button
          onClick={submit}
          disabled={busy}
          className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50"
          data-testid="atlas-analyze-btn"
        >
          {busy ? "Analyzing…" : "Analyze"}
        </button>
      </div>

      {/* Examples */}
      <div className="mt-3 flex flex-wrap gap-2">
        <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mr-2 self-center">Examples</span>
        {EXAMPLES.map(ex => (
           <button
             key={ex}
             onClick={() => setTopic(ex)}
             className="text-xs font-mono text-paper-300 border border-white/10 px-2 py-1 hover:border-verdict-gold hover:text-paper-100"
             data-testid={`atlas-example-${ex.replace(/\s/g, "-").toLowerCase()}`}
           >
             {ex}
           </button>
        ))}
      </div>

      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}
      {busy && <div className="mt-6"><Spinner label="Building world map…" /></div>}

      {data && (
        <div className="mt-10 grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-8">
          <div>
            {/* Verdict stamp */}
            <div className="flex flex-wrap items-center gap-3 mb-5">
              <span className="verdict-stamp inline-flex items-center gap-2 border-2 border-verdict-gold text-verdict-gold px-3 py-1 font-mono text-xs uppercase tracking-widest2">
                <Stamp className="w-3 h-3" strokeWidth={2} /> Verdict · {(data.verdict || "neutral").replace(/_/g, " ")}
              </span>
              <span className="font-mono text-xs text-paper-300">{data.verdict_human}</span>
            </div>

            {/* Legend */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-white/10 border border-white/10 mb-4">
              <Legend label="Legal"      tone="green"  count={(data.label_counts?.legal || 0) + (data.label_counts?.ai_inferred_legal || 0)} />
              <Legend label="Restricted" tone="amber"  count={(data.label_counts?.restricted || 0) + (data.label_counts?.ai_inferred_restricted || 0)} />
              <Legend label="Illegal"    tone="red"    count={(data.label_counts?.illegal || 0) + (data.label_counts?.ai_inferred_illegal || 0)} />
              <Legend label="No data"    tone="gray"   count={data.label_counts?.no_data || 0} />
            </div>

            {/* Map */}
            <div className="bg-ink-800 border border-white/10 p-2 md:p-4" data-testid="atlas-map">
              <ComposableMap
                projection="geoMercator"
                projectionConfig={{ center: [10, 18], scale: 130 }}
                style={{ width: "100%", height: "auto" }}
              >
                <Geographies geography={GEO_URL}>
                  {({ geographies }) =>
                    geographies.map(geo => {
                      const a3 = NUM_TO_A3[String(geo.id).padStart(3, "0")];
                      const geoName = String(geo.properties?.name || "").toLowerCase();
                      const country = (a3 ? byA3[a3] : null) || byName[geoName] || null;
                      const color = COLOR_BY_VERDICT[country?.verdict] || COLOR_BY_VERDICT.no_data;
                      return (
                        <Geography
                          key={geo.rsmKey}
                          geography={geo}
                          fill={color.fill}
                          stroke={color.border}
                          strokeWidth={country ? 0.7 : 0.3}
                          style={{
                            default:  { outline: "none" },
                            hover:    { fill: country ? "#D97706" : "#222", outline: "none", cursor: country ? "pointer" : "default" },
                            pressed:  { outline: "none" },
                          }}
                          onMouseEnter={() => setHovered(country || null)}
                          onMouseLeave={() => setHovered(null)}
                          onClick={() => country && setActive(country)}
                          data-testid={(a3 || country?.iso_a3) ? `atlas-country-${a3 || country.iso_a3}` : undefined}
                        />
                      );
                    })
                  }
                </Geographies>
              </ComposableMap>
              {hovered && (
                <div className="mt-2 px-3 py-2 bg-ink-900 border border-white/10 font-mono text-xs text-paper-300 inline-flex items-center gap-2">
                  <MapPin className="w-3 h-3 text-verdict-gold" />
                  <span className="text-paper-100">{hovered.name}</span> ·
                  <span className={`uppercase tracking-widest2 ${
                    hovered.verdict === "legal"      ? "text-verdict-green" :
                    hovered.verdict === "restricted" ? "text-verdict-amber" :
                    hovered.verdict === "illegal"    ? "text-verdict-red"   : "text-paper-400"
                  }`}>{hovered.verdict.replace(/_/g, " ")}</span>
                  · click for details
                </div>
              )}
            </div>

            {/* Country pills below the map */}
            <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10">
              {(data.countries || []).map(c => (
                <button
                  key={c.iso_a3}
                  onClick={() => setActive(c)}
                  className="bg-ink-900 hover:bg-ink-800 px-4 py-3 flex items-center justify-between text-left"
                  data-testid={`atlas-country-row-${c.iso_a3}`}
                >
                  <div className="flex items-center gap-3">
                    <span className={`w-2 h-2 ${
                      c.verdict === "legal"      ? "bg-verdict-green" :
                      c.verdict === "restricted" ? "bg-verdict-amber" :
                      c.verdict === "illegal"    ? "bg-verdict-red"   : "bg-paper-400"
                    }`} />
                    <span className="text-paper-100 font-medium">{c.name}</span>
                    {evidenceLabel(c.evidence_level) && (
                      <span className="text-[9px] font-mono uppercase tracking-widest2 text-paper-400 border border-white/10 px-1">
                        {evidenceLabel(c.evidence_level)}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-paper-400">
                    <span className="font-mono">{(c.confidence || 0).toFixed(2)}</span>
                    <ChevronRight className="w-3 h-3" />
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Country drawer (always visible on desktop, summary panel) */}
          <aside className="lg:sticky lg:top-24 self-start border border-white/10 bg-ink-900 max-h-[80vh] overflow-y-auto" data-testid="atlas-drawer">
            {!active ? (
              <div className="p-6">
                <MonoLabel>International baseline</MonoLabel>
                <p className="text-sm text-paper-300 leading-relaxed whitespace-pre-wrap">
                  {data.international_position || "No baseline retrieved."}
                </p>
                <div className="mt-6">
                  <MonoLabel>How to read this map</MonoLabel>
                  <ul className="text-sm text-paper-400 leading-relaxed space-y-2">
                    <li><span className="text-verdict-green">●</span> Local — built on retrieved primary sources from the local corpus.</li>
                    <li>Live and HF tags mark official API or dataset-backed reference material; AI marks inference without retrieved primary authority.</li>
                    <li>Confidence column shows the model's stated certainty (0–1).</li>
                  </ul>
                </div>
              </div>
            ) : (
              <div className="p-6">
                <div className="flex items-center justify-between mb-3">
                  <Badge tone={tone(active.verdict)}>
                    {active.verdict.replace(/_/g, " ")} · {(active.confidence || 0).toFixed(2)}
                  </Badge>
                  <button onClick={() => setActive(null)} className="text-paper-300 hover:text-paper-100" data-testid="atlas-drawer-close">
                    <X className="w-4 h-4" />
                  </button>
                </div>
                <h3 className="font-serif text-3xl text-paper-100 leading-tight">{active.name}</h3>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Badge tone={evidenceTone(active.evidence_level)}>{evidenceText(active.evidence_level)}</Badge>
                  {active.vclt_27 && <Badge tone="red">VCLT Art. 27</Badge>}
                </div>

                <div className="mt-4">
                  <MonoLabel>Headline</MonoLabel>
                  <div className="text-paper-200 text-sm">{active.headline}</div>
                </div>

                <div className="mt-4">
                  <MonoLabel>Explanation</MonoLabel>
                  <div className="text-paper-300 text-sm leading-relaxed whitespace-pre-wrap">
                    {active.explanation}
                  </div>
                </div>

                {(active.rationale_spans || []).length > 0 && (
                  <div className="mt-4">
                    <MonoLabel>Rationale spans</MonoLabel>
                    <ul className="space-y-2">
                      {active.rationale_spans.map((s, i) => (
                        <li key={i} className="text-xs font-mono text-paper-300 bg-ink-800 border-l-2 border-verdict-gold pl-3 py-2">
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {(active.sources || []).length > 0 && (
                  <div className="mt-4">
                    <MonoLabel>Domestic sources ({active.sources.length})</MonoLabel>
                    <ul className="space-y-2">
                      {active.sources.slice(0, 5).map((s, i) => (
                        <li key={i} className="text-xs font-mono text-paper-300 border border-white/10 p-2">
                          <div className="text-paper-100">{s.source_name}</div>
                          <div className="text-paper-400">{s.marker} · {s.jurisdiction || "—"} · p.{s.page || "?"}</div>
                          <div className="text-paper-400 mt-1 line-clamp-3">{s.excerpt}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {(active.international_sources || []).length > 0 && (
                  <div className="mt-4">
                    <MonoLabel>International sources ({active.international_sources.length})</MonoLabel>
                    <ul className="space-y-2">
                      {active.international_sources.slice(0, 3).map((s, i) => (
                        <li key={i} className="text-xs font-mono text-paper-300 border border-white/10 p-2">
                          <div className="text-paper-100">{s.source_name}</div>
                          <div className="text-paper-400">{s.marker} · {s.jurisdiction || "—"} · p.{s.page || "?"}</div>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {active.evidence_level === "ai_inferred" && (
                  <div className="mt-4 border border-verdict-amber/40 bg-verdict-amber/10 p-3 text-xs text-paper-200">
                    <ShieldAlert className="w-3 h-3 inline-block mr-1 text-verdict-amber" />
                    AI-inferred verdict — not backed by a retrieved primary source. Verify with the Live Authority engine before citing.
                  </div>
                )}
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function tone(v) {
  if (v === "legal") return "green";
  if (v === "restricted") return "amber";
  if (v === "illegal") return "red";
  return "gray";
}

function evidenceLabel(level) {
  if (level === "local_corpus") return "LOCAL";
  if (level === "live_authority") return "LIVE";
  if (level === "hf_reference") return "HF";
  if (level === "ai_inferred") return "AI";
  return "";
}

function evidenceText(level) {
  if (level === "local_corpus") return "Local corpus";
  if (level === "live_authority") return "Live authority";
  if (level === "hf_reference") return "HF reference";
  if (level === "ai_inferred") return "AI-inferred";
  return "No data";
}

function evidenceTone(level) {
  if (level === "local_corpus" || level === "live_authority") return "green";
  if (level === "hf_reference" || level === "ai_inferred") return "amber";
  return "gray";
}

function Legend({ label, count, tone: t }) {
  const klass = t === "green" ? "text-verdict-green"
              : t === "amber" ? "text-verdict-amber"
              : t === "red"   ? "text-verdict-red"
              : "text-paper-400";
  return (
    <div className="bg-ink-900 px-4 py-3 flex items-center justify-between">
      <span className={`text-[10px] font-mono uppercase tracking-widest2 ${klass}`}>{label}</span>
      <span className="font-mono text-paper-100">{count}</span>
    </div>
  );
}
