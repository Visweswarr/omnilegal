import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Globe, ShieldCheck, FileText, Radio, Users2, BookOpen, ArrowRight, Stamp, Scale, Layers, Zap } from "lucide-react";
import { fetchOverview } from "../lib/api";
import { Badge, MonoLabel } from "../components/UI";

const PILLARS = [
  {
    to: "/atlas", icon: Globe, eyebrow: "Pillar 01",
    title: "Conflict Atlas",
    blurb: "Type any legal topic. Watch the world map color itself by legality, with primary-source citations on every country.",
    accent: "text-verdict-gold",
  },
  {
    to: "/forensics", icon: ShieldCheck, eyebrow: "Pillar 02",
    title: "Citation Forensics",
    blurb: "Paste any legal text — even from another AI. Every citation is verified, scored, and graded against our grounded corpus.",
    accent: "text-verdict-green",
  },
  {
    to: "/advocacy", icon: FileText, eyebrow: "Pillar 03",
    title: "Advocacy Studio",
    blurb: "Pick a country, topic, position. Get a print-ready position paper, opening speech, rebuttal cards, and leverage cards.",
    accent: "text-paper-200",
  },
  {
    to: "/live", icon: Radio, eyebrow: "Pillar 04",
    title: "Live Authority",
    blurb: "Real-time queries across Indian Kanoon, CourtListener, GovInfo, EUR-Lex, HUDOC, and the UN Treaty index.",
    accent: "text-verdict-amber",
  },
  {
    to: "/council", icon: Users2, eyebrow: "Pillar 05",
    title: "Council of Models",
    blurb: "Claude Sonnet 4.5, Gemini 2.5 Flash, and Llama 3.3 70B answer side-by-side. A meta-judge resolves the disagreement.",
    accent: "text-paper-100",
  },
  {
    to: "/research", icon: BookOpen, eyebrow: "Pillar 06",
    title: "Research Console",
    blurb: "Five personas — Tourist, Researcher, Law Student, Layman, Conflict Detector. Every claim auto-audited.",
    accent: "text-paper-300",
  },
];

function useCountUp(target, duration = 1100) {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!target) return;
    let raf;
    const start = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      setV(Math.floor(target * (1 - Math.pow(1 - t, 3))));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);
  return v;
}

export default function Landing() {
  const [overview, setOverview] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchOverview().then(setOverview).catch(e => setError(e?.message));
  }, []);

  const totalChunks = useCountUp(overview?.total_chunks ?? 0, 1400);
  const collectionCount = useCountUp(overview?.collection_count ?? 0, 1100);
  const liveCount = (overview?.live_sources?.length) ?? 6;
  const councilCount = (overview?.council_models?.length) ?? 3;

  return (
    <div className="relative">
      {/* Hero */}
      <section className="px-6 md:px-12 pt-16 md:pt-24 pb-16 max-w-7xl mx-auto" data-testid="hero">
        <div className="grid grid-cols-12 gap-8 items-end">
          <div className="col-span-12 lg:col-span-8">
            <Badge tone="gold" data-testid="hero-eyebrow">
              <Stamp className="w-3 h-3 mr-0.5" strokeWidth={1.5} /> Verified Legal Intelligence
            </Badge>
            <h1 className="mt-4 font-serif text-[2.6rem] md:text-[4.4rem] leading-[0.98] tracking-tight text-paper-100">
              The verdict.<br />
              The map.<br />
              The proof.
            </h1>
            <p className="mt-6 max-w-2xl text-paper-300 leading-relaxed text-lg font-sans">
              ChatGPT gives you prose. <span className="text-paper-100">OmniLegal</span> gives you a primary-source verdict, a coloured map of every jurisdiction, and a forensic audit of every citation.
              <span className="block mt-3 text-paper-400 text-base">No prompt-engineering. Six single-click expert workflows. Built on a grounded corpus of <span className="text-verdict-gold font-mono">{totalChunks.toLocaleString()}</span> chunks.</span>
            </p>

            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                to="/atlas"
                className="inline-flex items-center gap-2 px-5 py-3 bg-verdict-gold text-ink-900 font-medium hover:bg-verdict-amber transition-colors"
                data-testid="cta-atlas"
              >
                Open the Atlas <ArrowRight className="w-4 h-4" strokeWidth={2} />
              </Link>
              <Link
                to="/forensics"
                className="inline-flex items-center gap-2 px-5 py-3 border border-white/20 text-paper-100 font-medium hover:bg-white/5"
                data-testid="cta-forensics"
              >
                Verify a citation
              </Link>
            </div>
          </div>

          {/* Metrics rail */}
          <div className="col-span-12 lg:col-span-4 grid grid-cols-2 gap-px bg-white/10 border border-white/10">
            <Metric value={totalChunks.toLocaleString()} label="Grounded chunks" />
            <Metric value={collectionCount.toString()} label="Collections" />
            <Metric value={liveCount.toString()}        label="Live registries" />
            <Metric value={councilCount.toString()}     label="Council models" />
          </div>
        </div>
      </section>

      {/* Pillars grid */}
      <section className="px-6 md:px-12 max-w-7xl mx-auto" data-testid="pillars">
        <div className="border-t border-white/10 pt-10">
          <MonoLabel>Six pillars · One thesis</MonoLabel>
          <h2 className="font-sans text-2xl md:text-3xl tracking-tight font-medium text-paper-100 mb-10">
            What no general-purpose chatbot can do.
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-px bg-white/10 border border-white/10">
            {PILLARS.map(p => (
              <Link
                key={p.to}
                to={p.to}
                className="group bg-ink-900 hover:bg-ink-800 transition-colors p-7 flex flex-col gap-3 min-h-[210px]"
                data-testid={`pillar-${p.title.toLowerCase().replace(/\s/g, "-")}`}
              >
                <div className="flex items-center justify-between">
                  <p.icon className={`w-5 h-5 ${p.accent}`} strokeWidth={1.5} />
                  <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{p.eyebrow}</span>
                </div>
                <h3 className="font-serif text-2xl tracking-tight text-paper-100">{p.title}</h3>
                <p className="text-sm text-paper-400 leading-relaxed">{p.blurb}</p>
                <span className="mt-auto inline-flex items-center gap-2 text-xs font-mono uppercase tracking-widest2 text-paper-300 group-hover:text-verdict-gold transition-colors">
                  Open <ArrowRight className="w-3 h-3" strokeWidth={2} />
                </span>
              </Link>
            ))}
          </div>
        </div>
      </section>

      {/* Manifesto strip */}
      <section className="px-6 md:px-12 max-w-7xl mx-auto mt-20" data-testid="manifesto">
        <div className="border border-white/10 p-8 md:p-12 grid grid-cols-1 md:grid-cols-3 gap-8">
          <Trio
            icon={Layers}
            title="Grounded, not guessed."
            body="Every answer is built on retrieved primary sources from 22 collections — Indian, US, UK, Russian, Israeli, EU, and international authorities."
          />
          <Trio
            icon={Scale}
            title="Auditable, not asserted."
            body="Every citation is verifiable with one click. Every claim is graded — verified, partial, suspicious, or hallucinated. No black boxes."
          />
          <Trio
            icon={Zap}
            title="Definitive, not chatty."
            body="No prompt-engineering. Single-click workflows produce a finished verdict, position paper, audit report, or comparative map — print-ready."
          />
        </div>
      </section>

      {/* Live ticker of registries */}
      <section className="mt-16 border-y border-white/10 bg-ink-800/40 overflow-hidden" data-testid="live-ticker">
        <div className="flex items-center text-[10px] font-mono uppercase tracking-widest2 text-paper-400 px-6 md:px-12 py-2 border-b border-white/5">
          <span className="text-verdict-gold mr-3">●</span> Live primary-source registries
        </div>
        <div className="overflow-hidden whitespace-nowrap py-3">
          <div className="ticker-track gap-12 px-12">
            {[...REGISTRIES, ...REGISTRIES].map((r, i) => (
              <span key={i} className="font-mono text-xs text-paper-300 mx-6">
                <span className="text-verdict-gold mr-2">·</span> {r}
              </span>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

const REGISTRIES = [
  "Indian Kanoon",
  "CourtListener",
  "GovInfo",
  "EUR-Lex",
  "HUDOC (ECHR)",
  "UN Treaty Index",
  "ICRC IHL Database",
  "ILO NATLEX",
  "FAOLEX",
  "WIPO Lex",
];

function Metric({ value, label }) {
  return (
    <div className="bg-ink-900 p-6">
      <div className="font-mono text-3xl md:text-4xl text-paper-100 tracking-tight">{value}</div>
      <div className="mt-2 text-[10px] font-mono uppercase tracking-widest2 text-paper-400">{label}</div>
    </div>
  );
}

function Trio({ icon: Icon, title, body }) {
  return (
    <div>
      <Icon className="w-5 h-5 text-verdict-gold mb-3" strokeWidth={1.5} />
      <div className="font-serif text-xl text-paper-100 mb-2">{title}</div>
      <div className="text-sm text-paper-400 leading-relaxed">{body}</div>
    </div>
  );
}
