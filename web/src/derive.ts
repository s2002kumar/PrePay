// Every number the Scenario Lab shows is a served field or one named step on served fields.
// This module holds those steps, pure and unit-tested (derive.test.ts); components only format.
//
// Sign convention: the API serves A − B (`a_minus_b`). The lab reads B against A, so every
// comparison here is B − A, which is exactly the served delta with its sign flipped.

import type { Methodology, MonthlyRow, ProjectionResponse, RangeValue, ScenarioOut, Verdict } from "./types";

/** Below these sizes a difference reads as "about the same" (display rounding is finer). */
export const NEGLIGIBLE_MONTHS = 0.05;
export const NEGLIGIBLE_PP = 0.05;

export type Side = "a" | "b";

export interface Totals {
  scheduled: number; // Σ SP over the served months
  payoffs: number; // Σ PP
  creditExits: number; // Σ DC (exposure that left through a credit event; not cash)
  recoveries: number; // Σ RC (cash)
  losses: number; // Σ illustrative credit loss
  interest: number; // Σ contractual interest accrued
}

export interface SideView {
  side: Side;
  out: ScenarioOut;
  /** As-of balance B0: the first projected month's beginning UPB. */
  b0: number;
  /** Months of projection served for this horizon (a full-life horizon stops at the last payment). */
  months: number;
  /** Sums of the served monthly rows. */
  totals: Totals;
  /** Remaining UPB after the last served month (summary.ending_upb_horizon_usd). */
  ending: number;
  /** Principal cash returned through the horizon: SP + PP + RC. */
  principalCash: number;
  /** Credit exits not yet resolved into a recovery or a loss: Σ DC − Σ RC − Σ loss. */
  pending: number;
  /** Exposure identity residual: B0 − Σ SP − Σ PP − Σ DC − ending (should be 0). */
  residual: number;
  /** Largest monthly identity residual: |begin − SP − PP − DC − end|. */
  maxRowResidual: number;
  /** Largest gap between a month's beginning UPB and the previous month's ending UPB. */
  maxChainGap: number;
  verdict: Verdict | null;
  /** True when the service says to read the model-family range, not the point. */
  rangeFirst: boolean;
}

export function sumRows(rows: MonthlyRow[]): Totals {
  const t: Totals = { scheduled: 0, payoffs: 0, creditExits: 0, recoveries: 0, losses: 0, interest: 0 };
  for (const r of rows) {
    t.scheduled += r.scheduled_principal_usd;
    t.payoffs += r.voluntary_prepay_principal_usd;
    t.creditExits += r.credit_exit_principal_usd;
    t.recoveries += r.recoveries_received_usd;
    t.losses += r.illustrative_credit_loss_usd;
    t.interest += r.contractual_interest_accrued_usd;
  }
  return t;
}

/** One month's identity residual: beginning − scheduled − payoffs − credit exits − ending. */
export function rowResidual(r: MonthlyRow): number {
  return r.beginning_upb_usd - r.scheduled_principal_usd - r.voluntary_prepay_principal_usd - r.credit_exit_principal_usd - r.ending_upb_usd;
}

export function sideView(side: Side, out: ScenarioOut): SideView {
  const rows = out.monthly;
  const b0 = rows[0]?.beginning_upb_usd ?? 0;
  const totals = sumRows(rows);
  const ending = out.summary.ending_upb_horizon_usd;
  let maxRowResidual = 0;
  let maxChainGap = 0;
  rows.forEach((r, i) => {
    maxRowResidual = Math.max(maxRowResidual, Math.abs(rowResidual(r)));
    const prev = rows[i - 1];
    if (prev) maxChainGap = Math.max(maxChainGap, Math.abs(r.beginning_upb_usd - prev.ending_upb_usd));
  });
  return {
    side,
    out,
    b0,
    months: rows.length,
    totals,
    ending,
    principalCash: totals.scheduled + totals.payoffs + totals.recoveries,
    pending: totals.creditExits - totals.recoveries - totals.losses,
    residual: b0 - totals.scheduled - totals.payoffs - totals.creditExits - ending,
    maxRowResidual,
    maxChainGap,
    verdict: out.reliability?.verdict ?? null,
    rangeFirst: out.reliability?.headline === "range",
  };
}

/** B − A on the comparison's headline metrics: the served A − B deltas with their sign flipped. */
export interface Comparison {
  walYears: number | null; // −(A − B cash WAL, months) / 12
  returned12Pp: number | null;
  returned24Pp: number | null;
  interestUsd: number | null;
  endingUsd: number | null;
  /** B − A principal returned through the horizon, pp: no served delta, so from the two summaries. */
  returnedHorizonPp: number;
}

const flip = (v: number | null | undefined): number | null => (v === null || v === undefined ? null : -v);

export function compare(result: ProjectionResponse): Comparison | null {
  const d = result.a_minus_b;
  const b = result.b;
  if (!d || !b) return null;
  return {
    walYears: d.cash_wal_months === null ? null : -d.cash_wal_months / 12,
    returned12Pp: flip(d.principal_returned_12m_pp),
    returned24Pp: flip(d.principal_returned_24m_pp),
    interestUsd: flip(d.contractual_interest_accrued_horizon_usd),
    endingUsd: flip(d.ending_upb_horizon_usd),
    returnedHorizonPp: (b.summary.principal_returned_fraction_horizon - result.a.summary.principal_returned_fraction_horizon) * 100,
  };
}

export type Direction = "sooner" | "later" | "same";

/** How B's principal timing reads against A's, from the served cash-WAL delta. */
export function direction(walYears: number | null): Direction | null {
  if (walYears === null) return null;
  if (Math.abs(walYears * 12) < NEGLIGIBLE_MONTHS) return "same";
  return walYears < 0 ? "sooner" : "later";
}

/** The model families behind a range, each named once and in served order. */
export function rangeModels(out: ScenarioOut): string[] {
  return out.model_range?.models ?? [];
}

export function hasRange(range: RangeValue | undefined | null): range is { min: number; max: number } {
  return !!range && range.min !== null && range.max !== null;
}

// ------------------------------------------------------------------ series for the charts

/** Cumulative principal returned as a fraction of B0, with month 0 = 0 by definition. */
export function cumulativeFraction(out: ScenarioOut): number[] {
  return [0, ...out.monthly.map((r) => r.cumulative_principal_returned_fraction)];
}

/** Cumulative principal cash returned in USD, Σ (SP + PP + RC) to date, with month 0 = 0. */
export function cumulativeUsd(out: ScenarioOut): number[] {
  let running = 0;
  return [0, ...out.monthly.map((r) => (running += r.scheduled_principal_usd + r.voluntary_prepay_principal_usd + r.recoveries_received_usd))];
}

/** Remaining UPB with month 0 = B0 (the first month's beginning UPB). */
export function balanceSeries(out: ScenarioOut): number[] {
  return [out.monthly[0]?.beginning_upb_usd ?? 0, ...out.monthly.map((r) => r.ending_upb_usd)];
}

/** Month labels: index i is month i after the as-of month (YYYY-MM). */
export function monthLabels(out: ScenarioOut, asOf: string): string[] {
  return [asOf, ...out.monthly.map((r) => r.month)];
}

// ------------------------------------------------------------------ principal cash by period

export interface Period {
  label: string; // "Jul 2026" style for months, "Year 3" for projection years
  first: number; // first month (1-based)
  last: number;
  scheduled: number;
  payoffs: number;
  recoveries: number;
}

/**
 * Principal cash per period: monthly up to 36 months, otherwise per projection year (months
 * 1–12, 13–24, …) so every bucket has the same length. The last year may be partial; its label says so.
 */
export function cashPeriods(rows: MonthlyRow[]): Period[] {
  const size = rows.length <= 36 ? 1 : 12;
  const out: Period[] = [];
  for (let start = 0; start < rows.length; start += size) {
    const chunk = rows.slice(start, start + size);
    const t = sumRows(chunk);
    const first = start + 1;
    const last = start + chunk.length;
    const label = size === 1 ? `Month ${first}` : chunk.length < 12 ? `Year ${out.length + 1} (${chunk.length} mo)` : `Year ${out.length + 1}`;
    out.push({ label, first, last, scheduled: t.scheduled, payoffs: t.payoffs, recoveries: t.recoveries });
  }
  return out;
}

/** One y-axis maximum for A and B, so the two composition panels are drawn on the same scale. */
export function sharedPeriodMax(...series: Period[][]): number {
  let max = 0;
  for (const periods of series) for (const p of periods) max = Math.max(max, p.scheduled + p.payoffs + p.recoveries);
  return max;
}

// ------------------------------------------------------------------ applicability

export const VERDICT_TEXT: Record<Verdict, string> = {
  supported: "Supported",
  extrapolating: "Extrapolating",
  unsupported: "Unsupported",
};

/** Feature keys in the reliability payload, in plain words. */
export const FEATURE_NAMES: Record<string, string> = {
  incentive_bps: "Refinance incentive",
  market_rate_t1: "Market-rate level",
  rate_change_6m_bps: "6-month rate change",
  loan_age: "Loan age",
  burnout_months: "Burnout",
};

export function featureName(key: string): string {
  return FEATURE_NAMES[key] ?? key.replaceAll("_", " ");
}

/** Features with any balance outside the training range, largest first. */
export function outsideFeatures(out: ScenarioOut): [string, number][] {
  const by = out.reliability?.outside_share_by_feature ?? {};
  return Object.entries(by)
    .filter(([, v]) => v > 0)
    .sort((x, y) => y[1] - x[1]);
}

/** The thresholds stated by the served rule (ADR 0009 §7); drawn on the support gauge. */
export const RULE = { extrapolatingOutside: 0.05, extrapolatingOutsidePlusThin: 0.2, unsupportedOutside: 0.25 } as const;

// ------------------------------------------------------------------ definitions

export interface Definition {
  key: string;
  label: string;
  unit: string;
  formula: string;
}

export function definition(method: Methodology | null, key: string): Definition | null {
  const m = method?.metrics[key];
  return m ? { key, label: m.label, unit: m.unit, formula: m.formula } : null;
}

/** Clamp a cursor month into 1..n. */
export function clampMonth(month: number, n: number): number {
  return Math.max(1, Math.min(n, Math.round(month)));
}
