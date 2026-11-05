import { useState } from "react";

import { type Bracket, TimeChart, type TimeSeries } from "../../components/TimeChart";
import { cumulativeFraction, cumulativeUsd, definition, hasRange, rowResidual, type SideView } from "../../derive";
import { pct, ratePct, signed, signedPp, signedUsd, usd, usdCents, usdFull } from "../../format";
import type { Methodology, MonthlyRow } from "../../types";
import { Term } from "./common";
import { display } from "./Composer";

export interface Cursor {
  month: number;
  set: (month: number) => void;
  label: (month: number) => string;
}

/** Cumulative principal returned, A against B, with the gap shaded and model-family brackets. */
export function PrincipalChart({ A, B, cursor, method }: { A: SideView; B: SideView | null; cursor: Cursor; method: Methodology | null }) {
  const [unit, setUnit] = useState<"pct" | "usd">("pct");
  const usdMode = unit === "usd";
  const b0 = A.b0;
  const scale = (v: number) => (usdMode ? v * b0 : v);
  const fmt = usdMode ? usd : (v: number) => pct(v);
  const views = B ? [A, B] : [A];
  const series: TimeSeries[] = views.map((v) => ({
    id: v.side,
    label: `${v.side.toUpperCase()} · ${display(v.out.label)}`,
    color: `var(--${v.side})`,
    values: usdMode ? cumulativeUsd(v.out) : cumulativeFraction(v.out),
    dashed: v.rangeFirst,
  }));
  const brackets: Bracket[] = [];
  for (const v of views) {
    const r = v.out.model_range;
    if (!r) continue;
    const offset = Math.max(0.15, v.months / 200) * (v.side === "a" ? -1 : 1);
    for (const [month, range] of [
      [12, r.principal_returned_fraction_12m],
      [24, r.principal_returned_fraction_24m],
    ] as const) {
      if (month <= v.months && hasRange(range) && range.max > range.min) {
        brackets.push({
          month: month + offset,
          low: scale(range.min),
          high: scale(range.max),
          color: `var(--${v.side})`,
          label: `${v.side.toUpperCase()} model-family spread at month ${month}: ${fmt(scale(range.min))}–${fmt(scale(range.max))}`,
        });
      }
    }
  }
  const n = A.months;
  return (
    <section className="panel chart-panel" aria-labelledby="principal-title" data-testid="principal-chart">
      <header className="panel-head">
        <div>
          <h2 id="principal-title">
            <Term method={method} metric="cumulative_principal_returned_fraction">
              Principal returned over time
            </Term>
          </h2>
          <p className="sub">
            Scheduled payments + early payoffs + recoveries, cumulative ·{" "}
            {usdMode ? "USD, undiscounted" : `% of today's ${usd(b0)} balance`} · months 1–{n}
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Units">
          <button type="button" aria-pressed={!usdMode} onClick={() => setUnit("pct")}>
            % of balance
          </button>
          <button type="button" aria-pressed={usdMode} onClick={() => setUnit("usd")}>
            US dollars
          </button>
        </div>
      </header>
      <div className="legend" aria-hidden="true">
        {series.map((s) => (
          <span key={s.id}>
            <i className={`key-line ${s.id}${s.dashed ? " dashed" : ""}`} />
            {s.label}
            {s.dashed ? " (unsupported: dashed)" : ""}
          </span>
        ))}
        {B && (
          <span>
            <i className="key-box gap" /> Gap between them
          </span>
        )}
        {brackets.length > 0 && (
          <span>
            <i className="key-bracket" /> Model-family spread at 12 and 24 months
          </span>
        )}
      </div>
      <TimeChart
        title={`Cumulative principal returned, ${usdMode ? "US dollars" : "percent of the as-of balance"}, by scenario`}
        summary={`Share of today's balance returned as principal cash under each scenario over ${n} months.`}
        series={series}
        x0={0}
        n={n}
        yDomain={[0, usdMode ? b0 : 1]}
        yFormat={fmt}
        yTickFormat={usdMode ? usd : (v) => pct(v, 0)}
        height={300}
        cursor={cursor.month}
        onCursor={cursor.set}
        band={B ? ["a", "b"] : undefined}
        brackets={brackets}
        endLabels
        monthLabel={cursor.label}
        testId="principal-svg"
        tooltip={(m) => {
          const a = series[0]?.values[m] ?? null;
          const b = series[1]?.values[m] ?? null;
          return (
            <div data-testid="principal-tip" data-month={m} data-a={a ?? ""} data-b={b ?? ""}>
              <div className="when">{cursor.label(m)}</div>
              {series.map((s) => {
                const v = s.values[m];
                return (
                  <div className="row" key={s.id}>
                    <i className={`key-line ${s.id}`} />
                    <span>{s.id.toUpperCase()}</span>
                    <strong>{v === null || v === undefined ? "n/a" : fmt(v)}</strong>
                  </div>
                );
              })}
              {a !== null && b !== null && (
                <div className="row gap-row">
                  <i />
                  <span>B − A</span>
                  <strong>{usdMode ? signedUsd(b - a) : `${signedPp((b - a) * 100)} · ${signedUsd((b - a) * b0)}`}</strong>
                </div>
              )}
            </div>
          );
        }}
      />
      <div className="scrub">
        <label htmlFor="cursor-month">Month</label>
        <button type="button" className="step small" aria-label="Previous month" onClick={() => cursor.set(Math.max(1, cursor.month - 1))}>
          ‹
        </button>
        <input
          id="cursor-month"
          type="range"
          min={1}
          max={n}
          value={cursor.month}
          onChange={(e) => cursor.set(Number(e.target.value))}
          aria-valuetext={cursor.label(cursor.month)}
        />
        <button type="button" className="step small" aria-label="Next month" onClick={() => cursor.set(Math.min(n, cursor.month + 1))}>
          ›
        </button>
        <span className="scrub-label" data-testid="cursor-label">
          {cursor.label(cursor.month)}
        </span>
      </div>
    </section>
  );
}

interface InspectorRow {
  key: string; // methodology metric (or a field name with a local definition)
  label: string;
  value: (r: MonthlyRow) => number | null;
  fmt: (v: number) => string;
  exact: (v: number) => string;
  delta: (v: number) => string;
}

const money = (key: keyof MonthlyRow, label: string): InspectorRow => ({
  key,
  label,
  value: (r) => r[key] as number,
  fmt: usd,
  exact: usdFull,
  delta: signedUsd,
});

const ROWS: InspectorRow[] = [
  { key: "market_rate_30y_pct", label: "Market rate, 30-yr", value: (r) => r.market_rate_30y_pct, fmt: (v) => ratePct(v), exact: (v) => ratePct(v, 3), delta: (v) => signed(v * 100, "bp", 0) },
  { key: "cpr_model", label: "Model CPR", value: (r) => r.cpr_model, fmt: (v) => pct(v), exact: (v) => pct(v, 3), delta: (v) => signedPp(v * 100) },
  money("beginning_upb_usd", "Beginning UPB"),
  money("scheduled_principal_usd", "Scheduled principal"),
  money("voluntary_prepay_principal_usd", "Voluntary payoffs"),
  money("credit_exit_principal_usd", "Credit exits (not cash)"),
  money("recoveries_received_usd", "Recoveries received"),
  money("illustrative_credit_loss_usd", "Illustrative loss"),
  money("contractual_interest_accrued_usd", "Interest accrued"),
  money("ending_upb_usd", "Ending UPB"),
  { key: "cumulative_principal_returned_fraction", label: "Cumulative returned", value: (r) => r.cumulative_principal_returned_fraction, fmt: (v) => pct(v), exact: (v) => pct(v, 3), delta: (v) => signedPp(v * 100) },
  { key: "out_of_support_share", label: "Rate inputs outside training range", value: (r) => r.out_of_support_share, fmt: (v) => pct(v), exact: (v) => pct(v, 2), delta: (v) => signedPp(v * 100) },
];

/** Definitions the methodology does not serve, written for this view. */
function localDefinition(key: string, method: Methodology | null, timing: string) {
  if (key === "market_rate_30y_pct") {
    return { label: "30-year mortgage rate (scenario input)", unit: "% per year", formula: `The hypothetical rate path for the month. ${timing}` };
  }
  if (key === "beginning_upb_usd") {
    return { label: "Beginning UPB", unit: "USD", formula: "B_t: the modeled remaining UPB carried in from the previous month's end (B_1 = today's balance)" };
  }
  return definition(method, key);
}

/** Cursor-linked readout: every served field at one month, with B − A and the served definition. */
export function Inspector({ A, B, cursor, method, timing }: { A: SideView; B: SideView | null; cursor: Cursor; method: Methodology | null; timing: string }) {
  const [selected, setSelected] = useState("cumulative_principal_returned_fraction");
  const i = cursor.month - 1;
  const ra = A.out.monthly[i];
  const rb = B?.out.monthly[i];
  const row = ROWS.find((r) => r.key === selected) ?? ROWS[0];
  const def = row ? localDefinition(row.key, method, timing) : null;
  if (!ra || !row) return null;
  return (
    <section className="panel inspector" aria-labelledby="inspector-title" data-testid="inspector" data-month={cursor.month}>
      <header className="panel-head">
        <h2 id="inspector-title">Inspector</h2>
        <span className="muted" data-testid="inspector-month">
          {cursor.label(cursor.month)}
        </span>
      </header>
      <table className="inspect-table">
        <caption className="sr-only">Served monthly values at {cursor.label(cursor.month)}; select a row for its definition</caption>
        <thead>
          <tr>
            <th scope="col" className="text">
              At this month
            </th>
            <th scope="col">A</th>
            {rb && <th scope="col">B</th>}
            {rb && <th scope="col">B − A</th>}
          </tr>
        </thead>
        <tbody>
          {ROWS.map((r) => {
            const va = r.value(ra);
            const vb = rb ? r.value(rb) : null;
            return (
              <tr key={r.key} className={r.key === selected ? "selected" : undefined} data-key={r.key} data-a={va ?? ""} data-b={vb ?? ""}>
                <th scope="row" className="text">
                  <button type="button" className="row-button" aria-pressed={r.key === selected} onClick={() => setSelected(r.key)}>
                    {r.label}
                  </button>
                </th>
                <td>{va === null ? "n/a" : r.fmt(va)}</td>
                {rb && <td>{vb === null ? "n/a" : r.fmt(vb)}</td>}
                {rb && <td className="delta-cell">{va === null || vb === null ? "n/a" : r.delta(vb - va)}</td>}
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="definition" aria-live="polite" data-testid="inspector-definition">
        <span className="kicker">Definition</span>
        {def ? (
          <>
            <strong>{def.label}</strong> <span className="muted">· {def.unit}</span>
            <code className="formula">{def.formula}</code>
          </>
        ) : (
          <span className="muted">Definition unavailable.</span>
        )}
        <span className="exact">
          A {row.value(ra) === null ? "n/a" : row.exact(row.value(ra) as number)}
          {rb && <> · B {row.value(rb) === null ? "n/a" : row.exact(row.value(rb) as number)}</>}
        </span>
      </div>
      <p className="identity" data-testid="inspector-identity">
        Begin − scheduled − payoffs − credit exits − end: A {usdCents(rowResidual(ra))}
        {rb && <> · B {usdCents(rowResidual(rb))}</>}
      </p>
    </section>
  );
}
