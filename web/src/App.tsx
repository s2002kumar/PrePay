import { useEffect, useState } from "react";

import { api } from "./api";
import { href, ROUTES, type Route, useRoute } from "./routing";
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

function useTheme(): [Theme, (theme: Theme) => void] {
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
  return [theme, setTheme];
}

const THEMES: [Theme, string][] = [
  ["system", "Auto"],
  ["light", "Light"],
  ["dark", "Dark"],
];

export function App() {
  const [route, params, navigate] = useRoute();
  const [pools, setPools] = useState<PoolSummary[] | null>(null);
  const [asOfRate, setAsOfRate] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [theme, setTheme] = useTheme();

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
      <header className="topbar">
        <div className="topbar-inner">
          <a
            className="brand"
            href={href(ROUTES.lab)}
            onClick={(e) => {
              e.preventDefault();
              navigate(ROUTES.lab);
            }}
          >
            <svg className="brand-mark" width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" focusable="false">
              <rect x="1" y="1" width="20" height="20" rx="5" fill="currentColor" />
              <path d="M6 15.5V9.5M10 15.5V6.5M14 15.5V11M17.5 15.5v-2.5" stroke="var(--surface)" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <strong>Prepay</strong>
            <span className="brand-sub">Mortgage cash-flow analytics</span>
          </a>
          <nav className="tabs" aria-label="Sections">
            {NAV.map(([r, label]) => (
              <a
                key={r}
                href={href(r)}
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
          <div className="segmented theme" role="group" aria-label="Color theme">
            {THEMES.map(([t, label]) => (
              <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}>
                {label}
              </button>
            ))}
          </div>
        </div>
      </header>
      <div className="notice" role="note">
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
          <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.3" />
          <path d="M8 7.2v4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="8" cy="4.9" r="0.9" fill="currentColor" />
        </svg>
        <span>
          <strong>Fictional portfolios, synthetic-trained model.</strong> Nothing here is Freddie Mac data, a forecast of real
          mortgages, or financial advice. Real-data results are evaluated privately and not published.
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
        valuation ·{" "}
        <a href="https://github.com/s2002kumar/PrePay" rel="noreferrer">
          source, tests and validation reports
        </a>
      </footer>
    </div>
  );
}
