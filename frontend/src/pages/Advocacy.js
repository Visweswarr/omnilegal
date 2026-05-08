import React, { useState } from "react";
import { FileText, Printer, Stamp, ChevronDown } from "lucide-react";
import { generateAdvocacy } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

const COUNTRIES = [
  { key: "india",   name: "India" },
  { key: "us",      name: "United States" },
  { key: "uk",      name: "United Kingdom" },
  { key: "russia",  name: "Russia" },
  { key: "israel",  name: "Israel" },
  { key: "eu",      name: "European Union" },
  { key: "germany", name: "Germany" },
  { key: "france",  name: "France" },
  { key: "china",   name: "China" },
  { key: "japan",   name: "Japan" },
  { key: "brazil",  name: "Brazil" },
  { key: "australia", name: "Australia" },
  { key: "canada",  name: "Canada" },
];

const POSITIONS = [
  { value: "FOR",     label: "FOR · Support" },
  { value: "AGAINST", label: "AGAINST · Oppose" },
  { value: "NEUTRAL", label: "NEUTRAL · Balanced" },
];

const TOPIC_EXAMPLES = [
  "Nuclear weapons modernization",
  "Encryption export controls",
  "Universal jurisdiction over war crimes",
  "Climate liability for fossil fuel exporters",
  "Right to be forgotten online",
  "Detention without trial",
];

export default function Advocacy() {
  const [country, setCountry] = useState(COUNTRIES[0]);
  const [topic, setTopic] = useState("");
  const [position, setPosition] = useState("FOR");
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!topic.trim()) return;
    setBusy(true); setError(null); setData(null);
    try {
      const res = await generateAdvocacy({
        country_key: country.key,
        country_name: country.name,
        topic: topic.trim(),
        position,
        include_conflict: true,
      });
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Generation failed");
    } finally { setBusy(false); }
  };

  const packet = data?.packet;

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="advocacy-page">
      <div className="flex items-center gap-3 mb-2 no-print">
        <FileText className="w-5 h-5 text-paper-100" strokeWidth={1.5} />
        <Badge tone="default">Pillar 03 · Advocacy Studio</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight no-print">
        A complete advocacy packet.<br className="hidden md:block" /> In one click.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl no-print">
        Pick a country, a topic, and a position. Get a print-ready position paper, a punchy opening speech,
        five rebuttal cards, and leverage cards — every assertion grounded in retrieved primary sources.
      </p>

      {/* Form */}
      <div className="mt-10 grid grid-cols-1 md:grid-cols-[2fr_3fr_2fr_auto] gap-3 no-print" data-testid="advocacy-form">
        <Selector
          label="Country"
          value={country.key}
          options={COUNTRIES.map(c => ({ value: c.key, label: c.name }))}
          onChange={k => setCountry(COUNTRIES.find(c => c.key === k))}
          testId="advocacy-country"
        />
        <input
          className="bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold"
          placeholder="Topic — e.g. nuclear weapons modernization"
          value={topic}
          onChange={e => setTopic(e.target.value)}
          data-testid="advocacy-topic"
        />
        <Selector
          label="Position"
          value={position}
          options={POSITIONS}
          onChange={setPosition}
          testId="advocacy-position"
        />
        <button
          onClick={submit}
          disabled={busy}
          className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50"
          data-testid="advocacy-generate-btn"
        >
          {busy ? "Drafting…" : "Generate Packet"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2 no-print">
        <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mr-2 self-center">Topic ideas</span>
        {TOPIC_EXAMPLES.map(t => (
          <button
            key={t}
            onClick={() => setTopic(t)}
            className="text-xs font-mono text-paper-300 border border-white/10 px-2 py-1 hover:border-verdict-gold hover:text-paper-100"
            data-testid={`advocacy-example-${t.replace(/\s/g, "-").toLowerCase()}`}
          >
            {t}
          </button>
        ))}
      </div>

      {busy && <div className="mt-6 no-print"><Spinner label="Drafting position paper, speech, rebuttals & leverage…" /></div>}
      {error && <div className="mt-6 no-print"><ErrorBlock error={error} /></div>}

      {data && data.error && !packet && (
        <div className="mt-6 no-print"><ErrorBlock error={data.error} /></div>
      )}

      {packet && (
        <div className="mt-12">
          <div className="flex items-center gap-3 mb-6 no-print" data-testid="advocacy-output-header">
            <span className="verdict-stamp inline-flex items-center gap-2 border-2 border-verdict-gold text-verdict-gold px-3 py-1 font-mono text-xs uppercase tracking-widest2">
              <Stamp className="w-3 h-3" strokeWidth={2} /> Packet Generated
            </span>
            <Badge tone="gold">{country.name}</Badge>
            <Badge tone={position === "FOR" ? "green" : position === "AGAINST" ? "red" : "default"}>{position}</Badge>
            <button
              onClick={() => window.print()}
              className="ml-auto px-4 py-2 border border-white/15 text-paper-100 inline-flex items-center gap-2 hover:bg-white/5"
              data-testid="advocacy-print-btn"
            >
              <Printer className="w-4 h-4" /> Print packet
            </button>
          </div>

          {/* Position Paper — editorial cream paper */}
          {packet.position_paper && (
            <div className="editorial-paper border border-white/10 p-8 md:p-12 mb-8" data-testid="advocacy-position-paper">
              <div className="font-mono text-[10px] uppercase tracking-widest2 text-ink-400 mb-2">Position Paper · {country.name}</div>
              <h2 className="font-serif text-3xl md:text-4xl text-ink-900 mb-6 leading-tight">{packet.position_paper.title}</h2>
              <div className="max-w-prose font-serif text-ink-700 leading-relaxed space-y-5 text-lg">
                <p>{packet.position_paper.preamble}</p>
                <p>{packet.position_paper.argument}</p>
                <p>{packet.position_paper.conclusion}</p>
              </div>
              {packet.position_paper.footnotes?.length > 0 && (
                <div className="mt-8 border-t border-ink-300 pt-4">
                  <div className="font-mono text-[10px] uppercase tracking-widest2 text-ink-400 mb-2">Footnotes</div>
                  <ul className="space-y-1 text-xs font-mono text-ink-500 max-w-prose">
                    {packet.position_paper.footnotes.map((f, i) => (
                      <li key={i} data-testid={`advocacy-footnote-${i}`}>[{i + 1}] {f}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Opening Speech */}
          {packet.opening_speech && (
            <div className="border border-white/10 bg-ink-800 p-8 mb-8" data-testid="advocacy-opening-speech">
              <MonoLabel>Opening speech</MonoLabel>
              <div className="font-serif text-2xl text-paper-100 leading-snug mb-6">"{packet.opening_speech.hook}"</div>
              <ol className="space-y-4 max-w-prose">
                {(packet.opening_speech.beats || []).map((b, i) => (
                  <li key={i} className="border-l-2 border-verdict-gold pl-4">
                    <div className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400 mb-1">Beat {i + 1} · {b.heading}</div>
                    <div className="text-paper-200 leading-relaxed">{b.body}</div>
                  </li>
                ))}
              </ol>
              <div className="mt-6 font-serif text-xl text-paper-100 italic">— {packet.opening_speech.close}</div>
            </div>
          )}

          {/* Rebuttal cards */}
          {packet.rebuttal_cards?.length > 0 && (
            <div className="mb-8" data-testid="advocacy-rebuttal-cards">
              <MonoLabel>Rebuttal cards · {packet.rebuttal_cards.length}</MonoLabel>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-white/10 border border-white/10">
                {packet.rebuttal_cards.map((c, i) => (
                  <div key={i} className="bg-ink-900 p-5">
                    <div className="font-mono text-[10px] uppercase tracking-widest2 text-verdict-amber mb-2">Counter {i + 1}</div>
                    <div className="text-sm text-paper-300 italic mb-3">"{c.claim_to_rebut}"</div>
                    <div className="text-paper-100 leading-relaxed text-sm mb-3">{c.rebuttal}</div>
                    {c.anchor_citations?.length > 0 && (
                      <div className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400 border-t border-white/10 pt-2">
                        Anchor: {c.anchor_citations.join(" · ")}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Leverage cards */}
          {packet.leverage_cards?.length > 0 && (
            <div className="mb-8" data-testid="advocacy-leverage-cards">
              <MonoLabel>Leverage cards · {packet.leverage_cards.length}</MonoLabel>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10">
                {packet.leverage_cards.map((c, i) => (
                  <div key={i} className="bg-ink-900 p-5 border-l-4 border-verdict-red">
                    <div className="flex items-center justify-between mb-2">
                      <div className="font-mono text-[10px] uppercase tracking-widest2 text-verdict-red">Leverage {i + 1}</div>
                      <Badge tone={c.severity === "high" ? "red" : c.severity === "medium" ? "amber" : "gray"}>
                        {c.severity || "medium"}
                      </Badge>
                    </div>
                    <div className="font-serif text-lg text-paper-100 leading-snug mb-3">{c.headline}</div>
                    <div className="text-sm text-paper-200 mb-2"><span className="text-verdict-gold font-mono text-[10px] uppercase tracking-widest2 mr-2">Rule</span>{c.rule}</div>
                    <div className="text-sm text-paper-300 mb-2"><span className="text-verdict-red font-mono text-[10px] uppercase tracking-widest2 mr-2">Violation</span>{c.violation}</div>
                    {c.anchor_citation && (
                      <div className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400 border-t border-white/10 pt-2 mt-3">
                        Anchor: {c.anchor_citation}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Sources rail */}
          <SourceRail title="Domestic sources" items={data.domestic_sources} />
          <SourceRail title="International sources" items={data.international_sources} />
          <SourceRail title="Opposing-side authority" items={data.opposite_sources} muted />

          <div className="mt-6 text-[10px] font-mono uppercase tracking-widest2 text-paper-400">
            Generated with {data.used_model || "—"}
          </div>
        </div>
      )}
    </div>
  );
}

function Selector({ label, value, options, onChange, testId }) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 font-sans appearance-none pr-10 focus:border-verdict-gold"
        data-testid={testId}
      >
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <ChevronDown className="absolute right-3 top-3.5 w-4 h-4 text-paper-400 pointer-events-none" />
      <div className="absolute -top-2 left-3 px-1 bg-ink-900 text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{label}</div>
    </div>
  );
}

function SourceRail({ title, items, muted }) {
  if (!items?.length) return null;
  return (
    <div className="mb-6" data-testid={`source-rail-${title.replace(/\s/g, "-").toLowerCase()}`}>
      <MonoLabel>{title} · {items.length}</MonoLabel>
      <div className={`grid grid-cols-1 md:grid-cols-2 gap-px bg-white/10 border border-white/10 ${muted ? "opacity-70" : ""}`}>
        {items.slice(0, 6).map((s, i) => (
          <div key={i} className="bg-ink-900 p-3 text-xs">
            <div className="font-mono text-paper-300 truncate">{s.source_name}</div>
            <div className="font-mono text-paper-400">{s.marker} · {s.jurisdiction || "—"} · p.{s.page || "?"}</div>
            <div className="text-paper-400 mt-1 line-clamp-2">{s.excerpt}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
