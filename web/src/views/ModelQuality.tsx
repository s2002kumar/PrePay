import { useEffect, useState } from "react";

import { api } from "../api";
import { DataTable } from "../components/Figures";
import { LineChart } from "../components/LineChart";
import { num, pct } from "../format";
import type { ModelMetrics, ModelQuality as Quality } from "../types";

const NAMES: Record<string, string> = {
  B0_psa: "B0 PSA benchmark",
  B1_lookup: "B1 age × incentive lookup",
  B2_logistic: "B2 multinomial logistic",
  M1_lightgbm: "M1 LightGBM",
  selected: "Selected (as sealed)",
};

function monthLabel(index: number): string {
  return `${Math.floor(index / 12)}-${String((index % 12) + 1).padStart(2, "0")}`;
}

export function ModelQuality() {
  const [data, setData] = useState<Quality | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.modelQuality().then(setData).catch(() => setError("Model quality data is unavailable."));
  }, []);
  if (error) return <div className="warning" role="alert">{error}</div>;
  if (!data) return <p aria-busy="true">Loading model quality…</p>;

  const selected = data.selection.selected;
  const windows = Object.entries(data.holdout);
  const firstWindow = windows[0];
  const cprSeries = firstWindow
    ? (() => {
        const rows = firstWindow[1].models.selected?.cpr_proxy_monthly ?? [];
        return { labels: rows.map((r) => monthLabel(r.month)), rows };
      })()
    : null;
  const holdoutRows = windows.flatMap(([w, result]) =>
    Object.entries(result.models).map(([model, m]) => ({ key: `${w}-${model}`, window: result.label, model, m })),
  );
  const cohortRows = Object.values(data.cohort_backtests).flatMap((c) =>
    Object.entries(c.horizons ?? {}).map(([h, e]) => ({ key: `${c.t0}-${h}`, t0: c.t0, h, e, loans: c.cohort_loans ?? 0 })),
  );

  return (
    <section aria-labelledby="quality-title">
      <h1 id="quality-title">Model quality</h1>
      <div className="warning" role="note">
        <strong>Synthetic results only.</strong> {data.notice} {data.real_data_status}
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>How the served model was chosen</h2>
        <p className="sub">{data.selection.rule}</p>
        <DataTable
          caption="Validation A log loss (2018 outcomes; lower is better)"
          rows={Object.entries(data.selection.validation_a_log_loss)}
          rowKey={([name]) => name}
          emphasis={([name]) => name === selected}
          columns={[
            { header: "Model", text: true, cell: ([name]) => NAMES[name] ?? name },
            { header: "Log loss", cell: ([, v]) => num(v, 5) },
            { header: "Role", text: true, cell: ([name]) => (name === selected ? "selected" : name === data.selection.best ? "lowest loss" : "") },
          ]}
        />
        <p className="sub" style={{ marginTop: 8 }}>
          Calibration {data.selection.calibration.adopted
            ? `adopted (temperature ${num(data.selection.calibration.temperature ?? 1, 3)})`
            : "not adopted: the cross-fitted temperature did not improve both halves of validation B"}
          .
        </p>
      </div>

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Sealed holdout, evaluated once</h2>
        <p className="sub">One-step monthly outcomes on test windows the model never saw. Every model is shown, including baselines that won.</p>
        <DataTable
          caption="Holdout metrics by window and model (synthetic data)"
          rows={holdoutRows}
          rowKey={(r) => r.key}
          emphasis={(r) => r.model === "selected"}
          columns={[
            { header: "Window", cell: (r) => r.window },
            { header: "Model", text: true, cell: (r) => NAMES[r.model] ?? r.model },
            { header: "Log loss", cell: (r) => num(r.m.log_loss, 4) },
            { header: "Brier", cell: (r) => num(r.m.brier, 4) },
            { header: "Payoff AUROC", cell: (r) => num(r.m.prepay_auroc, 3) },
            { header: "Payoff ECE", cell: (r) => num(r.m.prepay_ece, 4) },
            { header: "CPR proxy MAE", cell: (r) => (r.m.cpr_proxy_mae_pp === null ? "n/a" : `${r.m.cpr_proxy_mae_pp.toFixed(2)} pp`) },
            { header: "Payoffs / credit", cell: (r: { m: ModelMetrics }) => `${r.m.events.prepay} / ${r.m.events.credit}` },
          ]}
        />
        <ul className="sub" style={{ marginTop: 8 }}>
          {windows.map(([w, r]) => (
            <li key={w}>
              {r.label}: beats other baselines {r.flags.beats_baselines ? "yes" : "no"} · log-loss degradation{" "}
              {r.flags.log_loss_degradation ? "flagged" : "not flagged"} · payoff calibration degradation{" "}
              {r.flags.prepay_calibration_degradation ? "flagged" : "not flagged"}
            </li>
          ))}
        </ul>
      </div>

      {cprSeries && cprSeries.rows.length > 1 && firstWindow && (
        <div className="card" style={{ marginBottom: 16 }}>
          <header>
            <div>
              <h2>Payoff speed: model vs observed</h2>
              <p className="sub">{firstWindow[1].label} · balance-weighted full-payoff CPR proxy, % per year</p>
            </div>
          </header>
          <LineChart
            title="Model versus observed full-payoff CPR proxy"
            summary="Monthly full-payoff CPR proxy predicted by the selected model and observed in the synthetic holdout."
            xLabels={cprSeries.labels}
            series={[
              { id: "model", label: "Model (selected)", color: "var(--series-1)", values: cprSeries.rows.map((r) => r.cpr_model * 100) },
              { id: "observed", label: "Observed", color: "var(--series-2)", values: cprSeries.rows.map((r) => r.cpr_observed * 100) },
            ]}
            yFormat={(v) => `${v.toFixed(0)}%`}
            includeZero
          />
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <h2>Cohort run-off vs realized (censor-adjusted)</h2>
        <p className="sub">
          Cumulative share of loans active at t0 that paid off. Realized uses Aalen–Johansen with loan-bootstrap 95%
          intervals. Model shown with realized (hindsight) rates and with rates held flat at t0 (as-of).
        </p>
        <DataTable
          caption="Cumulative payoff incidence (synthetic)"
          rows={cohortRows}
          rowKey={(r) => r.key}
          columns={[
            { header: "Active at", text: true, cell: (r) => r.t0 },
            { header: "Horizon", text: true, cell: (r) => r.h },
            { header: "Loans", cell: (r) => r.loans.toLocaleString("en-US") },
            { header: "Realized", cell: (r) => `${pct(r.e.realized_aalen_johansen_prepay)} [${pct(r.e.realized_prepay_interval.low)}, ${pct(r.e.realized_prepay_interval.high)}]` },
            { header: "Selected, hindsight", cell: (r) => pct(r.e.models.selected?.hindsight_rates?.prepay) },
            { header: "Selected, as-of", cell: (r) => pct(r.e.models.selected?.as_of_flat_rates?.prepay) },
            { header: "B2, hindsight", cell: (r) => pct(r.e.models.B2_logistic?.hindsight_rates?.prepay) },
            { header: "M1, hindsight", cell: (r) => pct(r.e.models.M1_lightgbm?.hindsight_rates?.prepay) },
          ]}
        />
      </div>

      {firstWindow?.[1].models.selected && (
        <div className="card">
          <h2>Payoff reliability (selected model)</h2>
          <p className="sub">Equal-count bins of predicted monthly payoff probability vs observed frequency, {firstWindow[1].label}</p>
          <DataTable
            caption="Reliability bins"
            rows={firstWindow[1].models.selected.prepay_reliability}
            rowKey={(r) => `${r.mean_predicted}-${r.count}`}
            columns={[
              { header: "Mean predicted", cell: (r) => pct(r.mean_predicted, 2) },
              { header: "Observed", cell: (r) => pct(r.observed_rate, 2) },
              { header: "Loan-months", cell: (r) => r.count.toLocaleString("en-US") },
            ]}
          />
        </div>
      )}
    </section>
  );
}
