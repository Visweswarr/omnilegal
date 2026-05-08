import React, { useState } from "react";
import { Users2, Stamp, Gavel, AlertTriangle, BookOpen } from "lucide-react";
import { runCouncil } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel } from "../components/UI";

const MODELS = [
  { id: "anthropic", name: "Claude Sonnet 4.5", company: "Anthropic", accent: "border-l-verdict-gold" },
  { id: "google",    name: "Gemini 2.5 Flash",  company: "Google",    accent: "border-l-verdict-amber" },
  { id: "groq",      name: "Llama 3.3 70B",     company: "Groq",      accent: "border-l-verdict-green" },
];

const EXAMPLES = [
  "Is anticipatory self-defence lawful under the UN Charter?",
  "Does VCLT Article 27 override domestic constitutional supremacy?",
  "When does universal jurisdiction attach for war crimes?",
  "Are autonomous weapons systems legal under IHL?",
  "Does the right to be forgotten survive the First Amendment?",
];

export default function Council() {
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!query.trim()) return;
    setBusy(true); setError(null); setData(null);
    try {
      const res = await runCouncil(query.trim(), 6);
      setData(res);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Council failed");
    } finally { setBusy(false); }
  };

  const answersByProvider = (data?.answers || []).reduce((acc, a) => {
    acc[a.provider] = a;
    return acc;
  }, {});

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="council-page">
      <div className="flex items-center gap-3 mb-2">
        <Users2 className="w-5 h-5 text-paper-100" strokeWidth={1.5} />
        <Badge tone="default">Pillar 05 · Council of Models</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Three frontier LLMs.<br className="hidden md:block" /> One <span className="text-verdict-gold">judgment</span>.
      </h1>
      <p className="mt-4 text-paper-300 max-w-2xl">
        Same question, same retrieved context, three independent answers. A meta-judge synthesises a final verdict
        and openly flags points of agreement and disagreement — so you know exactly when an LLM is bluffing.
      </p>

      <div className="mt-8 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-3">
        <input
          className="bg-ink-800 border border-white/10 px-4 py-3 text-paper-100 placeholder:text-paper-400 font-sans focus:border-verdict-gold"
          placeholder="Ask a hard legal question…"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === "Enter" && submit()}
          data-testid="council-query-input"
        />
        <button
          onClick={submit}
          disabled={busy}
          className="bg-verdict-gold text-ink-900 px-6 py-3 font-medium hover:bg-verdict-amber disabled:opacity-50"
          data-testid="council-debate-btn"
        >
          {busy ? "Convening…" : "Convene the Council"}
        </button>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <span className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mr-2 self-center">Try</span>
        {EXAMPLES.map(ex => (
          <button
            key={ex}
            onClick={() => setQuery(ex)}
            className="text-xs font-mono text-paper-300 border border-white/10 px-2 py-1 hover:border-verdict-gold hover:text-paper-100"
            data-testid={`council-example-${ex.slice(0, 20).replace(/\s/g, "-").toLowerCase()}`}
          >
            {ex.slice(0, 36)}{ex.length > 36 ? "…" : ""}
          </button>
        ))}
      </div>

      {busy && <div className="mt-6"><Spinner label="Three LLMs deliberating in parallel…" /></div>}
      {error && <div className="mt-6"><ErrorBlock error={error} /></div>}

      {data && (
        <div className="mt-10">
          {/* Judge banner */}
          {data.judge?.verdict && (
            <div className="border-2 border-verdict-gold bg-verdict-gold/5 p-6 mb-8" data-testid="council-judge">
              <div className="flex items-center gap-3 mb-3">
                <span className="verdict-stamp inline-flex items-center gap-2 border-2 border-verdict-gold text-verdict-gold px-3 py-1 font-mono text-xs uppercase tracking-widest2">
                  <Gavel className="w-3 h-3" strokeWidth={2} /> Chief Justice Verdict
                </span>
                <Badge tone="gold">confidence · {(data.judge.confidence || 0).toFixed(2)}</Badge>
              </div>
              <div className="font-serif text-xl text-paper-100 leading-relaxed max-w-prose">
                {data.judge.verdict}
              </div>
            </div>
          )}

          {/* 3-column council answers */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-px bg-white/10 border border-white/10 mb-8">
            {MODELS.map(m => {
              const a = answersByProvider[m.id];
              return (
                <div
                  key={m.id}
                  className={`bg-ink-900 p-5 border-l-4 ${m.accent}`}
                  data-testid={`council-answer-${m.id}`}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <div className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400">{m.company}</div>
                      <div className="font-serif text-lg text-paper-100 leading-tight">{m.name}</div>
                    </div>
                    {a && a.elapsed_seconds != null && (
                      <span className="font-mono text-[10px] text-paper-400">{a.elapsed_seconds}s</span>
                    )}
                  </div>
                  {a?.error && !a?.answer && (
                    <div className="border border-verdict-red/30 bg-verdict-red/10 p-2 text-xs text-verdict-red">
                      {a.error}
                    </div>
                  )}
                  {a?.answer && (
                    <div className="text-sm text-paper-200 whitespace-pre-wrap leading-relaxed max-h-[440px] overflow-y-auto pr-1">
                      {a.answer}
                    </div>
                  )}
                  {!a && (
                    <div className="text-paper-400 text-xs">No answer.</div>
                  )}
                </div>
              );
            })}
          </div>

          {/* Agreements / Disagreements */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-white/10 border border-white/10 mb-8">
            <div className="bg-ink-900 p-5" data-testid="council-agreements">
              <MonoLabel>Agreements</MonoLabel>
              {(data.judge?.agreements?.length > 0) ? (
                <ul className="space-y-2">
                  {data.judge.agreements.map((a, i) => (
                    <li key={i} className="text-sm text-paper-200 border-l-2 border-verdict-green pl-3 py-1">{a}</li>
                  ))}
                </ul>
              ) : <div className="text-xs text-paper-400">None recorded.</div>}
            </div>
            <div className="bg-ink-900 p-5" data-testid="council-disagreements">
              <MonoLabel>Disagreements</MonoLabel>
              {(data.judge?.disagreements?.length > 0) ? (
                <ul className="space-y-3">
                  {data.judge.disagreements.map((d, i) => (
                    <li key={i} className="border-l-2 border-verdict-red pl-3">
                      <div className="text-sm text-paper-200 mb-1">{d.point}</div>
                      <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs font-mono text-paper-400">
                        {d.claude && <span><span className="text-verdict-gold">Claude:</span> {d.claude}</span>}
                        {d.gemini && <span><span className="text-verdict-amber">Gemini:</span> {d.gemini}</span>}
                        {d.groq   && <span><span className="text-verdict-green">Groq:</span> {d.groq}</span>}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : <div className="text-xs text-paper-400">No disagreements detected.</div>}
            </div>
          </div>

          {/* Ungrounded warnings */}
          {data.judge?.ungrounded_warnings?.length > 0 && (
            <div className="border border-verdict-amber/40 bg-verdict-amber/10 p-4 mb-8" data-testid="council-ungrounded">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle className="w-4 h-4 text-verdict-amber" />
                <MonoLabel>Ungrounded claims</MonoLabel>
              </div>
              <ul className="space-y-1 text-sm text-paper-200">
                {data.judge.ungrounded_warnings.map((w, i) => (
                  <li key={i} className="font-mono text-xs">{w}</li>
                ))}
              </ul>
            </div>
          )}

          {/* Shared retrieval context */}
          {data.passages?.length > 0 && (
            <div className="border border-white/10" data-testid="council-passages">
              <div className="flex items-center gap-2 px-4 py-3 border-b border-white/10">
                <BookOpen className="w-4 h-4 text-paper-300" strokeWidth={1.5} />
                <MonoLabel>Shared retrieved context · {data.passages.length}</MonoLabel>
              </div>
              <ul className="divide-y divide-white/5">
                {data.passages.map((p, i) => (
                  <li key={i} className="px-4 py-3 text-xs">
                    <div className="font-mono text-paper-100">{p.marker} · {p.source_name}</div>
                    <div className="font-mono text-paper-400">{p.jurisdiction || "—"} · p.{p.page || "?"}</div>
                    <div className="text-paper-300 mt-1 line-clamp-2">{p.excerpt}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
