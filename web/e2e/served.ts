// The served response behind a Scenario Lab URL, fetched independently of the UI.
import type { APIRequestContext } from "@playwright/test";

import type { ProjectionResponse, ScenarioIn } from "../src/types";

export const POOL = "fictional-2023-high-coupon";
export const GRID = ["flat", ...[-300, -250, -200, -150, -100, -50, 50, 100, 150, 200, 250, 300].map((bp) => `p${bp}`)];

function scenario(code: string): ScenarioIn | null {
  if (code === "none") return null;
  if (code === "flat") return { kind: "flat" };
  return { kind: "parallel", shock_bps: Number(code.slice(1)) };
}

export async function served(request: APIRequestContext, a: string, b: string, h: number, pool = POOL): Promise<ProjectionResponse> {
  const response = await request.post("/api/project", {
    data: {
      pool_id: pool,
      scenario: scenario(a),
      compare_to: scenario(b),
      horizon_months: h,
      credit: { severity: 0.35, recovery_lag_months: 12, annual_cdr_pct: null },
    },
  });
  if (!response.ok()) throw new Error(`project failed: ${response.status()}`);
  return (await response.json()) as ProjectionResponse;
}

/** The first grid scenario the service marks range-first (unsupported) against a flat A. */
export async function unsupportedCode(request: APIRequestContext, h: number, pool = POOL): Promise<string | null> {
  for (const code of [...GRID].reverse()) {
    const body = await served(request, "flat", code, h, pool);
    if (body.b?.reliability?.headline === "range") return code;
  }
  return null;
}

export function lab(a: string, b: string, h: number, pool = POOL): string {
  return `/scenario-lab?pool=${pool}&a=${a}&b=${b}&h=${h}`;
}
