import React, { useEffect, useRef, useState } from "react";
import { Mic, MicOff, Save, FileSearch } from "lucide-react";
import { voiceVerifyChunk, voiceFinalize, saveReport } from "../lib/api";
import { Spinner, ErrorBlock, Badge, MonoLabel, Section } from "../components/UI";

const STATUS_COLOR = {
  verified:     "border-verdict-green/60 bg-verdict-green/10 text-verdict-green",
  partial:      "border-verdict-amber/60 bg-verdict-amber/10 text-verdict-amber",
  suspicious:   "border-verdict-red/60 bg-verdict-red/10 text-verdict-red",
  hallucinated: "border-verdict-red/60 bg-verdict-red/10 text-verdict-red",
  not_found:    "border-verdict-red/60 bg-verdict-red/10 text-verdict-red",
  no_citations: "border-white/10 text-paper-400",
};

export default function Voice() {
  const [supported, setSupported] = useState(true);
  const [recording, setRecording] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [chunks, setChunks] = useState([]);
  const [final, setFinal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [savedId, setSavedId] = useState(null);

  const recRef = useRef(null);
  const lastFlushRef = useRef("");

  useEffect(() => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setSupported(false); return; }
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = "en-US";
    rec.onresult = (event) => {
      let interimText = "";
      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const res = event.results[i];
        if (res.isFinal) finalText += res[0].transcript + " ";
        else interimText += res[0].transcript;
      }
      setInterim(interimText);
      if (finalText.trim()) {
        setTranscript(prev => prev + finalText);
        lastFlushRef.current += finalText;
        // Flush on sentence boundaries
        if (/[.!?]\s*$/.test(lastFlushRef.current)) {
          const toVerify = lastFlushRef.current.trim();
          lastFlushRef.current = "";
          verifyChunk(toVerify);
        }
      }
    };
    rec.onerror = (e) => setError("Speech: " + (e?.error || "unknown"));
    rec.onend = () => { if (recRef.current?.shouldRestart) rec.start(); };
    recRef.current = rec;
    return () => { try { rec.stop(); } catch {} };
  }, []);

  const verifyChunk = async (text) => {
    try {
      const result = await voiceVerifyChunk(text);
      setChunks(prev => [...prev, result]);
    } catch (e) {
      setError(e?.response?.data?.detail || "Chunk verify failed.");
    }
  };

  const start = () => {
    if (!recRef.current) return;
    setError(null); setFinal(null);
    recRef.current.shouldRestart = true;
    try { recRef.current.start(); setRecording(true); }
    catch (e) { setError("Could not start microphone: " + e.message); }
  };

  const stop = async () => {
    if (!recRef.current) return;
    recRef.current.shouldRestart = false;
    try { recRef.current.stop(); } catch {}
    setRecording(false);
    if (lastFlushRef.current.trim()) {
      verifyChunk(lastFlushRef.current.trim());
      lastFlushRef.current = "";
    }
    if (transcript.trim()) {
      setBusy(true);
      try {
        setFinal(await voiceFinalize(transcript));
      } catch (e) {
        setError(e?.response?.data?.detail || "Final report failed.");
      } finally { setBusy(false); }
    }
  };

  const onSave = async () => {
    if (!final) return;
    try {
      const r = await saveReport("forensics", `Voice — ${new Date().toLocaleString()}`,
        { transcript, chunks, final });
      setSavedId(r.id);
    } catch (e) { setError(e?.response?.data?.detail || "Save failed."); }
  };

  return (
    <div className="px-6 md:px-12 py-12 max-w-7xl mx-auto" data-testid="voice-page">
      <div className="flex items-center gap-3 mb-2">
        <Mic className="w-5 h-5 text-verdict-red" strokeWidth={1.5} />
        <Badge tone="red">Pillar 10 · Voice Coach</Badge>
      </div>
      <h1 className="font-serif text-4xl md:text-5xl tracking-tight text-paper-100 leading-tight">
        Speak your speech.<br className="hidden md:block" /> Get a live <span className="text-verdict-red">fact-check</span>.
      </h1>
      <p className="text-paper-400 mt-4 max-w-2xl">
        We use your browser's speech engine to transcribe live, then stream each
        sentence through Citation Forensics. After you stop, you get a full forensics report.
      </p>

      {!supported && (
        <div className="mt-6 border border-verdict-amber/60 bg-verdict-amber/10 p-4 text-sm text-verdict-amber font-mono">
          Your browser doesn't expose a SpeechRecognition API. Voice Coach requires Chrome or Edge.
        </div>
      )}

      <div className="mt-8 flex items-center gap-4">
        {!recording ? (
          <button
            onClick={start} disabled={!supported}
            data-testid="voice-start"
            className="px-6 py-3 bg-verdict-red text-paper-100 font-mono text-xs uppercase tracking-widest2 inline-flex items-center gap-2 disabled:opacity-40"
          >
            <Mic className="w-4 h-4" /> Start recording
          </button>
        ) : (
          <button
            onClick={stop}
            data-testid="voice-stop"
            className="px-6 py-3 bg-paper-100 text-ink-900 font-mono text-xs uppercase tracking-widest2 inline-flex items-center gap-2"
          >
            <MicOff className="w-4 h-4" /> Stop
          </button>
        )}
        {recording && <Spinner label="Listening…" />}
      </div>

      <ErrorBlock error={error} />

      <div className="mt-8 grid md:grid-cols-2 gap-4">
        <div className="border border-white/10 bg-ink-800/40 p-4 min-h-[300px]">
          <MonoLabel>Live transcript</MonoLabel>
          <p className="font-serif text-lg leading-relaxed text-paper-100 whitespace-pre-wrap">
            {transcript}
            <span className="text-paper-400 italic">{interim}</span>
          </p>
        </div>

        <div className="border border-white/10 bg-ink-800/40 p-4 min-h-[300px]">
          <MonoLabel>Chunk verifications</MonoLabel>
          {chunks.length === 0 && <p className="text-paper-400 text-sm">Sentences will appear here as you speak.</p>}
          <div className="space-y-2">
            {chunks.map((c, i) => (
              <div key={i} className={`border p-2 text-sm ${STATUS_COLOR[c.verdict] || "border-white/10 text-paper-300"}`}>
                <div className="font-serif">{c.text}</div>
                <div className="mt-1 flex items-center gap-2 text-[10px] font-mono uppercase tracking-widest2">
                  <span>{c.verdict || "—"}</span>
                  <span>· trust {Math.round((c.trust_score || 0) * 100)}%</span>
                  <span>· {c.claims?.length || 0} claims</span>
                </div>
                {c.claims && c.claims.length > 0 && (
                  <ul className="mt-2 space-y-1 text-[11px] font-mono text-paper-300">
                    {c.claims.map((cl, j) => (
                      <li key={j} className="border-l border-white/10 pl-2">
                        <span className="text-verdict-gold">{cl.citation}</span>{" "}
                        <span>· {cl.status}</span>{" "}
                        <span>· {Math.round((cl.confidence || 0) * 100)}%</span>
                        {cl.source && <div className="text-paper-400">{cl.source}</div>}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {busy && <div className="mt-6"><Spinner label="Compiling final forensics…" /></div>}

      {final && !final.error && (
        <Section title="Final forensics report" eyebrow={final.overall_grade || "Summary"} action={
          <button onClick={onSave}
            data-testid="voice-save"
            className="px-3 py-2 border border-white/10 hover:border-verdict-gold/60 font-mono text-[10px] uppercase tracking-widest2 text-paper-300 inline-flex items-center gap-2">
            <Save className="w-3 h-3" /> {savedId ? `Saved ✓ ${savedId.slice(0,8)}` : "Save"}
          </button>
        }>
          <div className="border border-white/10 bg-ink-800/40 p-5">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-mono text-[10px] uppercase tracking-widest2 text-paper-400">Trust score</span>
              <span className="font-mono text-3xl text-verdict-gold">{Math.round((final.overall_score || 0) * 100)}%</span>
              <Badge tone={final.overall_grade === "high_trust" ? "green" : final.overall_grade === "medium_trust" ? "amber" : "red"}>
                {final.overall_grade}
              </Badge>
            </div>
            <div className="mt-4 grid grid-cols-3 md:grid-cols-6 gap-2 text-xs font-mono">
              {Object.entries(final.summary || {}).map(([k, v]) => (
                <div key={k} className="border border-white/10 p-2 text-center">
                  <div className="text-paper-400 uppercase tracking-widest2 text-[9px]">{k.replace(/_/g, " ")}</div>
                  <div className="text-paper-100 text-lg">{v}</div>
                </div>
              ))}
            </div>
          </div>
        </Section>
      )}
      {final?.error && <ErrorBlock error={final.error} />}
    </div>
  );
}
