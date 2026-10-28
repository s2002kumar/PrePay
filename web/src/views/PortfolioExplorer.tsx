import { useState } from "react";

import { BarList, StatTile } from "../components/Figures";
import { months, pct, ratePct, usd } from "../format";
import { ROUTES, type Route } from "../routing";
import type { PoolSummary } from "../types";

const LABELS: Record<string, string> = {
  P: "Purchase", C: "Cash-out refinance", N: "No-cash-out refinance", R: "Refinance (unspecified)",
  I: "Investment", S: "Second home", unknown: "Not available",
};

function mix(record: Record<string, number>, occupancy = false): [string, number][] {
  return Object.entries(record)
    .map(([k, v]): [string, number] => [occupancy && k === "P" ? "Primary residence" : (LABELS[k] ?? k), v])
    .sort((a, b) => b[1] - a[1]);
}

export function PortfolioExplorer({ pools, initial, navigate }: {
  pools: PoolSummary[];
  initial: string | null;
  navigate: (route: Route, params?: URLSearchParams) => void;
}) {
  const [selected, setSelected] = useState(initial ?? pools[0]?.pool_id ?? "");
  const pool = pools.find((p) => p.pool_id === selected) ?? pools[0];
  if (!pool) return <p>No pools available.</p>;
  return (
    <section aria-labelledby="portfolio-title">
      <h1 id="portfolio-title">Portfolio Explorer</h1>
      <p className="lede">
        Four <strong>fictional</strong> fixed-rate pools, generated in code from seeded distributions. They contain no
        Freddie Mac record. Balances are as of {pool.as_of}.
      </p>
      <div className="grid-3" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 2fr)" }}>
        <div className="pool-list" role="group" aria-label="Choose a fictional pool">
          {pools.map((p) => (
            <button
              key={p.pool_id}
              type="button"
              className="pool-option"
              aria-pressed={p.pool_id === pool.pool_id}
              onClick={() => setSelected(p.pool_id)}
            >
              <strong>{p.name}</strong>
              <small>
                {usd(p.current_upb_usd)} · WAC {ratePct(p.wac_pct)} · {p.loans.toLocaleString("en-US")} loans
              </small>
            </button>
          ))}
        </div>
        <div className="stack">
          <div className="card">
            <header>
              <h2>{pool.name}</h2>
              <span className="badge">fictional</span>
            </header>
            <p className="sub" style={{ marginBottom: 12 }}>{pool.description}</p>
            <div className="tiles" style={{ marginBottom: 0 }}>
              <StatTile label="Current balance" value={usd(pool.current_upb_usd)} detail={`${pool.loans.toLocaleString("en-US")} loans`} />
              <StatTile label="Weighted-average coupon" value={ratePct(pool.wac_pct)} detail="contract note rate" />
              <StatTile label="Weighted-average age" value={months(pool.wala_months)} detail={`${months(pool.wam_months)} remaining`} />
              <StatTile label="Average loan size" value={usd(pool.average_loan_size_usd)} detail="current balance" />
              <StatTile label="Credit score / LTV" value={`${pool.wa_credit_score?.toFixed(0) ?? "n/a"} / ${ratePct(pool.wa_original_ltv_pct, 0)}`} detail="balance-weighted, at origination" />
            </div>
          </div>
          <div className="grid-2">
            <div className="card">
              <h3>Coupon distribution</h3>
              <p className="sub" style={{ marginBottom: 8 }}>share of balance per 25 bp note-rate bucket</p>
              <BarList
                label="Coupon distribution"
                items={pool.note_rate_histogram
                  .filter((b) => b.upb_share > 0)
                  .map((b): [string, number] => [`${b.low_pct.toFixed(2)}–${b.high_pct.toFixed(2)}%`, b.upb_share])}
                format={(v) => pct(v, 0)}
              />
            </div>
            <div className="card">
              <h3>Composition</h3>
              <p className="sub" style={{ marginBottom: 8 }}>share of balance</p>
              <div className="stack" style={{ gap: 12 }}>
                <BarList label="Term" items={mix(pool.term_mix)} format={(v) => pct(v, 0)} />
                <BarList label="Loan purpose" items={mix(pool.purpose_mix)} format={(v) => pct(v, 0)} />
                <BarList label="Occupancy" items={mix(pool.occupancy_mix, true)} format={(v) => pct(v, 0)} />
                <BarList label="Region" items={mix(pool.region_mix)} format={(v) => pct(v, 0)} />
              </div>
            </div>
          </div>
          <div>
            <button
              type="button"
              className="primary"
              onClick={() => navigate(ROUTES.lab, new URLSearchParams({ pool: pool.pool_id }))}
            >
              Project this pool in the Scenario Lab
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
