import { scaleLinear } from "d3-scale";
import type { ReactNode } from "react";

import { type Comparison, direction, hasRange, NEGLIGIBLE_PP, RULE, type SideView } from "../../derive";
import { modelName, pct, signedPp, signedUsd, signedYears, usd, years } from "../../format";
import type { Methodology, RangeValue } from "../../types";
import { Basis, StatusIcon, Term } from "./common";
import { display } from "./Composer";

/** In-page links to a collapsed section open it before the browser scrolls there. */
function openDetails(id: string) {
  const el = document.getElementById(id);
  if (el instanceof HTMLDetailsElement) el.open = true;
}

const familyList = (side: SideView) => side.out.model_range?.models.map((m) => modelName(m).split(" ")[0]).join(", ") ?? "";

function sideNames(views: SideView[]): string {
  return views.map((v) => v.side.toUpperCase()).join(" and ");
}

/** The support status in words, always above the headline: limitations come first. */
function SupportBanner({ A, B }: { A: SideView; B: SideView | null }) {
  const sides = B ? [A, B] : [A];
  if (sides.every((s) => s.verdict === null)) return null;
  const unsupported = sides.filter((s) => s.verdict === "unsupported");
  const extrapolating = sides.filter((s) => s.verdict === "extrapolating");
  const shares = (list: SideView[]) =>
    list
      .map((s) => `${s.side.toUpperCase()}: ${pct(s.out.reliability?.outside_share)} outside, ${pct(s.out.reliability?.sparse_share)} thinly supported`)
      .join("; ");
  if (unsupported.length) {
    return (
      <div className="banner crit" role="note" data-testid="support-banner">
        <StatusIcon tone="crit" />
        <p>
          <strong>
            {sideNames(unsupported)} {unsupported.length > 1 ? "are" : "is"} unsupported.
          </strong>{" "}
          At least {pct(RULE.unsupportedOutside, 0)} of {unsupported.length > 1 ? "each one's" : "its"} projected balance has
          inputs outside the model's training range ({shares(unsupported)}). The headline is the spread across model
          families, not a single estimate. <a href="#trust">How far to trust this</a>
        </p>
      </div>
    );
  }
  if (extrapolating.length) {
    return (
      <div className="banner warn" role="note" data-testid="support-banner">
        <StatusIcon tone="warn" />
        <p>
          <strong>
            {sideNames(extrapolating)} {extrapolating.length > 1 ? "are" : "is"} extrapolating.
          </strong>{" "}
          Part of the projected balance lies outside, or at the thin edge of, the training data ({shares(extrapolating)}).
          Read the point values together with the model-family spread. <a href="#trust">How far to trust this</a>
        </p>
      </div>
    );
  }
  return (
    <div className="banner good" role="note" data-testid="support-banner">
      <StatusIcon tone="good" />
      <p>
        <strong>Supported.</strong> The projected inputs stay inside the model's training data
        {B ? " for both scenarios" : ""}. <a href="#trust">How far to trust this</a>
      </p>
    </div>
  );
}

function rangeText(r: RangeValue | undefined, f: (v: number) => string): string {
  return hasRange(r) ? `${f(r.min)}–${f(r.max)}` : "n/a";
}

const yrs = (v: number) => v.toFixed(2);

function Headline({ A, B, cmp }: { A: SideView; B: SideView | null; cmp: Comparison | null }) {
  const rangeFirst = A.rangeFirst || !!B?.rangeFirst;
  if (rangeFirst) {
    const sides = B ? [A, B] : [A];
    return (
      <div className="headline range" data-testid="headline" data-mode="range">
        <p className="lead">Cash weighted-average life, as a range across model families</p>
        <div className="range-lines">
          {sides.map((s) => (
            <p key={s.side} className="range-line">
              <i className={`swatch ${s.side}`} aria-hidden="true" />
              <span className="range-side">{s.side.toUpperCase()}</span>
              <span className="big" data-side={s.side} data-min={s.out.model_range?.cash_wal_years.min ?? ""} data-max={s.out.model_range?.cash_wal_years.max ?? ""}>
                {rangeText(s.out.model_range?.cash_wal_years, yrs)} yr
              </span>
              {s.rangeFirst && <span className="chip crit small">read the range</span>}
            </p>
          ))}
        </div>
        <p className="support-text">
          The fitted model families ({familyList(A)}) disagree on this scenario, so no single number is offered as the
          answer. Point values from the served model ({sides.map((s) => `${s.side.toUpperCase()} ${years(s.out.summary.cash_wal_years)}`).join(", ")})
          stay visible below, marked as points.
        </p>
      </div>
    );
  }
  if (!B || !cmp) {
    return (
      <div className="headline" data-testid="headline" data-mode="single">
        <p className="lead">Under A, principal comes back over</p>
        <p className="big" data-raw={A.out.summary.cash_wal_years ?? ""}>
          {years(A.out.summary.cash_wal_years).replace(" yr", " years")}
        </p>
        <p className="lead">on average (cash weighted-average life, full life)</p>
      </div>
    );
  }
  const dir = direction(cmp.walYears);
  const magnitude = cmp.walYears === null ? "n/a" : Math.abs(cmp.walYears).toFixed(2);
  return (
    <div className="headline" data-testid="headline" data-mode="point">
      <p className="lead">Under B, principal comes back</p>
      <p className="big" data-raw={cmp.walYears ?? ""}>
        {dir === "same" ? "about as quickly" : `${magnitude} years ${dir}`}
      </p>
      <p className="lead">
        {dir === "same" ? "as under A" : "on average than under A"}
        <span className="muted"> · cash weighted-average life, full life</span>
      </p>
      <p className="support-text">
        Cash WAL {years(B.out.summary.cash_wal_years)} under B ({display(B.out.label)}) vs{" "}
        {years(A.out.summary.cash_wal_years)} under A ({display(A.out.label)}). B − A = {signedYears(cmp.walYears)}, the served
        A − B difference with its sign flipped.
      </p>
    </div>
  );
}

function more(v: number, negligible: number, up: string, down: string): string {
  return Math.abs(v) < negligible ? "about the same" : v > 0 ? up : down;
}

/** The financial consequence in one paragraph, built from the same served deltas. */
function Consequence({ A, cmp }: { A: SideView; cmp: Comparison }) {
  const h = A.out.summary.horizon_months;
  const dir = direction(cmp.walYears);
  const parts: ReactNode[] = [];
  if (cmp.returned24Pp !== null) {
    const usd24 = (cmp.returned24Pp / 100) * A.b0;
    parts.push(
      Math.abs(cmp.returned24Pp) < NEGLIGIBLE_PP ? (
        <>Within 24 months both return about the same share of today's balance.</>
      ) : (
        <>
          Within 24 months B returns <strong>{signedPp(cmp.returned24Pp).replace(/^[+−]/, "")}</strong>{" "}
          {cmp.returned24Pp > 0 ? "more" : "less"} of today's balance ({usd(Math.abs(usd24))}).
        </>
      ),
    );
  }
  if (cmp.endingUsd !== null && cmp.interestUsd !== null) {
    parts.push(
      <>
        {" "}
        At month {h} it has <strong>{usd(Math.abs(cmp.endingUsd))}</strong> {more(cmp.endingUsd, 0.5, "more", "less")}{" "}
        principal still owed and over months 1–{h} accrues <strong>{usd(Math.abs(cmp.interestUsd))}</strong>{" "}
        {more(cmp.interestUsd, 0.5, "more", "less")} contractual interest.
      </>,
    );
  }
  const why =
    dir === "sooner"
      ? "Faster repayment hands capital back sooner and shortens the time it earns interest."
      : dir === "later"
        ? "Slower repayment keeps capital outstanding longer, so more interest accrues on it."
        : "";
  return (
    <p className="consequence" data-testid="consequence">
      <span className="kicker">Why it matters</span>
      {parts}
      {why && ` ${why}`} Amounts are undiscounted; nothing here prices or values these cash flows.
    </p>
  );
}

// ------------------------------------------------------------------ A vs B dot comparisons

interface Bell {
  key: string;
  metric: string; // methodology key for the definition
  title: string;
  basis: string;
  unit: string;
  a: number | null;
  b: number | null;
  ra?: RangeValue | undefined;
  rb?: RangeValue | undefined;
  delta: number | null;
  deltaText: string;
  domain: [number, number];
  fmt: (v: number) => string;
  axis: (v: number) => string;
}

function niceTop(values: (number | null | undefined)[], floor = 0): number {
  const top = Math.max(floor, ...values.filter((v): v is number => v !== null && v !== undefined && Number.isFinite(v)));
  return scaleLinear().domain([0, top]).nice(4).domain()[1] ?? top;
}

function Dumbbell({ bell, A, B, method }: { bell: Bell; A: SideView; B: SideView | null; method: Methodology | null }) {
  const [lo, hi] = bell.domain;
  const at = (v: number) => `${Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))}%`;
  const spread = (side: "a" | "b", r: RangeValue | undefined) =>
    hasRange(r) ? (
      <span
        className={`spread ${side}`}
        style={{ left: at(r.min), width: `calc(${at(r.max)} - ${at(r.min)})` }}
        title={`${side.toUpperCase()} model-family spread ${bell.fmt(r.min)}–${bell.fmt(r.max)}`}
      />
    ) : null;
  const dot = (side: "a" | "b", v: number | null, view: SideView | null) =>
    v === null || !view ? null : (
      <span className={`dot ${side}${view.rangeFirst ? " hollow" : ""}`} style={{ left: at(v) }}>
        <span className={`dot-label ${side === "b" ? "above" : "below"}`}>
          {view.rangeFirst ? "point " : ""}
          {bell.fmt(v)}
        </span>
      </span>
    );
  return (
    <div
      className="bell"
      data-metric={bell.key}
      data-a={bell.a ?? ""}
      data-b={bell.b ?? ""}
      data-delta={bell.delta ?? ""}
      role="group"
      aria-label={`${bell.title}: A ${bell.a === null ? "n/a" : bell.fmt(bell.a)}${B && bell.b !== null ? `, B ${bell.fmt(bell.b)}, B − A ${bell.deltaText}` : ""}`}
    >
      <div className="bell-head">
        <Term method={method} metric={bell.metric}>
          <span className="bell-title">{bell.title}</span>
        </Term>
        <Basis>{bell.basis}</Basis>
        {B && (
          <span className="bell-delta">
            <span className="muted">B − A</span> <strong>{bell.deltaText}</strong>
          </span>
        )}
      </div>
      <div className="bell-track" aria-hidden="true">
        <span className="rail" />
        {spread("a", bell.ra)}
        {B && spread("b", bell.rb)}
        {B && bell.a !== null && bell.b !== null && (
          <span className="link" style={{ left: at(Math.min(bell.a, bell.b)), width: `calc(${at(Math.max(bell.a, bell.b))} - ${at(Math.min(bell.a, bell.b))})` }} />
        )}
        {dot("a", bell.a, A)}
        {dot("b", bell.b, B)}
      </div>
      <div className="bell-axis" aria-hidden="true">
        <span>{bell.axis(lo)}</span>
        <span className="unit">{bell.unit}</span>
        <span>{bell.axis(hi)}</span>
      </div>
    </div>
  );
}

export function Outcome({ A, B, cmp, method }: { A: SideView; B: SideView | null; cmp: Comparison | null; method: Methodology | null }) {
  const h = A.out.summary.horizon_months;
  const sa = A.out.summary;
  const sb = B?.out.summary;
  const ra = A.out.model_range;
  const rb = B?.out.model_range;
  const walTop = niceTop([sa.cash_wal_years, sb?.cash_wal_years, ra?.cash_wal_years.max, rb?.cash_wal_years.max], 5);
  const intTop = niceTop([sa.contractual_interest_accrued_horizon_usd, sb?.contractual_interest_accrued_horizon_usd]);
  const bells: Bell[] = [
    {
      key: "cash_wal",
      metric: "cash_wal_years",
      title: "Cash weighted-average life",
      basis: "full life",
      unit: "years",
      a: sa.cash_wal_years,
      b: sb?.cash_wal_years ?? null,
      ra: ra?.cash_wal_years,
      rb: rb?.cash_wal_years,
      delta: cmp?.walYears ?? null,
      deltaText: signedYears(cmp?.walYears),
      domain: [0, walTop],
      fmt: years,
      axis: (v) => `${v} yr`,
    },
    {
      key: "returned_24m",
      metric: "cumulative_principal_returned_fraction",
      title: "Principal back within 24 months",
      basis: "months 1–24",
      unit: "% of today's balance",
      a: sa.principal_returned_fraction_24m,
      b: sb?.principal_returned_fraction_24m ?? null,
      ra: ra?.principal_returned_fraction_24m,
      rb: rb?.principal_returned_fraction_24m,
      delta: cmp?.returned24Pp ?? null,
      deltaText: signedPp(cmp?.returned24Pp),
      domain: [0, 1],
      fmt: (v) => pct(v),
      axis: (v) => pct(v, 0),
    },
    {
      key: "ending_upb",
      metric: "ending_upb_usd",
      title: `Still owed at month ${h}`,
      basis: `at month ${h}`,
      unit: `USD, of ${usd(A.b0)} today`,
      a: sa.ending_upb_horizon_usd,
      b: sb?.ending_upb_horizon_usd ?? null,
      ra: ra?.ending_upb_horizon_usd,
      rb: rb?.ending_upb_horizon_usd,
      delta: cmp?.endingUsd ?? null,
      deltaText: signedUsd(cmp?.endingUsd),
      domain: [0, A.b0],
      fmt: usd,
      axis: usd,
    },
    {
      key: "interest",
      metric: "contractual_interest_accrued_usd",
      title: "Contractual interest accrued",
      basis: `months 1–${h}`,
      unit: "USD, undiscounted",
      a: sa.contractual_interest_accrued_horizon_usd,
      b: sb?.contractual_interest_accrued_horizon_usd ?? null,
      delta: cmp?.interestUsd ?? null,
      deltaText: signedUsd(cmp?.interestUsd),
      domain: [0, intTop],
      fmt: usd,
      axis: usd,
    },
  ];
  const anyRange = !!(ra || rb);
  return (
    <section className="outcome panel" aria-labelledby="outcome-title">
      <div className="outcome-main">
        <h2 id="outcome-title" className="kicker">
          The outcome{B ? " · B against A" : ""}
        </h2>
        <SupportBanner A={A} B={B} />
        <Headline A={A} B={B} cmp={cmp} />
        {B && cmp && !(A.rangeFirst || B.rangeFirst) && <Consequence A={A} cmp={cmp} />}
        <p className="outcome-links">
          <a href="#full-table" onClick={() => openDetails("full-table")}>
            Full comparison table
          </a>
          <a href="#ledger" onClick={() => openDetails("ledger")}>
            Monthly ledger
          </a>
          <a href="#trust">How far to trust this</a>
        </p>
      </div>
      <div className="outcome-bells" data-testid="bells">
        <div className="bells-head">
          <h3>{B ? "A and B, side by side" : "Scenario A"}</h3>
          <div className="legend" aria-hidden="true">
            <span>
              <i className="swatch a" /> A · {display(A.out.label)}
            </span>
            {B && (
              <span>
                <i className="swatch b" /> B · {display(B.out.label)}
              </span>
            )}
            {anyRange && (
              <span>
                <i className="spread-key" /> Model-family spread
              </span>
            )}
          </div>
        </div>
        {bells.map((bell) => (
          <Dumbbell key={bell.key} bell={bell} A={A} B={B} method={method} />
        ))}
        <p className="footnote">
          {B && <>B − A is the served A − B difference with its sign flipped. </>}
          {anyRange && (
            <>
              Hatched brackets span the results of the fitted model families ({familyList(A)}) for the same scenario: how much
              the models disagree, <strong>not a confidence interval</strong>.{" "}
            </>
          )}
          {(A.rangeFirst || B?.rangeFirst) && <>Hollow dots are point values shown for reference only.</>}
        </p>
      </div>
    </section>
  );
}

