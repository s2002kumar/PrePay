// Static-site mode: the API's responses, precomputed by `prepay demo export-static` on a fixed
// grid (src/prepay/api/static.py). `assemble` mirrors the Python function of the same name, which
// the export checks against every live API response it covers.

import { ApiRequestError } from "./errors";
import type { MonthlyRow, ProjectionRequest, ProjectionResponse, ScenarioIn, ScenarioOut } from "./types";

export const STATIC = import.meta.env.VITE_PREPAY_STATIC === "1";
const DATA = `${import.meta.env.BASE_URL}data/`;

/** Precomputed scenario codes; must equal STATIC_SCENARIOS in src/prepay/api/static.py. */
export const STATIC_SCENARIOS = [
  "flat",
  ...[-300, -250, -200, -150, -100, -50, 50, 100, 150, 200, 250, 300].map((bp) => `p${bp}`),
];
/** The credit inputs the static grid was computed with (the API's CreditIn defaults). */
export const STATIC_CREDIT = { severity: 0.35, recovery_lag_months: 12, annual_cdr_pct: null };

type PerPool = Pick<ProjectionResponse, "data_class" | "notice" | "pool_id" | "as_of" | "model" | "assumptions">;
interface StaticIndex {
  format: number;
  scenarios: string[];
  horizons: number[];
  pools: Record<string, PerPool>;
}
interface StoredProjection {
  scenario: Pick<ScenarioOut, "kind" | "shock_bps" | "label">;
  monthly: MonthlyRow[];
  by_horizon: Record<string, Pick<ScenarioOut, "summary" | "reliability" | "model_range">>;
}
type Pairs = Record<string, Pick<ProjectionResponse, "a_minus_b" | "warnings">>;

const files = new Map<string, Promise<unknown>>();

export function loadStatic<T>(path: string): Promise<T> {
  let pending = files.get(path);
  if (!pending) {
    pending = fetch(`${DATA}${path}`, { headers: { Accept: "application/json" } }).then((response) => {
      if (!response.ok) throw new ApiRequestError(response.status, "static_missing", `Static data unavailable (${path})`);
      return response.json();
    });
    pending.catch(() => files.delete(path));
    files.set(path, pending);
  }
  return pending as Promise<T>;
}

/** The URL code of a scenario on the static grid, or null when the grid does not hold it. */
export function staticCode(scenario: ScenarioIn | null): string | null {
  if (scenario === null) return "none";
  if (scenario.kind === "flat") return "flat";
  if (scenario.kind === "parallel") {
    const code = `p${scenario.shock_bps ?? 0}`;
    return STATIC_SCENARIOS.includes(code) ? code : null;
  }
  return null;
}

export function assemble(
  index: StaticIndex,
  projections: Record<string, StoredProjection>,
  pairs: Pairs,
  poolId: string,
  codeA: string,
  codeB: string,
  horizon: number,
): ProjectionResponse {
  const scenarioOut = (code: string): ScenarioOut => {
    const stored = projections[code];
    const at = stored?.by_horizon[String(horizon)];
    if (!stored || !at) throw new ApiRequestError(404, "static_missing", `No precomputed projection for ${code}`);
    return { ...stored.scenario, summary: at.summary, monthly: stored.monthly.slice(0, horizon), reliability: at.reliability, model_range: at.model_range };
  };
  const pool = index.pools[poolId];
  const pair = pairs[`${codeA}|${codeB}`];
  if (!pool || !pair) throw new ApiRequestError(404, "static_missing", "No precomputed comparison for these inputs");
  return {
    ...pool,
    a: scenarioOut(codeA),
    b: codeB === "none" ? null : scenarioOut(codeB),
    a_minus_b: pair.a_minus_b,
    warnings: pair.warnings,
  };
}

export async function staticProject(request: ProjectionRequest): Promise<ProjectionResponse> {
  const credit = request.credit;
  if (
    credit.severity !== STATIC_CREDIT.severity ||
    credit.recovery_lag_months !== STATIC_CREDIT.recovery_lag_months ||
    credit.annual_cdr_pct !== STATIC_CREDIT.annual_cdr_pct
  ) {
    throw new ApiRequestError(422, "static_unsupported", "This static site holds the default credit assumptions only.");
  }
  const codeA = staticCode(request.scenario);
  const codeB = staticCode(request.compare_to);
  if (codeA === null || codeA === "none" || codeB === null) {
    throw new ApiRequestError(422, "static_unsupported", "This static site holds flat and parallel-shift scenarios only.");
  }
  const index = await loadStatic<StaticIndex>("index.json");
  if (!index.horizons.includes(request.horizon_months)) {
    throw new ApiRequestError(422, "static_unsupported", `No precomputed horizon of ${request.horizon_months} months.`);
  }
  const pool = encodeURIComponent(request.pool_id);
  const codes = [...new Set([codeA, codeB])].filter((c) => c !== "none");
  const [pairs, ...stored] = await Promise.all([
    loadStatic<Pairs>(`pairs/${pool}/${request.horizon_months}.json`),
    ...codes.map((c) => loadStatic<StoredProjection>(`projections/${pool}/${c}.json`)),
  ]);
  const projections = Object.fromEntries(codes.map((c, i) => [c, stored[i] as StoredProjection]));
  return assemble(index, projections, pairs, request.pool_id, codeA, codeB, request.horizon_months);
}
