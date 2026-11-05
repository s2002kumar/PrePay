import { featureName, hasRange, outsideFeatures, RULE, type SideView } from "../../derive";
import { modelName, pct, usd, years } from "../../format";
import type { Methodology, RangeValue } from "../../types";
import { VerdictChip } from "./common";
import { display } from "./Composer";

function span(r: RangeValue | undefined, f: (v: number) => string): string {
  return hasRange(r) ? (r.min === r.max ? f(r.min) : `${f(r.min)}–${f(r.max)}`) : "n/a";
}

function SupportCard({ v, warnings }: { v: SideView; warnings: string[] }) {
  const rel = v.out.reliability;
  const h = v.out.summary.horizon_months;
  if (!rel) {
    return (
      <div className="trust-card">
        <p className="muted">No support profile was served with this model.</p>
      </div>
    );
  }
  const features = outsideFeatures(v.out);
  const top = features[0];
  const outsideW = Math.min(100, rel.outside_share * 100);
  const sparseW = Math.min(100 - outsideW, rel.sparse_share * 100);
  const r = v.out.model_range;
  const mine = warnings.filter((w) => w.startsWith(`Scenario ${v.side.toUpperCase()} `));
  return (
    <div className={`trust-card verdict-${rel.verdict}`} data-side={v.side} data-verdict={rel.verdict} data-outside={rel.outside_share} data-sparse={rel.sparse_share}>
      <div className="trust-head">
        <span>
          <i className={`swatch ${v.side}`} aria-hidden="true" /> <strong>{v.side.toUpperCase()}</strong> {display(v.out.label)}
        </span>
        <VerdictChip verdict={rel.verdict} />
      </div>
      <p className="trust-lead">
        <strong>{pct(rel.outside_share)}</strong> of {v.side.toUpperCase()}'s projected balance over months 1–{h} has inputs
        outside the range the model was trained on{top ? `, mostly ${featureName(top[0]).toLowerCase()}` : ""}; another{" "}
        <strong>{pct(rel.sparse_share)}</strong> sits where training data was thin.
      </p>
      <div className="gauge" aria-hidden="true">
        <span className="gauge-fill outside" style={{ width: `${outsideW}%` }} />
        <span className="gauge-fill sparse" style={{ left: `${outsideW}%`, width: `${sparseW}%` }} />
        <span className="tick" style={{ left: `${RULE.extrapolatingOutside * 100}%` }} />
        <span className="tick" style={{ left: `${RULE.extrapolatingOutsidePlusThin * 100}%` }} />
        <span className="tick strong" style={{ left: `${RULE.unsupportedOutside * 100}%` }} />
      </div>
      <div className="gauge-scale" aria-hidden="true">
        <span style={{ left: `${RULE.extrapolatingOutside * 100}%` }}>5%</span>
        <span style={{ left: `${RULE.extrapolatingOutsidePlusThin * 100}%` }}>20%</span>
        <span style={{ left: `${RULE.unsupportedOutside * 100}%` }}>25%</span>
        <span style={{ left: "100%" }}>100%</span>
      </div>
      <div className="legend small" aria-hidden="true">
        <span>
          <i className="key-box outside" /> Outside the range {pct(rel.outside_share)}
        </span>
        <span>
          <i className="key-box sparse" /> Thinly supported {pct(rel.sparse_share)}
        </span>
      </div>
      {features.length > 0 && (
        <div className="features">
          <p className="mini-head">
            Outside the range, by input (a loan-month can be outside on several inputs, so these can add to more than{" "}
            {pct(rel.outside_share)})
          </p>
          <ul className="feature-list">
            {features.map(([k, share]) => (
              <li key={k} data-feature={k} data-share={share}>
                <span>{featureName(k)}</span>
                <span className="feature-bar" aria-hidden="true">
                  <span style={{ width: `${Math.max(1, share * 100)}%` }} />
                </span>
                <span className="num">{pct(share)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {r && (
        <p className="trust-range" data-testid={`range-${v.side}`}>
          <span className="mini-head">Across model families ({r.models.map((m) => modelName(m).split(" ")[0]).join(", ")})</span>
          cash WAL <strong>{span(r.cash_wal_years, (x) => years(x))}</strong> · back within 24 months{" "}
          <strong>{span(r.principal_returned_fraction_24m, (x) => pct(x))}</strong> · still owed at month {h}{" "}
          <strong>{span(r.ending_upb_horizon_usd, usd)}</strong>
        </p>
      )}
      <details className="reasons">
        <summary>Service reasons and warnings, verbatim</summary>
        <ul>
          {rel.reasons.map((x) => (
            <li key={x}>{x}</li>
          ))}
          {mine.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function Trust({ A, B, method, warnings }: { A: SideView; B: SideView | null; method: Methodology | null; warnings: string[] }) {
  const h = A.out.summary.horizon_months;
  const rule = method?.metrics.reliability_verdict?.formula;
  const rangeDef = method?.metrics.model_range?.formula;
  const families = A.out.model_range?.models.map(modelName).join(", ");
  const unattributed = warnings.filter((w) => !/^Scenario [AB] /.test(w));
  return (
    <section className="panel trust" id="trust" aria-labelledby="trust-title" data-testid="trust">
      <header className="panel-head">
        <div>
          <h2 id="trust-title">How far to trust this</h2>
          <p className="sub">
            Does each scenario look like the data the model learned from? Weighted by projected balance over months 1–{h}.
          </p>
        </div>
      </header>
      <div className={`trust-grid${B ? " two" : ""}`}>
        <SupportCard v={A} warnings={warnings} />
        {B && <SupportCard v={B} warnings={warnings} />}
      </div>
      {unattributed.length > 0 && (
        <ul className="sub">
          {unattributed.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      <dl className="rule">
        <dt>Applicability rule (served)</dt>
        <dd data-testid="served-rule">{rule ?? "unavailable"}</dd>
        <dt>Model-family spread</dt>
        <dd>
          {rangeDef ?? "unavailable"}
          {families ? `. Families: ${families}.` : ""}
        </dd>
      </dl>
    </section>
  );
}
