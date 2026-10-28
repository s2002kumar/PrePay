import { describe, expect, it } from "vitest";

import { pct, ratePct, signed, signedUsd, usd, years } from "./format";
import { scenarioFromCode, scenarioLabel } from "./routing";

describe("formatting keeps units and never invents precision", () => {
  it("formats money compactly with sign", () => {
    expect(usd(1_234_567)).toBe("$1.2M");
    expect(usd(-2500)).toBe("-$2.5K");
    expect(usd(null)).toBe("n/a");
    expect(signedUsd(-1500)).toBe("−$1.5K");
  });
  it("formats rates, fractions and durations", () => {
    expect(pct(0.1234)).toBe("12.3%");
    expect(ratePct(6.5)).toBe("6.50%");
    expect(years(7.257)).toBe("7.26 yr");
    expect(signed(-3.04, "mo")).toBe("−3.0 mo");
    expect(signed(Number.NaN, "mo")).toBe("n/a");
  });
});

describe("scenario codes in URLs", () => {
  it("parses presets", () => {
    expect(scenarioFromCode("flat", 6.5)).toEqual({ kind: "flat" });
    expect(scenarioFromCode("p-200", 6.5)).toEqual({ kind: "parallel", shock_bps: -200 });
    expect(scenarioFromCode("none", 6.5)).toBeNull();
  });
  it("builds a ramp from the as-of rate to the target", () => {
    const ramp = scenarioFromCode("ramp:4.50:4", 6.5);
    expect(ramp?.kind).toBe("custom");
    expect(ramp?.path_30y_pct).toEqual([6, 5.5, 5, 4.5]);
  });
  it("falls back to flat for unknown codes instead of failing", () => {
    expect(scenarioFromCode("<script>", 6.5)).toEqual({ kind: "flat" });
    expect(scenarioLabel("p200")).toBe("Parallel +200 bp");
  });
});
