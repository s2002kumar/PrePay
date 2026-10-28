import { useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "../api";
import { DataTable, StatTile } from "../components/Figures";
import { LineChart, type Series } from "../components/LineChart";
import { StackedColumns } from "../components/StackedColumns";
import { pct, ratePct, signed, signedUsd, usd, years } from "../format";
import { replaceParams, scenarioFromCode, scenarioLabel } from "../routing";
import type { MonthlyRow, PoolSummary, ProjectionResponse, ScenarioOut } from "../types";

const PRESETS = ["flat", "p-200", "p-100", "p100", "p200"];
const HORIZONS = [12, 24, 60, 120, 240, 360];

interface Props {
  pools: PoolSummary[];
  asOfRate: number;
  params: URLSearchParams;
}

function ScenarioPicker({ id, label, code, onChange, allowNone }: {
  id: string;
  label: string;
  code: string;
  onChange: (code: string) => void;
  allowNone: boolean;
}) {
  const isRamp = code.startsWith("ramp:");
  const [, target = "5.00", length = "12"] = isRamp ? code.split(":") : [];
  return (
    <>
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <select
          id={id}
          value={isRamp ? "ramp" : code}
          onChange={(e) => onChange(e.target.value === "ramp" ? "ramp:5.00:12" : e.target.value)}
        >
          {PRESETS.map((p) => (
            <option key={p} value={p}>
              {scenarioLabel(p)}
            </option>
          ))}
          <option value="ramp">Custom: ramp to a rate</option>
          {allowNone && <option value="none">No comparison</option>}
        </select>
      </div>
      {isRamp && (
        <>
          <div className="field">
            <label htmlFor={`${id}-target`}>{label}: target 30y rate (%)</label>
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
            <label htmlFor={`${id}-months`}>{label}: over (months)</label>
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
        </>
      )}
    </>
  );
}

function annual(rows: MonthlyRow[]): { labels: string[]; values: number[][] } {
  if (rows.length <= 36) {
    return {
      labels: rows.map((r) => r.month),
      values: rows.map((r) => [r.scheduled_principal_usd, r.voluntary_prepay_principal_usd, r.recoveries_received_usd]),
    };
  }
  const byYear = new Map<string, number[]>();
  for (const r of rows) {
    const year = r.month.slice(0, 4);
    const sums = byYear.get(year) ?? [0, 0, 0];
    sums[0] = (sums[0] ?? 0) + r.scheduled_principal_usd;
    sums[1] = (sums[1] ?? 0) + r.voluntary_prepay_principal_usd;
    sums[2] = (sums[2] ?? 0) + r.recoveries_received_usd;
    byYear.set(year, sums);
  }
  return { labels: [...byYear.keys()], values: [...byYear.values()] };
}

export function ScenarioLab({ pools, asOfRate, params }: Props) {
  const [poolId, setPoolId] = useState(params.get("pool") ?? "fictional-2023-high-coupon");
  const [codeA, setCodeA] = useState(params.get("a") ?? "flat");
  const [codeB, setCodeB] = useState(params.get("b") ?? "p-100");
  const [horizon, setHorizon] = useState(Number(params.get("h") ?? 120));
  const [severity, setSeverity] = useState(Number(params.get("sev") ?? 0.35));
  const [lag, setLag] = useState(Number(params.get("lag") ?? 12));
  const [result, setResult] = useState<ProjectionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [composition, setComposition] = useState<"a" | "b">("a");
  const [copied, setCopied] = useState(false);
  const pending = useRef<AbortController | null>(null);

  const request = useMemo(() => ({
    pool_id: poolId,
    scenario: scenarioFromCode(codeA, asOfRate) ?? { kind: "flat" as const },
    compare_to: scenarioFromCode(codeB, asOfRate),
    horizon_months: horizon,
    credit: { severity, recovery_lag_months: lag },
  }), [poolId, codeA, codeB, horizon, severity, lag, asOfRate]);

  useEffect(() => {
    const next = new URLSearchParams({
      pool: poolId, a: codeA, b: codeB, h: String(horizon), sev: String(severity), lag: String(lag),
    });
    replaceParams(next);
    const timer = window.setTimeout(() => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      setLoading(true);
      api.project(request, controller.signal)
        .then((response) => {
          setResult(response);
          setError(null);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(reason instanceof ApiRequestError ? reason.message : "The projection service is unavailable.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [request, poolId, codeA, codeB, horizon, severity, lag]);

  const pool = pools.find((p) => p.pool_id === poolId);
  const a = result?.a;
  const b = result?.b ?? null;
  const months = a?.monthly.map((r) => r.month) ?? [];
  const seriesOf = (pick: (r: MonthlyRow) => number | null): Series[] => {
    const out: Series[] = [];
    if (a) out.push({ id: "a", label: `A: ${a.label}`, color: "var(--series-1)", values: a.monthly.map(pick) });
    if (b) out.push({ id: "b", label: `B: ${b.label}`, color: "var(--series-2)", values: b.monthly.map(pick) });
    return out;
  };
  const shown: ScenarioOut | null = composition === "b" && b ? b : (a ?? null);
  const stacked = shown ? annual(shown.monthly) : null;
  const deltas = result?.a_minus_b;

  async function share() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section aria-labelledby="lab-title">
      <h1 id="lab-title">Scenario Lab</h1>
      <p className="lede">
        Compare how a fictional pool returns principal under two hypothetical 30-year mortgage-rate paths. Rates change
        refinancing incentives, and with them modeled payoffs. Loan coupons never change.
      </p>
      <div className="controls" role="group" aria-label="Scenario inputs">
        <div className="field">
          <label htmlFor="pool">Fictional pool</label>
          <select id="pool" value={poolId} onChange={(e) => setPoolId(e.target.value)}>
            {pools.map((p) => (
              <option key={p.pool_id} value={p.pool_id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <ScenarioPicker id="scenario-a" label="Scenario A" code={codeA} onChange={setCodeA} allowNone={false} />
        <ScenarioPicker id="scenario-b" label="Scenario B" code={codeB} onChange={setCodeB} allowNone />
        <div className="field">
          <label htmlFor="horizon">Horizon</label>
          <select id="horizon" value={horizon} onChange={(e) => setHorizon(Number(e.target.value))}>
            {HORIZONS.map((h) => (
              <option key={h} value={h}>
                {h} months
              </option>
            ))}
          </select>
        </div>
        <button type="button" onClick={share} aria-live="polite">
          {copied ? "Link copied" : "Copy share link"}
        </button>
      </div>
      <p className="muted" style={{ marginTop: -8 }}>
        As of {pool?.as_of ?? "…"} · last observed (synthetic) 30-year rate {ratePct(asOfRate)} · model{" "}
        {result?.model ?? "…"} (synthetic-trained)
      </p>

      {error && (
        <div className="warning" role="alert">
          {error}
        </div>
      )}
      {result && result.warnings.length > 0 && (
        <div className="warning" role="status">
          <strong>Read with care</strong>
          <ul>
            {result.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {!result && !error && <p aria-busy="true">Projecting the pool…</p>}

      {a && (
        <div className={loading ? "is-loading" : undefined} aria-busy={loading}>
          <div className="tiles">
            <StatTile
              label="Cash weighted-average life"
              value={years(a.summary.cash_wal_years)}
              detail={b ? `B ${years(b.summary.cash_wal_years)} · A−B ${signed(deltas?.cash_wal_months, "mo")}` : "full-life, principal cash"}
            />
            <StatTile
              label="Principal returned in 12 months"
              value={pct(a.summary.principal_returned_fraction_12m)}
              detail={b ? `B ${pct(b.summary.principal_returned_fraction_12m)} · A−B ${signed(deltas?.principal_returned_12m_pp, "pp")}` : "of as-of balance"}
            />
            <StatTile
              label="Principal returned in 24 months"
              value={pct(a.summary.principal_returned_fraction_24m)}
              detail={b ? `B ${pct(b.summary.principal_returned_fraction_24m)} · A−B ${signed(deltas?.principal_returned_24m_pp, "pp")}` : "of as-of balance"}
            />
            <StatTile
              label={`Interest accrued, ${horizon} mo`}
              value={usd(a.summary.contractual_interest_accrued_horizon_usd)}
              detail={b ? `B ${usd(b.summary.contractual_interest_accrued_horizon_usd)} · A−B ${signedUsd(deltas?.contractual_interest_accrued_horizon_usd)}` : "contractual, undiscounted"}
            />
            <StatTile
              label={`Remaining balance at ${horizon} mo`}
              value={usd(a.summary.ending_upb_horizon_usd)}
              detail={b ? `B ${usd(b.summary.ending_upb_horizon_usd)}` : `of ${usd(pool?.current_upb_usd)} today`}
            />
          </div>

          <div className="grid-2">
            <div className="card">
              <header>
                <div>
                  <h2>30-year mortgage rate path</h2>
                  <p className="sub">month-end, percent per year (hypothetical)</p>
                </div>
              </header>
              <LineChart
                title="30-year mortgage rate path by scenario"
                summary={`Scenario rate paths over ${months.length} months.`}
                xLabels={months}
                series={seriesOf((r) => r.market_rate_30y_pct)}
                yFormat={(v) => `${v.toFixed(1)}%`}
              />
            </div>
            <div className="card">
              <header>
                <div>
                  <h2>Modeled payoff speed (CPR)</h2>
                  <p className="sub">full voluntary payoffs only, % of balance per year</p>
                </div>
              </header>
              <LineChart
                title="Model CPR by scenario"
                summary="Annualized full-payoff rate implied by the model each month."
                xLabels={months}
                series={seriesOf((r) => (r.cpr_model === null ? null : r.cpr_model * 100))}
                yFormat={(v) => `${v.toFixed(0)}%`}
                includeZero
              />
            </div>
            <div className="card">
              <header>
                <div>
                  <h2>Cumulative principal returned</h2>
                  <p className="sub">scheduled + payoffs + recoveries, % of as-of balance</p>
                </div>
              </header>
              <LineChart
                title="Cumulative principal returned by scenario"
                summary="Share of the as-of balance returned as principal cash."
                xLabels={months}
                series={seriesOf((r) => r.cumulative_principal_returned_fraction * 100)}
                yFormat={(v) => `${v.toFixed(0)}%`}
                includeZero
              />
            </div>
            <div className="card">
              <header>
                <div>
                  <h2>Modeled remaining balance</h2>
                  <p className="sub">expected unpaid principal, USD</p>
                </div>
              </header>
              <LineChart
                title="Modeled remaining balance by scenario"
                summary="Expected remaining principal at each month end."
                xLabels={months}
                series={seriesOf((r) => r.ending_upb_usd)}
                yFormat={(v) => usd(v)}
                includeZero
              />
            </div>
          </div>

          {stacked && shown && (
            <div className="card" style={{ marginTop: 16 }}>
              <header>
                <div>
                  <h2>Where principal cash comes from</h2>
                  <p className="sub">
                    {shown.label} · USD per {stacked.labels.length === shown.monthly.length ? "month" : "calendar year"}; credit
                    exits are not cash until recovered
                  </p>
                </div>
                {b && (
                  <div className="segmented" role="group" aria-label="Scenario shown">
                    <button type="button" aria-pressed={composition === "a"} onClick={() => setComposition("a")}>
                      A
                    </button>
                    <button type="button" aria-pressed={composition === "b"} onClick={() => setComposition("b")}>
                      B
                    </button>
                  </div>
                )}
              </header>
              <StackedColumns
                title={`Principal cash composition for ${shown.label}`}
                summary="Scheduled principal, voluntary payoffs and illustrative recoveries per period."
                categories={stacked.labels}
                parts={[
                  { id: "scheduled", label: "Scheduled principal", color: "var(--series-1)" },
                  { id: "prepay", label: "Voluntary payoffs", color: "var(--series-2)" },
                  { id: "recoveries", label: "Recoveries (illustrative)", color: "var(--series-3)" },
                ]}
                values={stacked.values}
                format={(v) => usd(v)}
              />
            </div>
          )}

          <details className="drawer card" style={{ marginTop: 16 }}>
            <summary>Assumptions and table view</summary>
            <div className="controls" style={{ marginTop: 12 }} role="group" aria-label="Credit assumptions">
              <div className="field">
                <label htmlFor="severity">Credit severity (share of disposed principal lost)</label>
                <input id="severity" type="number" min={0} max={1} step={0.05} value={severity}
                  onChange={(e) => setSeverity(Math.min(1, Math.max(0, Number(e.target.value))))} />
              </div>
              <div className="field">
                <label htmlFor="lag">Recovery lag (months)</label>
                <input id="lag" type="number" min={0} max={36} step={1} value={lag}
                  onChange={(e) => setLag(Math.min(36, Math.max(0, Math.round(Number(e.target.value)))))} />
              </div>
            </div>
            <dl className="defs">
              {Object.entries(result.assumptions).map(([k, v]) => (
                <div key={k} style={{ display: "contents" }}>
                  <dt>{k.replaceAll("_", " ")}</dt>
                  <dd>{String(v)}</dd>
                </div>
              ))}
            </dl>
            <DataTable
              caption={`Monthly ledger, scenario A (${a.label}), USD`}
              rows={a.monthly}
              rowKey={(r) => r.month}
              columns={[
                { header: "Month", cell: (r) => r.month },
                { header: "30y rate", cell: (r) => ratePct(r.market_rate_30y_pct) },
                { header: "Begin UPB", cell: (r) => usd(r.beginning_upb_usd) },
                { header: "Scheduled", cell: (r) => usd(r.scheduled_principal_usd) },
                { header: "Payoffs", cell: (r) => usd(r.voluntary_prepay_principal_usd) },
                { header: "Credit exits", cell: (r) => usd(r.credit_exit_principal_usd) },
                { header: "Recoveries", cell: (r) => usd(r.recoveries_received_usd) },
                { header: "Interest accrued", cell: (r) => usd(r.contractual_interest_accrued_usd) },
                { header: "End UPB", cell: (r) => usd(r.ending_upb_usd) },
                { header: "CPR", cell: (r) => pct(r.cpr_model) },
              ]}
            />
          </details>
        </div>
      )}
    </section>
  );
}
