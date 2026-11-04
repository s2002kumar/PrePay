import { useState } from "react";

import { StackedColumns } from "../../components/StackedColumns";
import { cashPeriods, type SideView, sharedPeriodMax } from "../../derive";
import { pct, signedUsd, usd, usdCents } from "../../format";
import { display } from "./Composer";

const PARTS = [
  { id: "scheduled", label: "Scheduled principal", color: "var(--c-sched)" },
  { id: "payoffs", label: "Early payoffs", color: "var(--c-pay)" },
  { id: "recoveries", label: "Recoveries (cash)", color: "var(--c-credit)" },
];

/** One scenario's as-of balance split: B0 = scheduled + payoffs + credit exits + still owed. */
function BalanceBar({ v }: { v: SideView }) {
  const s = v.out.summary;
  const segs = [
    { key: "sched", label: "Scheduled", value: s.scheduled_principal_horizon_usd },
    { key: "pay", label: "Early payoffs", value: s.voluntary_prepay_principal_horizon_usd },
    { key: "credit", label: "Credit exits", value: v.totals.creditExits },
    { key: "owed", label: "Still owed", value: s.ending_upb_horizon_usd },
  ];
  return (
    <div className="balance-bar" data-side={v.side}>
      <div className="balance-bar-head">
        <span>
          <i className={`swatch ${v.side}`} aria-hidden="true" /> <strong>{v.side.toUpperCase()}</strong> {display(v.out.label)}
        </span>
        <span className="muted">
          {usd(v.principalCash)} back as principal cash ({pct(s.principal_returned_fraction_horizon)})
        </span>
      </div>
      <div className="hbar" aria-hidden="true">
        {segs.map((g) =>
          g.value > 0 ? <span key={g.key} className={`seg ${g.key}`} style={{ flexGrow: g.value }} title={`${g.label} ${usd(g.value)}`} /> : null,
        )}
      </div>
    </div>
  );
}

export function Composition({ A, B }: { A: SideView; B: SideView | null }) {
  const [view, setView] = useState<"totals" | "time">("totals");
  const h = A.out.summary.horizon_months;
  const views = B ? [A, B] : [A];
  const periods = views.map((v) => cashPeriods(v.out.monthly));
  const yMax = sharedPeriodMax(...periods);
  const monthly = (periods[0]?.[0]?.last ?? 1) === 1;
  type Line = { key: string; label: string; note?: string; get: (v: SideView) => number; sub?: boolean; strong?: boolean };
  const lines: Line[] = [
    { key: "sched", label: "Scheduled principal", get: (v) => v.out.summary.scheduled_principal_horizon_usd },
    { key: "pay", label: "Early payoffs", note: "voluntary payoff principal", get: (v) => v.out.summary.voluntary_prepay_principal_horizon_usd },
    { key: "credit", label: "Credit exits", note: "exposure that left; not cash", get: (v) => v.totals.creditExits },
    { key: "rec", label: "recovered as cash", get: (v) => v.out.summary.recoveries_received_horizon_usd, sub: true },
    { key: "loss", label: "illustrative loss", get: (v) => v.out.summary.illustrative_credit_loss_horizon_usd, sub: true },
    { key: "pending", label: `not yet resolved by month ${h}`, note: "recovery lag", get: (v) => v.pending, sub: true },
    { key: "owed", label: `Still owed at month ${h}`, get: (v) => v.out.summary.ending_upb_horizon_usd },
    { key: "cash", label: "Principal cash returned", note: "scheduled + payoffs + recoveries", get: (v) => v.principalCash, strong: true },
  ];
  return (
    <section className="panel composition" aria-labelledby="composition-title" data-testid="composition">
      <header className="panel-head">
        <div>
          <h2 id="composition-title">Where today's {usd(A.b0)} goes</h2>
          <p className="sub">
            Every dollar of today's balance is repaid on schedule, paid off early, leaves through a credit exit, or is still
            owed at month {h}.
          </p>
        </div>
        <div className="segmented" role="group" aria-label="Composition view">
          <button type="button" aria-pressed={view === "totals"} onClick={() => setView("totals")}>
            Totals to month {h}
          </button>
          <button type="button" aria-pressed={view === "time"} onClick={() => setView("time")}>
            Cash over time
          </button>
        </div>
      </header>
      {view === "totals" ? (
        <>
          <div className="legend" aria-hidden="true">
            <span>
              <i className="key-box sched" /> Scheduled principal
            </span>
            <span>
              <i className="key-box pay" /> Early payoffs
            </span>
            <span>
              <i className="key-box credit" /> Credit exits (not cash)
            </span>
            <span>
              <i className="key-box owed" /> Still owed
            </span>
          </div>
          {views.map((v) => (
            <BalanceBar key={v.side} v={v} />
          ))}
          <div className="table-wrap" tabIndex={0} role="region" aria-label="Balance composition table">
            <table className="comp-table" data-parity>
              <caption>Where the as-of balance goes, months 1–{h} · USD and % of today's balance</caption>
              <thead>
                <tr>
                  <th scope="col" className="text">
                    Component
                  </th>
                  <th scope="col">A</th>
                  <th scope="col">% of B0</th>
                  {B && <th scope="col">B</th>}
                  {B && <th scope="col">% of B0</th>}
                  {B && <th scope="col">B − A</th>}
                </tr>
              </thead>
              <tbody>
                {lines.map((l) => (
                  <tr key={l.key} className={`${l.sub ? "sub-row" : ""}${l.strong ? " total-row" : ""}`} data-key={l.key} data-a={l.get(A)} data-b={B ? l.get(B) : ""}>
                    <th scope="row" className="text">
                      {!l.sub && !l.strong && <i className={`key-box ${l.key}`} aria-hidden="true" />}
                      {l.sub ? "↳ " : ""}
                      {l.label}
                      {l.note && <span className="muted"> · {l.note}</span>}
                    </th>
                    <td>{usd(l.get(A))}</td>
                    <td className="muted">{pct(l.get(A) / A.b0)}</td>
                    {B && <td>{usd(l.get(B))}</td>}
                    {B && <td className="muted">{pct(l.get(B) / B.b0)}</td>}
                    {B && <td>{signedUsd(l.get(B) - l.get(A))}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="identity" data-testid="composition-identity">
            <span className="check" aria-hidden="true">✓</span> Adds up: {usd(A.b0)} today = scheduled + early payoffs + credit
            exits + still owed. Residual from the served monthly rows: A {usdCents(A.residual)}
            {B && <> · B {usdCents(B.residual)}</>}.
          </p>
        </>
      ) : (
        <>
          <p className="sub">
            Principal cash per {monthly ? "month" : "projection year (months 1–12, 13–24, …)"} · USD, undiscounted · A and B
            share one scale. Credit exits are not cash until recovered.
          </p>
          <div className="legend" aria-hidden="true">
            {PARTS.map((p) => (
              <span key={p.id}>
                <i className="key-box" style={{ background: p.color }} /> {p.label}
              </span>
            ))}
          </div>
          <div className={`cash-grid${B ? " two" : ""}`}>
            {views.map((v, k) => {
              const ps = periods[k] ?? [];
              return (
                <div key={v.side} className="cash-panel">
                  <p className="cash-title">
                    <i className={`swatch ${v.side}`} aria-hidden="true" /> <strong>{v.side.toUpperCase()}</strong> {display(v.out.label)}
                  </p>
                  <StackedColumns
                    title={`Principal cash per ${monthly ? "month" : "projection year"}, scenario ${v.side.toUpperCase()}`}
                    summary="Scheduled principal, early payoffs and recoveries per period, on the same scale as the other scenario."
                    categories={ps.map((p) => (monthly ? p.label : `${p.label}: months ${p.first}–${p.last}`))}
                    tickLabels={ps.map((p) => String(monthly ? p.first : ps.indexOf(p) + 1))}
                    parts={PARTS}
                    values={ps.map((p) => [p.scheduled, p.payoffs, p.recoveries])}
                    format={usd}
                    yMax={yMax}
                    legend={false}
                    height={200}
                    testId={`cash-${v.side}`}
                  />
                </div>
              );
            })}
          </div>
          <p className="footnote">x-axis: {monthly ? "month" : "projection year"}. The two panels share the y-axis maximum ({usd(yMax)} before rounding).</p>
        </>
      )}
    </section>
  );
}
