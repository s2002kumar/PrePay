import { useEffect, useState } from "react";

import { api } from "../api";
import { DataTable } from "../components/Figures";
import type { Health, Methodology as Method } from "../types";

const REPO = "https://github.com/s2002kumar/PrePay";

export function Methodology() {
  const [method, setMethod] = useState<Method | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    Promise.all([api.methodology(), api.health()])
      .then(([m, h]) => {
        setMethod(m);
        setHealth(h);
      })
      .catch(() => setError("Methodology data is unavailable."));
  }, []);
  if (error) return <div className="warning" role="alert">{error}</div>;
  if (!method || !health) return <p aria-busy="true">Loading methodology…</p>;
  return (
    <section aria-labelledby="method-title">
      <h1 id="method-title">Methodology &amp; status</h1>
      <p className="lede">{method.question}</p>

      <div className="grid-2" style={{ marginBottom: 16 }}>
        <div className="card">
          <h2>Status</h2>
          <dl className="defs">
            <dt>Public demo</dt>
            <dd>Running · data class {health.data_class} · artifacts {health.artifact_class}</dd>
            <dt>Served model</dt>
            <dd>{health.model} (run {method.model.run_id}, trained on {method.model.trained_on})</dd>
            <dt>Real-data validation</dt>
            <dd>Blocked: no lawfully obtained Freddie Mac files have been evaluated</dd>
            <dt>Projection latency</dt>
            <dd>
              {health.project_latency_ms
                ? `p50 ${health.project_latency_ms.p50.toFixed(0)} ms · p95 ${health.project_latency_ms.p95.toFixed(0)} ms (${health.project_latency_ms.count} recent requests, this instance)`
                : "no requests sampled yet"}
            </dd>
            <dt>Independent review</dt>
            <dd>None yet; all reviews so far are self-review by the implementing agent</dd>
          </dl>
        </div>
        <div className="card">
          <h2>What is predicted</h2>
          <dl className="defs">
            {Object.entries(method.outcomes).map(([k, v]) => (
              <div key={k} style={{ display: "contents" }}>
                <dt>{k}</dt>
                <dd>{v}</dd>
              </div>
            ))}
          </dl>
          <p className="sub" style={{ marginTop: 8 }}>{method.feature_timing}.</p>
        </div>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Pipeline</h2>
        <ol className="sub">
          <li>Lock source files by SHA-256; stream raw archives into bronze Parquet with line-level lineage.</li>
          <li>dbt: type fields, map documented sentinels to missing, quarantine data problems, date each loan's first event.</li>
          <li>Build at-risk loan-months with features known at t-1; label P / C / A.</li>
          <li>Fit B0–B2 baselines and LightGBM on outcomes to 2017; select on 2018, calibrate on 2019.</li>
          <li>Seal the run; evaluate 2020+ holdouts once; publish the first report as is.</li>
          <li>Project pools: scenario rate path → features → model hazards → audited cash-flow ledger.</li>
        </ol>
        <p className="sub">
          The public demo runs this pipeline on fictional data only. Source:{" "}
          <a href={REPO} rel="noreferrer">GitHub repository</a> · <a href={`${REPO}/blob/main/docs/STATUS.md`} rel="noreferrer">status ledger</a> ·{" "}
          <a href={`${REPO}/blob/main/docs/VALIDATION_REPORT.md`} rel="noreferrer">validation report</a>
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Every number, defined</h2>
        <DataTable
          caption="Displayed metrics with units and formulas"
          rows={Object.entries(method.metrics)}
          rowKey={([k]) => k}
          columns={[
            { header: "Metric", text: true, cell: ([, d]) => d.label },
            { header: "Unit", text: true, cell: ([, d]) => d.unit },
            { header: "Definition", text: true, cell: ([, d]) => <span style={{ whiteSpace: "normal" }}>{d.formula}</span> },
          ]}
        />
      </div>

      <div className="grid-2">
        <div className="card">
          <h2>Model features</h2>
          <DataTable
            caption="Features (all as of the end of the prior month)"
            rows={method.features}
            rowKey={(f) => f.name}
            columns={[
              { header: "Feature", text: true, cell: (f) => f.name },
              { header: "Source", text: true, cell: (f) => f.source },
              { header: "Description", text: true, cell: (f) => <span style={{ whiteSpace: "normal" }}>{f.description}</span> },
            ]}
          />
        </div>
        <div className="card">
          <h2>Limitations</h2>
          <ul className="sub">
            {method.limitations.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          <h3>Data permissions</h3>
          <p className="sub">{method.data_permissions}</p>
        </div>
      </div>
    </section>
  );
}
