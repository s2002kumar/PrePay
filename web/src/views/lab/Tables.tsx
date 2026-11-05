import { useEffect, useRef, useState } from "react";

import { type Comparison, hasRange, type SideView } from "../../derive";
import { pct, ratePct, signedPp, signedUsd, signedYears, usd, usdCents, usdFull, years } from "../../format";
import type { RangeValue } from "../../types";
import { display } from "./Composer";
import type { Cursor } from "./Timeline";

interface TableRow {
  key: string;
  label: string;
  basis: string;
  a: number | null;
  b: number | null;
  delta: number | null;
  fmt: (v: number) => string;
  deltaFmt: (v: number) => string;
  sub?: (v: number) => string;
  ra?: RangeValue | undefined;
  rb?: RangeValue | undefined;
  served?: boolean; // B − A is the served delta (sign flipped), not computed here
}

function rangeCell(r: RangeValue | undefined, f: (v: number) => string) {
  return hasRange(r) ? (r.min === r.max ? f(r.min) : `${f(r.min)}–${f(r.max)}`) : "—";
}

/** A's full analytical view: every headline metric for A, B, B − A and each model-family range. */
export function FullTable({ A, B, cmp }: { A: SideView; B: SideView | null; cmp: Comparison | null }) {
  const h = A.out.summary.horizon_months;
  const sa = A.out.summary;
  const sb = B?.out.summary;
  const ra = A.out.model_range;
  const rb = B?.out.model_range;
  const diff = (fa: number | null | undefined, fb: number | null | undefined) =>
    fa === null || fa === undefined || fb === null || fb === undefined ? null : fb - fa;
  const fpct = (v: number) => pct(v);
  const groups: [string, TableRow[]][] = [
    [
      "Timing",
      [
        { key: "cash_wal", label: "Cash weighted-average life", basis: "full life", a: sa.cash_wal_years, b: sb?.cash_wal_years ?? null, delta: cmp?.walYears ?? null, fmt: years, deltaFmt: signedYears, ra: ra?.cash_wal_years, rb: rb?.cash_wal_years, served: true },
        { key: "exit_wal", label: "Exposure-exit WAL", basis: "full life", a: sa.exposure_exit_wal_years, b: sb?.exposure_exit_wal_years ?? null, delta: diff(sa.exposure_exit_wal_years, sb?.exposure_exit_wal_years), fmt: years, deltaFmt: signedYears },
      ],
    ],
    [
      "Principal returned · % of today's balance",
      [
        { key: "ret12", label: "Within 12 months", basis: "months 1–12", a: sa.principal_returned_fraction_12m, b: sb?.principal_returned_fraction_12m ?? null, delta: cmp?.returned12Pp ?? null, fmt: fpct, deltaFmt: signedPp, ra: ra?.principal_returned_fraction_12m, rb: rb?.principal_returned_fraction_12m, served: true },
        { key: "ret24", label: "Within 24 months", basis: "months 1–24", a: sa.principal_returned_fraction_24m, b: sb?.principal_returned_fraction_24m ?? null, delta: cmp?.returned24Pp ?? null, fmt: fpct, deltaFmt: signedPp, ra: ra?.principal_returned_fraction_24m, rb: rb?.principal_returned_fraction_24m, served: true },
        { key: "retH", label: `Through month ${h}`, basis: `months 1–${h}`, a: sa.principal_returned_fraction_horizon, b: sb?.principal_returned_fraction_horizon ?? null, delta: cmp?.returnedHorizonPp ?? null, fmt: fpct, deltaFmt: signedPp, sub: (v) => usd(v * A.b0) },
      ],
    ],
    [
      `Balance and interest · through month ${h}`,
      [
        { key: "owed", label: `Still owed at month ${h}`, basis: `at month ${h}`, a: sa.ending_upb_horizon_usd, b: sb?.ending_upb_horizon_usd ?? null, delta: cmp?.endingUsd ?? null, fmt: usd, deltaFmt: signedUsd, ra: ra?.ending_upb_horizon_usd, rb: rb?.ending_upb_horizon_usd, served: true },
        { key: "interest", label: "Contractual interest accrued", basis: `months 1–${h}`, a: sa.contractual_interest_accrued_horizon_usd, b: sb?.contractual_interest_accrued_horizon_usd ?? null, delta: cmp?.interestUsd ?? null, fmt: usd, deltaFmt: signedUsd, served: true },
      ],
    ],
    [
      "Credit · stated assumption, not a model estimate",
      [
        { key: "exits", label: "Credit exits (exposure, not cash)", basis: `months 1–${h}`, a: A.totals.creditExits, b: B?.totals.creditExits ?? null, delta: diff(A.totals.creditExits, B?.totals.creditExits), fmt: usd, deltaFmt: signedUsd },
        { key: "recov", label: "Recoveries received (cash)", basis: `months 1–${h}`, a: sa.recoveries_received_horizon_usd, b: sb?.recoveries_received_horizon_usd ?? null, delta: diff(sa.recoveries_received_horizon_usd, sb?.recoveries_received_horizon_usd), fmt: usd, deltaFmt: signedUsd },
        { key: "loss", label: "Illustrative losses", basis: `months 1–${h}`, a: sa.illustrative_credit_loss_horizon_usd, b: sb?.illustrative_credit_loss_horizon_usd ?? null, delta: diff(sa.illustrative_credit_loss_horizon_usd, sb?.illustrative_credit_loss_horizon_usd), fmt: usd, deltaFmt: signedUsd },
        { key: "pending", label: "Not yet resolved (recovery lag)", basis: `after month ${h}`, a: A.pending, b: B?.pending ?? null, delta: diff(A.pending, B?.pending), fmt: usd, deltaFmt: signedUsd },
      ],
    ],
  ];
  const cols = B ? 7 : 4;
  return (
    <details className="panel full-table" id="full-table">
      <summary>
        <span className="summary-title">Full comparison table</span>
        <span className="muted">A, B, B − A and the model-family range for every headline metric</span>
      </summary>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Full comparison table">
        <table data-parity>
          <caption>
            A: {display(A.out.label)}
            {B ? ` · B: ${display(B.out.label)}` : ""} · served summaries; B − A marked * is the served A − B delta with its sign flipped
          </caption>
          <thead>
            <tr>
              <th scope="col" className="text">
                Metric
              </th>
              <th scope="col" className="text">
                Window
              </th>
              <th scope="col">A</th>
              {B && <th scope="col">B</th>}
              {B && <th scope="col">B − A</th>}
              <th scope="col">A model range</th>
              {B && <th scope="col">B model range</th>}
            </tr>
          </thead>
          {groups.map(([title, rows]) => (
            <tbody key={title}>
              <tr className="group-row">
                <th scope="rowgroup" colSpan={cols} className="text">
                  {title}
                </th>
              </tr>
              {rows.map((r) => (
                <tr key={r.key} data-key={r.key} data-a={r.a ?? ""} data-b={r.b ?? ""} data-delta={r.delta ?? ""}>
                  <th scope="row" className="text">
                    {r.label}
                  </th>
                  <td className="text muted">{r.basis}</td>
                  <td>
                    {r.a === null ? "n/a" : r.fmt(r.a)}
                    {r.sub && r.a !== null && <span className="cell-sub">{r.sub(r.a)}</span>}
                  </td>
                  {B && (
                    <td>
                      {r.b === null ? "n/a" : r.fmt(r.b)}
                      {r.sub && r.b !== null && <span className="cell-sub">{r.sub(r.b)}</span>}
                    </td>
                  )}
                  {B && (
                    <td>
                      {r.delta === null ? "n/a" : r.deltaFmt(r.delta)}
                      {r.served ? "*" : ""}
                    </td>
                  )}
                  <td className={A.rangeFirst ? "emph" : "muted"}>{rangeCell(r.ra, r.fmt)}</td>
                  {B && <td className={B.rangeFirst ? "emph" : "muted"}>{rangeCell(r.rb, r.fmt)}</td>}
                </tr>
              ))}
            </tbody>
          ))}
          <tbody>
            <tr className="group-row">
              <th scope="rowgroup" colSpan={cols} className="text">
                Reconciliation
              </th>
            </tr>
            <tr data-key="residual">
              <th scope="row" className="text">
                Balance identity residual
              </th>
              <td className="text muted">B0 − SP − PP − DC − end</td>
              <td>{usdCents(A.residual)}</td>
              {B && <td>{usdCents(B.residual)}</td>}
              {B && <td />}
              <td />
              {B && <td />}
            </tr>
          </tbody>
        </table>
      </div>
    </details>
  );
}

const LEDGER_ROW = 33;

/** The served monthly rows in whole dollars, with totals and the balance check. */
export function Ledger({ A, B, cursor }: { A: SideView; B: SideView | null; cursor: Cursor }) {
  const [side, setSide] = useState<"a" | "b">("a");
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const v = side === "b" && B ? B : A;
  const rows = v.out.monthly;
  const t = v.totals;
  useEffect(() => {
    const el = box.current;
    if (!el || !open) return;
    const top = (cursor.month - 1) * LEDGER_ROW;
    if (top < el.scrollTop || top > el.scrollTop + el.clientHeight - 2 * LEDGER_ROW) el.scrollTop = Math.max(0, top - el.clientHeight / 2);
  }, [cursor.month, open, side]);
  return (
    <details className="panel ledger" id="ledger" onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary>
        <span className="summary-title">Monthly ledger</span>
        <span className="muted">
          {rows.length} served rows per scenario · whole USD, undiscounted · totals and the balance check underneath
        </span>
      </summary>
      {B && (
        <div className="segmented" role="group" aria-label="Ledger scenario">
          <button type="button" aria-pressed={side === "a"} onClick={() => setSide("a")}>
            A · {display(A.out.label)}
          </button>
          <button type="button" aria-pressed={side === "b"} onClick={() => setSide("b")}>
            B · {display(B.out.label)}
          </button>
        </div>
      )}
      <div className="table-wrap ledger-wrap" ref={box} tabIndex={0} role="region" aria-label={`Monthly ledger, scenario ${v.side.toUpperCase()}`}>
        <table data-parity>
          <caption>
            Monthly ledger, scenario {v.side.toUpperCase()} ({display(v.out.label)}), USD
          </caption>
          <thead>
            <tr>
              <th scope="col">Mo</th>
              <th scope="col" className="text">
                Month
              </th>
              <th scope="col">30y rate</th>
              <th scope="col">Begin UPB</th>
              <th scope="col">Scheduled</th>
              <th scope="col">Payoffs</th>
              <th scope="col">Credit exits</th>
              <th scope="col">Recoveries</th>
              <th scope="col">Illus. loss</th>
              <th scope="col">Interest</th>
              <th scope="col">End UPB</th>
              <th scope="col">CPR</th>
              <th scope="col">Cum. returned</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={r.month} className={i + 1 === cursor.month ? "current" : undefined} onClick={() => cursor.set(i + 1)}>
                <td>{i + 1}</td>
                <td className="text">{r.month}</td>
                <td>{ratePct(r.market_rate_30y_pct)}</td>
                <td>{usdFull(r.beginning_upb_usd)}</td>
                <td>{usdFull(r.scheduled_principal_usd)}</td>
                <td>{usdFull(r.voluntary_prepay_principal_usd)}</td>
                <td>{usdFull(r.credit_exit_principal_usd)}</td>
                <td>{usdFull(r.recoveries_received_usd)}</td>
                <td>{usdFull(r.illustrative_credit_loss_usd)}</td>
                <td>{usdFull(r.contractual_interest_accrued_usd)}</td>
                <td>{usdFull(r.ending_upb_usd)}</td>
                <td>{pct(r.cpr_model)}</td>
                <td>{pct(r.cumulative_principal_returned_fraction)}</td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr className="total-row">
              <th scope="row" colSpan={3} className="text">
                Total, months 1–{rows.length}
              </th>
              <td>{usdFull(v.b0)}</td>
              <td>{usdFull(t.scheduled)}</td>
              <td>{usdFull(t.payoffs)}</td>
              <td>{usdFull(t.creditExits)}</td>
              <td>{usdFull(t.recoveries)}</td>
              <td>{usdFull(t.losses)}</td>
              <td>{usdFull(t.interest)}</td>
              <td>{usdFull(v.ending)}</td>
              <td />
              <td>{pct(v.out.summary.principal_returned_fraction_horizon)}</td>
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="identity" data-testid="ledger-identity">
        Begin UPB of month 1 − Σ scheduled − Σ payoffs − Σ credit exits − end UPB = {usdCents(v.residual)} · largest monthly
        residual {usdCents(v.maxRowResidual)} · each month begins where the last ended (largest gap {usdCents(v.maxChainGap)}).
        Click a row to move the cursor; <span className="muted">B − A for any month is in the inspector.</span>
      </p>
    </details>
  );
}
