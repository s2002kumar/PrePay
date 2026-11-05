import { type ReactNode, useEffect, useId, useRef, useState } from "react";

import { definition, VERDICT_TEXT } from "../../derive";
import type { Methodology, Verdict } from "../../types";

/** Status icon + label: a verdict is never carried by color alone. */
export function VerdictChip({ verdict, prefix }: { verdict: Verdict | null; prefix?: string }) {
  if (!verdict) return null;
  const tone = verdict === "supported" ? "good" : verdict === "extrapolating" ? "warn" : "crit";
  return (
    <span className={`chip ${tone}`} data-verdict={verdict}>
      <StatusIcon tone={tone} />
      {prefix && <span className="chip-prefix">{prefix}</span>}
      {VERDICT_TEXT[verdict]}
    </span>
  );
}

export function StatusIcon({ tone }: { tone: "good" | "warn" | "crit" }) {
  return (
    <svg className="status-icon" width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      {tone === "good" && (
        <>
          <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M5 8.2l2 2 4-4.4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </>
      )}
      {tone === "warn" && (
        <>
          <path d="M8 1.8l6.6 11.6H1.4z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M8 6v3.6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="8" cy="11.6" r="0.9" fill="currentColor" />
        </>
      )}
      {tone === "crit" && (
        <>
          <path d="M5.2 1.5h5.6l3.7 3.7v5.6l-3.7 3.7H5.2l-3.7-3.7V5.2z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </>
      )}
    </svg>
  );
}

/** What window a number covers: full life, a fixed window, or the selected horizon. */
export function Basis({ children }: { children: ReactNode }) {
  return <span className="basis">{children}</span>;
}

/**
 * A metric name that opens its served definition (label, unit, formula from /api/methodology).
 * `extra` adds a plain-language reading written for this view.
 */
export function Term({ method, metric, children, extra }: {
  method: Methodology | null;
  metric: string;
  children: ReactNode;
  extra?: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const box = useRef<HTMLSpanElement>(null);
  const def = definition(method, metric);
  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (box.current && !box.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  return (
    <span className="term" ref={box}>
      {children}
      <button
        type="button"
        className="info"
        aria-expanded={open}
        aria-controls={id}
        aria-label={`Definition: ${def?.label ?? metric}`}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setOpen(false);
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 7.2v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="8" cy="4.9" r="0.9" fill="currentColor" />
        </svg>
      </button>
      {open && (
        <span className="popover" id={id} role="note">
          {def ? (
            <>
              <strong>{def.label}</strong> <span className="muted">· {def.unit}</span>
              <code className="formula">{def.formula}</code>
            </>
          ) : (
            <span className="muted">Definition unavailable.</span>
          )}
          {extra && <span className="plain">{extra}</span>}
        </span>
      )}
    </span>
  );
}

/** "B − A" difference cell: the sign carries the meaning; the unit is always printed. */
export function Delta({ value, format }: { value: number | null; format: (v: number) => string }) {
  if (value === null || !Number.isFinite(value)) return <span className="muted">n/a</span>;
  return <span className="delta">{format(value)}</span>;
}
