import { useCallback, useEffect, useState } from "react";

import type { ScenarioIn } from "./types";

export const ROUTES = {
  portfolio: "/portfolio",
  lab: "/scenario-lab",
  quality: "/model-quality",
  methodology: "/methodology",
} as const;

export type Route = (typeof ROUTES)[keyof typeof ROUTES];

function currentRoute(): Route {
  const path = window.location.pathname.replace(/\/+$/, "");
  const known = Object.values(ROUTES) as string[];
  return (known.includes(path) ? path : ROUTES.lab) as Route;
}

/** Minimal history-API router: state lives in the URL so every view is link-shareable. */
export function useRoute(): [Route, URLSearchParams, (route: Route, params?: URLSearchParams) => void] {
  const [location, setLocation] = useState(() => ({
    route: currentRoute(),
    params: new URLSearchParams(window.location.search),
  }));
  useEffect(() => {
    const onPop = () =>
      setLocation({ route: currentRoute(), params: new URLSearchParams(window.location.search) });
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = useCallback((route: Route, params?: URLSearchParams) => {
    const query = params && [...params.keys()].length ? `?${params.toString()}` : "";
    window.history.pushState(null, "", `${route}${query}`);
    setLocation({ route, params: params ?? new URLSearchParams() });
  }, []);
  return [location.route, location.params, navigate];
}

export function replaceParams(params: URLSearchParams): void {
  const query = [...params.keys()].length ? `?${params.toString()}` : "";
  window.history.replaceState(null, "", `${window.location.pathname}${query}`);
}

/**
 * Scenario codes used in URLs: "flat", "p-200" (parallel bp), "ramp:5.50:12" (linear ramp from
 * the as-of 30y rate to 5.50% over 12 months, then held), or "none" (no comparison).
 */
export function scenarioFromCode(code: string, asOfRate: number): ScenarioIn | null {
  if (code === "none") return null;
  if (code === "flat") return { kind: "flat" };
  const parallel = /^p(-?\d{1,3})$/.exec(code);
  if (parallel?.[1] !== undefined) return { kind: "parallel", shock_bps: Number(parallel[1]) };
  const ramp = /^ramp:(\d{1,2}(?:\.\d{1,2})?):(\d{1,3})$/.exec(code);
  if (ramp?.[1] !== undefined && ramp[2] !== undefined) {
    const target = Number(ramp[1]);
    const length = Math.min(Math.max(Number(ramp[2]), 1), 120);
    const path = Array.from({ length }, (_, i) => asOfRate + ((target - asOfRate) * (i + 1)) / length);
    return { kind: "custom", path_30y_pct: path.map((r) => Math.round(r * 1000) / 1000) };
  }
  return { kind: "flat" };
}

export function scenarioLabel(code: string): string {
  if (code === "none") return "No comparison";
  if (code === "flat") return "Flat at last observed";
  const parallel = /^p(-?\d{1,3})$/.exec(code);
  if (parallel?.[1] !== undefined) {
    const bp = Number(parallel[1]);
    return `Parallel ${bp > 0 ? "+" : ""}${bp} bp`;
  }
  const ramp = /^ramp:([\d.]+):(\d+)$/.exec(code);
  if (ramp) return `Ramp to ${Number(ramp[1]).toFixed(2)}% over ${ramp[2]} mo`;
  return code;
}
