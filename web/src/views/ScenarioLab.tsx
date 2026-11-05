import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, ApiRequestError } from "../api";
import { clampMonth, compare, sideView } from "../derive";
import { modelName, pct, ratePct, usd } from "../format";
import { href, replaceParams, ROUTES, scenarioFromCode } from "../routing";
import type { Methodology, PoolSummary, ProjectionResponse } from "../types";
import { Composer } from "./lab/Composer";
import { Composition } from "./lab/Composition";
import { Drivers } from "./lab/Drivers";
import { Outcome } from "./lab/Outcome";
import { FullTable, Ledger } from "./lab/Tables";
import { Inspector, PrincipalChart } from "./lab/Timeline";
import { Trust } from "./lab/Trust";

interface Props {
  pools: PoolSummary[];
  asOfRate: number;
  params: URLSearchParams;
}

/** The served model and the assumptions every number depends on, always visible. */
function ModelContext({ result, asOf, asOfRate, method }: { result: ProjectionResponse; asOf: string; asOfRate: number; method: Methodology | null }) {
  const a = result.assumptions;
  return (
    <section className="context" aria-labelledby="context-title">
      <div className="panel" role="region" aria-label="Active model and assumptions">
        <h2 id="context-title">About these numbers</h2>
        <dl className="defs compact">
          <dt>Active model</dt>
          <dd>
            <strong>{modelName(result.model)}</strong> · trained on synthetic data
            {method ? ` (run ${method.model.run_id})` : ""} · <a href={href(ROUTES.quality)}>how it was chosen</a>
          </dd>
          <dt>As of</dt>
          <dd>
            {asOf} · last observed 30-year rate {ratePct(asOfRate)} (synthetic history)
          </dd>
          <dt>Credit exits</dt>
          <dd>
            {String(a.credit_exits)}; severity {pct(Number(a.credit_severity), 0)}, recovery after {String(a.recovery_lag_months)} months
          </dd>
          <dt>Conventions</dt>
          <dd>rates act from month 2 · note rates fixed · curtailments not modeled · undiscounted</dd>
        </dl>
        <details className="drawer">
          <summary>Every served assumption</summary>
          <dl className="defs compact">
            {Object.entries(a).map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{k.replaceAll("_", " ")}</dt>
                <dd>{String(v)}</dd>
              </div>
            ))}
          </dl>
        </details>
      </div>
      {method && (
        <div className="panel">
          <h2>Limitations</h2>
          <ul className="limits">
            {method.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <p className="sub">
            <a href={href(ROUTES.methodology)}>Methodology, pipeline and every formula</a>
          </p>
        </div>
      )}
    </section>
  );
}

export function ScenarioLab({ pools, asOfRate, params }: Props) {
  const [poolId, setPoolId] = useState(params.get("pool") ?? "fictional-2023-high-coupon");
  const [codeA, setCodeA] = useState(params.get("a") ?? "flat");
  const [codeB, setCodeB] = useState(params.get("b") ?? "p-100");
  const [horizon, setHorizon] = useState(Number(params.get("h") ?? 120));
  const [severity, setSeverity] = useState(Number(params.get("sev") ?? 0.35));
  const [lag, setLag] = useState(Number(params.get("lag") ?? 12));
  const [cdr, setCdr] = useState(params.get("cdr") ?? "");
  const [result, setResult] = useState<ProjectionResponse | null>(null);
  const [method, setMethod] = useState<Methodology | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [cursor, setCursor] = useState(24);
  const pending = useRef<AbortController | null>(null);

  useEffect(() => {
    api.methodology().then(setMethod).catch(() => setMethod(null));
  }, []);

  const request = useMemo(() => ({
    pool_id: poolId,
    scenario: scenarioFromCode(codeA, asOfRate) ?? { kind: "flat" as const },
    compare_to: scenarioFromCode(codeB, asOfRate),
    horizon_months: horizon,
    credit: { severity, recovery_lag_months: lag, annual_cdr_pct: cdr === "" ? null : Number(cdr) },
  }), [poolId, codeA, codeB, horizon, severity, lag, cdr, asOfRate]);

  useEffect(() => {
    const next = new URLSearchParams({
      pool: poolId, a: codeA, b: codeB, h: String(horizon), sev: String(severity), lag: String(lag),
    });
    if (cdr !== "") next.set("cdr", cdr);
    replaceParams(next);
    const timer = window.setTimeout(() => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      setLoading(true);
      api.project(request, controller.signal)
        .then((response) => {
          setResult(response);
          setError(null);
        })
        .catch((reason: unknown) => {
          if (controller.signal.aborted) return;
          setError(reason instanceof ApiRequestError ? reason.message : "The projection service is unavailable.");
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }, 200);
    return () => window.clearTimeout(timer);
  }, [request, poolId, codeA, codeB, horizon, severity, lag, cdr]);

  const pool = pools.find((p) => p.pool_id === poolId);
  const A = useMemo(() => (result ? sideView("a", result.a) : null), [result]);
  const B = useMemo(() => (result?.b ? sideView("b", result.b) : null), [result]);
  const cmp = useMemo(() => (result ? compare(result) : null), [result]);
  const n = A?.months ?? 1;
  const month = clampMonth(cursor, n);
  const label = useCallback(
    (m: number) => `Month ${m} · ${result?.a.monthly[m - 1]?.month ?? ""}`,
    [result],
  );
  const shared = { month, set: (m: number) => setCursor(clampMonth(m, n)), label };
  const timing = String(result?.assumptions.scenario_timing ?? "");

  return (
    <section aria-labelledby="lab-title" className="lab">
      <header className="page-head">
        <h1 id="lab-title">Scenario Lab</h1>
        <p className="lede">
          How quickly does a mortgage pool pay back its principal when interest rates move? Pick two hypothetical rate paths,
          A and B, and compare what a prepayment model projects: when the money comes back, how much is still owed, and how
          far to trust the answer.
        </p>
        {pool && (
          <p className="facts">
            {pool.name} · {pool.loans.toLocaleString("en-US")} loans · {usd(pool.current_upb_usd)} today · WAC{" "}
            {ratePct(pool.wac_pct)} · as of {pool.as_of} · fictional portfolio, synthetic-trained model · not investment advice
          </p>
        )}
      </header>

      <Composer
        pools={pools}
        poolId={poolId}
        onPool={setPoolId}
        codeA={codeA}
        codeB={codeB}
        onA={setCodeA}
        onB={setCodeB}
        horizon={horizon}
        onHorizon={setHorizon}
        servedMonths={A?.months ?? null}
        asOfRate={asOfRate}
        verdictA={A?.verdict ?? null}
        verdictB={B?.verdict ?? null}
        credit={{ severity, lag, cdr, setSeverity, setLag, setCdr }}
      />

      {error && (
        <div className="banner crit" role="alert">
          <p>{error}</p>
        </div>
      )}
      {!result && !error && <p aria-busy="true">Projecting the pool…</p>}

      {result && A && (
        <div className={`lab-body${loading ? " is-loading" : ""}`} aria-busy={loading}>
          <Outcome A={A} B={B} cmp={cmp} method={method} />
          <FullTable A={A} B={B} cmp={cmp} />
          <div className="timeline-grid">
            <PrincipalChart A={A} B={B} cursor={shared} method={method} />
            <Inspector A={A} B={B} cursor={shared} method={method} timing={timing} />
          </div>
          <Drivers A={A} B={B} cursor={shared} method={method} pool={pool} timing={timing} />
          <Composition A={A} B={B} />
          <Trust A={A} B={B} method={method} warnings={result.warnings} />
          <Ledger A={A} B={B} cursor={shared} />
          <ModelContext result={result} asOf={pool?.as_of ?? result.as_of} asOfRate={asOfRate} method={method} />
        </div>
      )}
    </section>
  );
}
