import { describe, expect, it } from "vitest";

import {
  balanceSeries,
  cashPeriods,
  compare,
  cumulativeFraction,
  cumulativeUsd,
  direction,
  outsideFeatures,
  rowResidual,
  sharedPeriodMax,
  sideView,
  sumRows,
} from "./derive";
import { signedPp, signedUsd, signedYears, usdCents } from "./format";
import { scenarioShort } from "./routing";
import type { MonthlyRow, ProjectionResponse, ScenarioOut } from "./types";

/** A conserving ledger: each month pays `sp` scheduled and a `smm` share of the rest as payoffs. */
function ledger(n: number, b0: number, smm: number, dcRate = 0.001, severity = 0.35, lag = 2): MonthlyRow[] {
  const rows: MonthlyRow[] = [];
  const exits: number[] = [];
  let begin = b0;
  let returned = 0;
  for (let t = 0; t < n; t++) {
    const sp = begin * 0.002;
    const pp = (begin - sp) * smm;
    const dc = (begin - sp) * dcRate;
    exits.push(dc);
    const resolved = t >= lag ? (exits[t - lag] ?? 0) : 0;
    const rc = (1 - severity) * resolved;
    const loss = severity * resolved;
    const end = begin - sp - pp - dc;
    returned += sp + pp + rc;
    rows.push({
      month: `2026-${String(t + 7).padStart(2, "0")}`,
      market_rate_30y_pct: 6.5,
      beginning_upb_usd: begin,
      scheduled_principal_usd: sp,
      voluntary_prepay_principal_usd: pp,
      credit_exit_principal_usd: dc,
      recoveries_received_usd: rc,
      illustrative_credit_loss_usd: loss,
      contractual_interest_accrued_usd: begin * 0.065 / 12,
      ending_upb_usd: end,
      cpr_model: 1 - (1 - smm) ** 12,
      credit_exit_rate_annualized: null,
      cumulative_principal_returned_fraction: returned / b0,
      out_of_support_share: 0,
    });
    begin = end;
  }
  return rows;
}

function scenario(label: string, rows: MonthlyRow[], wal: number, headline: "point" | "range" = "point"): ScenarioOut {
  const t = sumRows(rows);
  const last = rows[rows.length - 1] as MonthlyRow;
  return {
    kind: "parallel",
    shock_bps: 0,
    label,
    monthly: rows,
    summary: {
      horizon_months: rows.length,
      cash_wal_years: wal,
      exposure_exit_wal_years: wal - 0.01,
      principal_returned_fraction_12m: rows[11]?.cumulative_principal_returned_fraction ?? null,
      principal_returned_fraction_24m: rows[23]?.cumulative_principal_returned_fraction ?? null,
      principal_returned_fraction_horizon: last.cumulative_principal_returned_fraction,
      contractual_interest_accrued_horizon_usd: t.interest,
      scheduled_principal_horizon_usd: t.scheduled,
      voluntary_prepay_principal_horizon_usd: t.payoffs,
      recoveries_received_horizon_usd: t.recoveries,
      illustrative_credit_loss_horizon_usd: t.losses,
      ending_upb_horizon_usd: last.ending_upb_usd,
      pending_recoveries_horizon_usd: 0.65 * (t.creditExits - t.recoveries - t.losses),
      max_out_of_support_share_horizon: 0,
    },
    reliability: {
      verdict: headline === "range" ? "unsupported" : "extrapolating",
      outside_share: headline === "range" ? 0.9 : 0.07,
      sparse_share: 0.1,
      outside_share_by_feature: { loan_age: 0.01, market_rate_t1: headline === "range" ? 0.9 : 0, burnout_months: 0.06 },
      reasons: [],
      headline,
    },
    model_range: null,
  };
}

const B0 = 1_000_000;
const a = scenario("Flat at last observed", ledger(48, B0, 0.01), 7.5);
const b = scenario("Parallel -100 bp", ledger(48, B0, 0.03), 3.25, "range");
const result: ProjectionResponse = {
  data_class: "fictional",
  notice: "n",
  pool_id: "p",
  as_of: "2026-06",
  model: "B2_logistic",
  assumptions: {},
  a,
  b,
  // served as A − B
  a_minus_b: {
    cash_wal_months: (7.5 - 3.25) * 12,
    principal_returned_12m_pp: -12.5,
    principal_returned_24m_pp: -20,
    contractual_interest_accrued_horizon_usd: 5000,
    ending_upb_horizon_usd: 250_000,
  },
  warnings: [],
};

describe("side view reconciles the served monthly rows", () => {
  const v = sideView("a", a);
  it("takes B0 from the first month and conserves the balance", () => {
    expect(v.b0).toBe(B0);
    expect(Math.abs(v.residual)).toBeLessThan(1e-6);
    expect(v.maxRowResidual).toBeLessThan(1e-6);
    expect(v.maxChainGap).toBe(0);
    for (const r of a.monthly) expect(Math.abs(rowResidual(r))).toBeLessThan(1e-9);
  });
  it("splits credit exits into recovered, lost and still pending", () => {
    expect(v.pending).toBeCloseTo(v.totals.creditExits - v.totals.recoveries - v.totals.losses, 9);
    expect(v.pending).toBeGreaterThan(0); // the last `lag` months of exits are unresolved
    expect(0.65 * v.pending).toBeCloseTo(a.summary.pending_recoveries_horizon_usd, 6);
  });
  it("principal cash is scheduled + payoffs + recoveries and equals the served cumulative fraction", () => {
    expect(v.principalCash).toBeCloseTo(v.totals.scheduled + v.totals.payoffs + v.totals.recoveries, 6);
    expect(v.principalCash / v.b0).toBeCloseTo(a.summary.principal_returned_fraction_horizon, 12);
  });
  it("marks range-first scenarios from the served headline", () => {
    expect(v.rangeFirst).toBe(false);
    expect(sideView("b", b).rangeFirst).toBe(true);
  });
});

describe("B − A is the served A − B with its sign flipped", () => {
  const c = compare(result);
  it("flips every served delta", () => {
    expect(c?.walYears).toBeCloseTo(-(7.5 - 3.25), 12);
    expect(c?.walYears).toBeCloseTo((b.summary.cash_wal_years ?? 0) - (a.summary.cash_wal_years ?? 0), 12);
    expect(c?.returned12Pp).toBe(12.5);
    expect(c?.returned24Pp).toBe(20);
    expect(c?.interestUsd).toBe(-5000);
    expect(c?.endingUsd).toBe(-250_000);
  });
  it("computes the horizon return gap from the two summaries", () => {
    const expected = (b.summary.principal_returned_fraction_horizon - a.summary.principal_returned_fraction_horizon) * 100;
    expect(c?.returnedHorizonPp).toBeCloseTo(expected, 12);
    expect(c?.returnedHorizonPp).toBeGreaterThan(0); // B pays faster
  });
  it("has no comparison without B", () => {
    expect(compare({ ...result, b: null, a_minus_b: null })).toBeNull();
  });
  it("reads the direction from the sign, with a negligible band", () => {
    expect(direction(-4.25)).toBe("sooner");
    expect(direction(1)).toBe("later");
    expect(direction(0.003)).toBe("same"); // 0.036 months
    expect(direction(null)).toBeNull();
  });
});

describe("chart series", () => {
  it("starts cumulative series at 0 and balance at B0 (month 0)", () => {
    expect(cumulativeFraction(a)[0]).toBe(0);
    expect(cumulativeFraction(a)).toHaveLength(49);
    expect(balanceSeries(a)[0]).toBe(B0);
    expect(balanceSeries(a)[48]).toBe(a.summary.ending_upb_horizon_usd);
  });
  it("dollar series is the cumulative fraction times B0", () => {
    const usd = cumulativeUsd(a);
    const frac = cumulativeFraction(a);
    usd.forEach((v, i) => expect(v).toBeCloseTo((frac[i] ?? 0) * B0, 6));
  });
});

describe("principal cash by period", () => {
  it("uses months up to 36 and equal 12-month buckets beyond", () => {
    const short = cashPeriods(a.monthly.slice(0, 24));
    expect(short).toHaveLength(24);
    expect(short[0]?.label).toBe("Month 1");
    const long = cashPeriods(ledger(40, B0, 0.02));
    expect(long.map((p) => [p.first, p.last])).toEqual([[1, 12], [13, 24], [25, 36], [37, 40]]);
    expect(long[3]?.label).toBe("Year 4 (4 mo)");
  });
  it("preserves totals", () => {
    const rows = ledger(40, B0, 0.02);
    const t = sumRows(rows);
    const p = cashPeriods(rows);
    const sum = p.reduce((s, x) => s + x.scheduled + x.payoffs + x.recoveries, 0);
    expect(sum).toBeCloseTo(t.scheduled + t.payoffs + t.recoveries, 6);
  });
  it("gives A and B one shared scale", () => {
    const pa = cashPeriods(a.monthly);
    const pb = cashPeriods(b.monthly);
    const max = sharedPeriodMax(pa, pb);
    const peak = (ps: typeof pa) => Math.max(...ps.map((x) => x.scheduled + x.payoffs + x.recoveries));
    expect(max).toBe(Math.max(peak(pa), peak(pb)));
    expect(max).toBe(peak(pb)); // the faster scenario sets the scale for both
  });
});

describe("applicability", () => {
  it("lists outside features largest first, dropping zeros", () => {
    expect(outsideFeatures(a).map(([k]) => k)).toEqual(["burnout_months", "loan_age"]);
  });
});

describe("formatting keeps the sign and the unit", () => {
  it("prints B − A with a true minus and a unit", () => {
    expect(signedYears(-4.2512)).toBe("−4.25 yr");
    expect(signedPp(36.04)).toBe("+36.0 pp");
    expect(signedUsd(-65_500_000)).toBe("−$65.5M");
    expect(signedYears(0)).toBe("±0.00 yr");
  });
  it("prints reconciliation residuals to the cent, without a negative zero", () => {
    expect(usdCents(-1e-7)).toBe("$0.00");
    expect(usdCents(0.004)).toBe("$0.00");
    expect(usdCents(-12.345)).toBe("−$12.35");
  });
  it("short scenario names", () => {
    expect(scenarioShort("p-100")).toBe("−100 bp");
    expect(scenarioShort("p200")).toBe("+200 bp");
    expect(scenarioShort("flat")).toBe("Flat");
  });
});
