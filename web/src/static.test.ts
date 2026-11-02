import { describe, expect, it } from "vitest";

import { assemble, STATIC_SCENARIOS, staticCode } from "./static";
import type { MonthlyRow, ProjectionResponse } from "./types";

const row = (month: string): MonthlyRow => ({
  month,
  market_rate_30y_pct: 6,
  beginning_upb_usd: 100,
  scheduled_principal_usd: 1,
  voluntary_prepay_principal_usd: 2,
  credit_exit_principal_usd: 0,
  recoveries_received_usd: 0,
  illustrative_credit_loss_usd: 0,
  contractual_interest_accrued_usd: 0.5,
  ending_upb_usd: 97,
  cpr_model: 0.2,
  credit_exit_rate_annualized: 0,
  cumulative_principal_returned_fraction: 0.03,
  out_of_support_share: 0,
});

describe("static adapter", () => {
  it("maps only grid scenarios to codes", () => {
    expect(STATIC_SCENARIOS).toHaveLength(13);
    expect(staticCode({ kind: "flat" })).toBe("flat");
    expect(staticCode({ kind: "parallel", shock_bps: -150 })).toBe("p-150");
    expect(staticCode({ kind: "parallel", shock_bps: 75 })).toBeNull();
    expect(staticCode({ kind: "custom", path_30y_pct: [5] })).toBeNull();
    expect(staticCode(null)).toBe("none");
  });

  it("slices monthly rows to the horizon and takes pair fields from the pair file", () => {
    const summary = { horizon_months: 2 } as ProjectionResponse["a"]["summary"];
    const stored = {
      scenario: { kind: "flat" as const, shock_bps: 0, label: "Flat" },
      monthly: [row("2026-07"), row("2026-08"), row("2026-09")],
      by_horizon: { "2": { summary, reliability: null, model_range: null } },
    };
    const index = {
      format: 1,
      scenarios: ["flat"],
      horizons: [2],
      pools: { p: { data_class: "fictional" as const, notice: "n", pool_id: "p", as_of: "2026-06", model: "B2_logistic", assumptions: {} } },
    };
    const pairs = { "flat|none": { a_minus_b: null, warnings: ["w"] } };
    const out = assemble(index, { flat: stored }, pairs, "p", "flat", "none", 2);
    expect(out.a.monthly.map((r) => r.month)).toEqual(["2026-07", "2026-08"]);
    expect(out.b).toBeNull();
    expect(out.warnings).toEqual(["w"]);
    expect(out.model).toBe("B2_logistic");
    expect(() => assemble(index, { flat: stored }, pairs, "p", "flat", "flat", 2)).toThrow(/No precomputed comparison/);
  });
});
