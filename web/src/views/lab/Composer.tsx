import { useState } from "react";

import { ratePct } from "../../format";
import { scenarioLabel } from "../../routing";
import { STATIC, STATIC_SCENARIOS } from "../../static";
import type { PoolSummary, Verdict } from "../../types";
import { VerdictChip } from "./common";

/** The precomputed grid, in rate-shock order: −300 bp … flat … +300 bp. */
export const GRID = [...STATIC_SCENARIOS].sort((x, y) => shock(x) - shock(y));
export const HORIZONS: [number, string][] = [
  [12, "1 yr"],
  [24, "2 yr"],
  [60, "5 yr"],
  [120, "10 yr"],
  [240, "20 yr"],
  [360, "Full life"],
];

function shock(code: string): number {
  const m = /^p(-?\d+)$/.exec(code);
  return m?.[1] ? Number(m[1]) : 0;
}

/** Labels use a true minus sign. */
export function display(label: string): string {
  return label.replace(/(^|\s)-(\d)/g, "$1−$2");
}

function describe(code: string, asOfRate: number): string {
  if (code === "none") return "Show scenario A on its own";
  if (code === "flat") return `30-year rate held at the last observed ${ratePct(asOfRate)}`;
  const parallel = /^p(-?\d+)$/.exec(code);
  if (parallel?.[1] !== undefined) {
    const bp = Number(parallel[1]);
    return `30-year rate ${(Math.abs(bp) / 100).toFixed(2)} pp ${bp < 0 ? "below" : "above"} the last observed ${ratePct(asOfRate)}, from month 2`;
  }
  const ramp = /^ramp:([\d.]+):(\d+)$/.exec(code);
  if (ramp) return `Straight line from ${ratePct(asOfRate)} to ${Number(ramp[1]).toFixed(2)}% over ${ramp[2]} months, then held`;
  return "";
}

interface ScenarioProps {
  side: "a" | "b";
  code: string;
  onChange: (code: string) => void;
  allowNone: boolean;
  asOfRate: number;
  verdict: Verdict | null;
}

function ScenarioCard({ side, code, onChange, allowNone, asOfRate, verdict }: ScenarioProps) {
  const name = side === "a" ? "Scenario A" : "Scenario B";
  const id = `scenario-${side}`;
  const isRamp = code.startsWith("ramp:");
  const [, target = "5.00", length = "12"] = isRamp ? code.split(":") : [];
  const k = GRID.indexOf(code);
  const step = (d: number) => {
    const next = GRID[k + d];
    if (next) onChange(next);
  };
  return (
    <div className={`scenario-card side-${side}`}>
      <div className="scenario-head">
        <label htmlFor={id}>
          <i className={`swatch ${side}`} aria-hidden="true" />
          {name}
        </label>
        {code !== "none" && <VerdictChip verdict={verdict} />}
      </div>
      <div className="stepper">
        <button
          type="button"
          className="step"
          aria-label={`${name}: lower the rate shock`}
          disabled={k <= 0}
          onClick={() => step(-1)}
        >
          −
        </button>
        <select id={id} value={isRamp ? "ramp" : code} onChange={(e) => onChange(e.target.value === "ramp" ? "ramp:5.00:12" : e.target.value)}>
          {GRID.map((g) => (
            <option key={g} value={g}>
              {display(scenarioLabel(g))}
            </option>
          ))}
          {!STATIC && <option value="ramp">Custom: ramp to a rate</option>}
          {allowNone && <option value="none">No comparison</option>}
        </select>
        <button
          type="button"
          className="step"
          aria-label={`${name}: raise the rate shock`}
          disabled={k < 0 || k >= GRID.length - 1}
          onClick={() => step(1)}
        >
          +
        </button>
      </div>
      <p className="scenario-desc">{describe(code, asOfRate)}</p>
      {isRamp && (
        <div className="ramp">
          <div className="field">
            <label htmlFor={`${id}-target`}>{name}: target 30y rate (%)</label>
            <input
              id={`${id}-target`}
              type="number"
              min={1}
              max={19}
              step={0.25}
              value={Number(target)}
              onChange={(e) => onChange(`ramp:${Number(e.target.value).toFixed(2)}:${length}`)}
            />
          </div>
          <div className="field">
            <label htmlFor={`${id}-months`}>{name}: over (months)</label>
            <input
              id={`${id}-months`}
              type="number"
              min={1}
              max={120}
              step={1}
              value={Number(length)}
              onChange={(e) => onChange(`ramp:${target}:${Math.round(Number(e.target.value)) || 1}`)}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export interface CreditInputs {
  severity: number;
  lag: number;
  cdr: string;
  setSeverity: (v: number) => void;
  setLag: (v: number) => void;
  setCdr: (v: string) => void;
}

export function Composer(props: {
  pools: PoolSummary[];
  poolId: string;
  onPool: (id: string) => void;
  codeA: string;
  codeB: string;
  onA: (code: string) => void;
  onB: (code: string) => void;
  horizon: number;
  onHorizon: (h: number) => void;
  servedMonths: number | null;
  asOfRate: number;
  verdictA: Verdict | null;
  verdictB: Verdict | null;
  credit: CreditInputs;
}) {
  const { pools, poolId, onPool, codeA, codeB, onA, onB, horizon, onHorizon, servedMonths, asOfRate, verdictA, verdictB, credit } = props;
  const [copied, setCopied] = useState(false);
  const swap = () => {
    if (codeB === "none") return;
    onA(codeB);
    onB(codeA);
  };
  async function share() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }
  const full = horizon === 360;
  return (
    <section className="composer panel" aria-label="Scenario inputs">
      <div className="composer-top">
        <div className="field pool-field">
          <label htmlFor="pool">Fictional pool</label>
          <select id="pool" value={poolId} onChange={(e) => onPool(e.target.value)}>
            {pools.map((p) => (
              <option key={p.pool_id} value={p.pool_id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <button type="button" className="ghost" onClick={share} aria-live="polite">
          {copied ? "Link copied" : "Copy share link"}
        </button>
      </div>
      <div className="composer-grid">
        <ScenarioCard side="a" code={codeA} onChange={onA} allowNone={false} asOfRate={asOfRate} verdict={verdictA} />
        <button type="button" className="swap" onClick={swap} disabled={codeB === "none"} aria-label="Swap scenarios A and B">
          <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
            <path d="M3 5h10l-3-3M13 11H3l3 3" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span className="swap-text">Swap</span>
        </button>
        <ScenarioCard side="b" code={codeB} onChange={onB} allowNone asOfRate={asOfRate} verdict={verdictB} />
        <div className="horizon">
          <span className="field-label" id="horizon-label">
            Horizon
          </span>
          <div className="segmented wide" role="group" aria-labelledby="horizon-label">
            {HORIZONS.map(([h, label]) => (
              <button key={h} type="button" aria-pressed={horizon === h} onClick={() => onHorizon(h)} title={`${h} months`}>
                {label}
              </button>
            ))}
          </div>
          <p className="scenario-desc" data-testid="horizon-note">
            {full
              ? servedMonths !== null
                ? `Months 1–${servedMonths}: the pool's last scheduled payment`
                : "To the pool's last scheduled payment"
              : `Months 1–${horizon} for totals and balances; cash WAL is always full life`}
          </p>
        </div>
      </div>
      <details className="assumptions">
        <summary>Credit and rate-path assumptions</summary>
        {STATIC ? (
          <p className="scenario-desc">
            This public site holds precomputed results only: {GRID.length} rate scenarios (flat and parallel shifts of
            −300 to +300 bp) × {HORIZONS.length} horizons for each fictional pool, at the default credit assumptions.
            Custom rate paths and credit inputs need the local app (see the README); nothing is simulated in your browser.
          </p>
        ) : (
          <p className="scenario-desc">The local app projects any custom ramp and credit assumption on request.</p>
        )}
        <fieldset className="plain credit-fields" disabled={STATIC} aria-label="Credit assumptions">
          <div className="field">
            <label htmlFor="severity">Credit severity (share of disposed principal lost)</label>
            <input
              id="severity"
              type="number"
              min={0}
              max={1}
              step={0.05}
              value={credit.severity}
              onChange={(e) => credit.setSeverity(Math.min(1, Math.max(0, Number(e.target.value))))}
            />
          </div>
          <div className="field">
            <label htmlFor="cdr">Credit exits, annual CDR % (blank: default)</label>
            <input
              id="cdr"
              type="number"
              min={0}
              max={20}
              step={0.1}
              value={credit.cdr}
              placeholder="default"
              onChange={(e) => credit.setCdr(e.target.value === "" ? "" : String(Math.min(20, Math.max(0, Number(e.target.value)))))}
            />
          </div>
          <div className="field">
            <label htmlFor="lag">Recovery lag (months)</label>
            <input
              id="lag"
              type="number"
              min={0}
              max={36}
              step={1}
              value={credit.lag}
              onChange={(e) => credit.setLag(Math.min(36, Math.max(0, Math.round(Number(e.target.value)))))}
            />
          </div>
        </fieldset>
      </details>
    </section>
  );
}
