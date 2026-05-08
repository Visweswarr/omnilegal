import React from "react";

export function Spinner({ label = "Computing verdict…" }) {
  return (
    <div className="flex items-center gap-3 font-mono text-xs uppercase tracking-widest2 text-paper-400" data-testid="spinner">
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inset-0 rounded-none bg-verdict-gold animate-ping opacity-60"></span>
        <span className="relative h-2.5 w-2.5 bg-verdict-gold"></span>
      </span>
      {label}
    </div>
  );
}

export function ErrorBlock({ error }) {
  if (!error) return null;
  return (
    <div className="border border-verdict-red bg-verdict-red/10 px-4 py-3 font-mono text-xs text-verdict-red" data-testid="error-block">
      {String(error?.message || error || "Unknown error")}
    </div>
  );
}

export function Badge({ children, tone = "default", className = "", ...rest }) {
  const tones = {
    default:    "border-white/15 text-paper-300 bg-white/5",
    gold:       "border-verdict-gold/60 text-verdict-gold bg-verdict-gold/10",
    red:        "border-verdict-red/60 text-verdict-red bg-verdict-red/10",
    green:      "border-verdict-green/60 text-verdict-green bg-verdict-green/10",
    amber:      "border-verdict-amber/60 text-verdict-amber bg-verdict-amber/10",
    gray:       "border-white/10 text-paper-400 bg-white/0",
  };
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-[10px] font-mono uppercase tracking-widest2 border ${tones[tone] || tones.default} ${className}`}
      {...rest}
    >
      {children}
    </span>
  );
}

export function MonoLabel({ children }) {
  return (
    <div className="text-[10px] font-mono uppercase tracking-widest2 text-paper-400 mb-2">
      {children}
    </div>
  );
}

export function Section({ title, children, eyebrow, action }) {
  return (
    <section className="mb-12">
      <div className="flex items-end justify-between gap-3 mb-5">
        <div>
          {eyebrow && <MonoLabel>{eyebrow}</MonoLabel>}
          <h2 className="font-sans text-2xl md:text-3xl tracking-tight text-paper-100 font-medium">{title}</h2>
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
