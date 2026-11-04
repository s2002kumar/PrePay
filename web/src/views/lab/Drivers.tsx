import { TimeChart, type TimeSeries } from "../../components/TimeChart";
import { balanceSeries, type SideView } from "../../derive";
import { pct, ratePct, usd } from "../../format";
import type { Methodology, PoolSummary } from "../../types";
import { Term } from "./common";
import type { Cursor } from "./Timeline";

function pair(A: SideView, B: SideView | null, pick: (v: SideView) => (number | null)[]): TimeSeries[] {
  return (B ? [A, B] : [A]).map((v) => ({
    id: v.side,
    label: v.side.toUpperCase(),
    color: `var(--${v.side})`,
    values: pick(v),
    dashed: v.rangeFirst,
  }));
}

/** Input → model → result: the rate path, the modeled payoff speed it implies, and the balance left. */
export function Drivers({ A, B, cursor, method, pool, timing }: {
  A: SideView;
  B: SideView | null;
  cursor: Cursor;
  method: Methodology | null;
  pool: PoolSummary | undefined;
  timing: string;
}) {
  const n = A.months;
  const i = cursor.month - 1;
  const at = (v: SideView | null, f: (r: SideView["out"]["monthly"][number]) => number | null) => {
    const r = v?.out.monthly[i];
    return r ? f(r) : null;
  };
  const rateA = at(A, (r) => r.market_rate_30y_pct);
  const rateB = at(B, (r) => r.market_rate_30y_pct);
  const cprA = at(A, (r) => r.cpr_model);
  const cprB = at(B, (r) => r.cpr_model);
  const balA = at(A, (r) => r.ending_upb_usd);
  const balB = at(B, (r) => r.ending_upb_usd);
  const m = cursor.label(cursor.month);
  const wac = pool?.wac_pct ?? null;
  return (
    <section className="drivers" aria-labelledby="drivers-title">
      <div className="section-head">
        <h2 id="drivers-title">Why the scenarios differ</h2>
        <p className="sub">The input, what the model does with it, and the result. One cursor moves all three.</p>
      </div>
      <div className="drivers-grid">
        <div className="panel driver">
          <h3>
            <span className="step-no">1</span> Mortgage rates <span className="muted">· your input</span>
          </h3>
          <TimeChart
            compact
            title="30-year mortgage rate path by scenario, percent per year"
            summary={`Hypothetical 30-year rate each month. ${timing}`}
            series={pair(A, B, (v) => v.out.monthly.map((r) => r.market_rate_30y_pct))}
            x0={1}
            n={n}
            yFormat={(v) => ratePct(v)}
            yTickFormat={(v) => `${v.toFixed(1)}%`}
            refs={wac === null ? [] : [{ y: wac, label: `Pool WAC ${ratePct(wac)} (as of)` }]}
            height={190}
            cursor={cursor.month}
            onCursor={cursor.set}
            monthLabel={cursor.label}
            testId="rate-chart"
          />
          <p className="driver-read" data-testid="rate-read">
            {m}: {B ? <>B {ratePct(rateB)} vs A {ratePct(rateA)}.</> : <>A {ratePct(rateA)}.</>} Refinancing pays when market
            rates fall below a loan's note rate{wac === null ? "" : `; this pool's balance-weighted note rate (WAC) is ${ratePct(wac)}`}.
          </p>
        </div>
        <div className="panel driver">
          <h3>
            <span className="step-no">2</span>
            <Term method={method} metric="cpr_model">
              Payoff speed
            </Term>{" "}
            <span className="muted">· the model</span>
          </h3>
          <TimeChart
            compact
            title="Modeled payoff speed (CPR, full payoffs only) by scenario, percent per year"
            summary="Annualized full-payoff rate implied by the model each month."
            series={pair(A, B, (v) => v.out.monthly.map((r) => r.cpr_model))}
            x0={1}
            n={n}
            includeZero
            yFormat={(v) => pct(v)}
            yTickFormat={(v) => pct(v, 0)}
            marks={n >= 2 ? [{ month: 2, label: "Scenario rates act from month 2" }] : []}
            height={190}
            cursor={cursor.month}
            onCursor={cursor.set}
            monthLabel={cursor.label}
            testId="cpr-chart"
          />
          <p className="driver-read" data-testid="cpr-read">
            {m}: modeled payoff speed {B ? <>is {pct(cprB)} a year under B vs {pct(cprA)} under A.</> : <>is {pct(cprA)} a year.</>}
          </p>
        </div>
        <div className="panel driver">
          <h3>
            <span className="step-no">3</span>
            <Term method={method} metric="ending_upb_usd">
              Balance still owed
            </Term>{" "}
            <span className="muted">· the result</span>
          </h3>
          <TimeChart
            compact
            title="Modeled remaining balance by scenario, US dollars"
            summary="Expected unpaid principal at each month end, starting from today's balance."
            series={pair(A, B, (v) => balanceSeries(v.out))}
            x0={0}
            n={n}
            yDomain={[0, A.b0]}
            yFormat={usd}
            height={190}
            cursor={cursor.month}
            onCursor={cursor.set}
            monthLabel={cursor.label}
            testId="balance-chart"
          />
          <p className="driver-read" data-testid="balance-read">
            {m}: {B ? <>{usd(balB)} still owed under B vs {usd(balA)} under A.</> : <>{usd(balA)} still owed.</>}
          </p>
        </div>
      </div>
    </section>
  );
}
