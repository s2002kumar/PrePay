import { useEffect, useState } from "react";

import { api } from "./api";
import { ROUTES, type Route, useRoute } from "./routing";
import type { PoolSummary } from "./types";
import { Methodology } from "./views/Methodology";
import { ModelQuality } from "./views/ModelQuality";
import { PortfolioExplorer } from "./views/PortfolioExplorer";
import { ScenarioLab } from "./views/ScenarioLab";

const NAV: [Route, string][] = [
  [ROUTES.portfolio, "Portfolio"],
  [ROUTES.lab, "Scenario Lab"],
  [ROUTES.quality, "Model quality"],
  [ROUTES.methodology, "Methodology & status"],
];

type Theme = "system" | "light" | "dark";

function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      const stored = window.localStorage.getItem("prepay-theme");
      return stored === "light" || stored === "dark" ? stored : "system";
    } catch {
      return "system";
    }
  });
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      window.localStorage.setItem("prepay-theme", theme);
    } catch {
      // storage unavailable (private mode): the theme still applies for this visit
    }
  }, [theme]);
  const cycle = () => setTheme((t) => (t === "system" ? "light" : t === "light" ? "dark" : "system"));
  return [theme, cycle];
}

export function App() {
  const [route, params, navigate] = useRoute();
  const [pools, setPools] = useState<PoolSummary[] | null>(null);
  const [asOfRate, setAsOfRate] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, cycleTheme] = useTheme();

  useEffect(() => {
    Promise.all([api.pools(), api.scenarios()])
      .then(([p, s]) => {
        setPools(p.pools);
        setAsOfRate(s.as_of_rate_30y_pct);
      })
      .catch(() => setError("The demo service is unavailable. Try again shortly."));
  }, []);

  useEffect(() => {
    const label = NAV.find(([r]) => r === route)?.[1] ?? "Prepay";
    document.title = `${label} · Prepay (fictional demo)`;
  }, [route]);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <header className="top">
        <div className="brand">
          <strong>Prepay</strong>
          <span>Mortgage cash-flow intelligence</span>
        </div>
        <nav className="tabs" aria-label="Sections">
          {NAV.map(([r, label]) => (
            <a
              key={r}
              href={r}
              aria-current={route === r ? "page" : undefined}
              onClick={(e) => {
                e.preventDefault();
                navigate(r);
              }}
            >
              {label}
            </a>
          ))}
        </nav>
        <button type="button" onClick={cycleTheme} aria-label={`Color theme: ${theme}. Change theme`}>
          Theme: {theme}
        </button>
      </header>
      <div className="notice" role="note">
        <span aria-hidden="true">ⓘ</span>
        <span>
          <strong>Fictional portfolios, synthetic-trained model.</strong> Nothing here is Freddie Mac data, a forecast of real
          mortgages, or financial advice. Real-data validation is pending.
        </span>
      </div>
      <main id="main" tabIndex={-1}>
        {error && <div className="warning" role="alert">{error}</div>}
        {!error && (!pools || asOfRate === null) && <p aria-busy="true">Loading the demo…</p>}
        {pools && asOfRate !== null && (
          <>
            {route === ROUTES.portfolio && <PortfolioExplorer pools={pools} initial={params.get("pool")} navigate={navigate} />}
            {route === ROUTES.lab && <ScenarioLab pools={pools} asOfRate={asOfRate} params={params} />}
            {route === ROUTES.quality && <ModelQuality />}
            {route === ROUTES.methodology && <Methodology />}
          </>
        )}
      </main>
      <footer className="foot">
        Prepay research demo · all portfolios fictional · rate paths are hypothetical, not forecasts · no discounting or
        valuation.
      </footer>
    </div>
  );
}
