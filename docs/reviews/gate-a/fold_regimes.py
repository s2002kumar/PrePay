"""Public-rate facts for each ADR 0009 §4 rolling-origin fold (FRED PMMS only; no loan data)."""

import json
import sys
from pathlib import Path

from prepay import periods
from prepay.evaluation.regimes import rate_regime_facts
from prepay.features.machine import RatePath
from prepay.ingest.pmms import parse_fred_csv
from prepay.modeling.experiment import V1_ORIGINS, ExperimentWindows

pmms = Path(sys.argv[1])
series = {}
for name in ("MORTGAGE30US", "MORTGAGE15US"):
    obs = parse_fred_csv((pmms / f"{name}.csv").read_text(encoding="utf-8"), name)
    series[name] = (list(obs.dates), list(obs.rate_pct))
rates = RatePath.from_weekly(*series["MORTGAGE30US"], *series["MORTGAGE15US"])
out = {}
for origin in V1_ORIGINS:
    w = ExperimentWindows.rolling_origin(origin).windows()
    facts = rate_regime_facts(rates, list(w.values()))
    train, ev = facts["windows"]["train"], facts["windows"]["evaluate"]
    outside = ev["months_below_train_min"] + ev["months_above_train_max"]
    rise = ev["max_6m_change_bps"] > train["max_6m_change_bps"]
    fall = ev["min_6m_change_bps"] < train["min_6m_change_bps"]
    out[periods.to_iso(origin)] = {
        "train": train["target_months"],
        "train_range_pct": [train["rate_min_pct"], train["rate_max_pct"]],
        "train_6m_change_bps": [train["min_6m_change_bps"], train["max_6m_change_bps"]],
        "evaluate": ev["target_months"],
        "eval_months": ev["months"],
        "eval_range_pct": [ev["rate_min_pct"], ev["rate_max_pct"]],
        "eval_months_below_train_min": ev["months_below_train_min"],
        "eval_months_above_train_max": ev["months_above_train_max"],
        "eval_6m_change_bps": [ev["min_6m_change_bps"], ev["max_6m_change_bps"]],
        "eval_new_low_months": ev["new_low_months"],
        "train_new_low_months": train["new_low_months"],
        "regime_shift": bool(outside >= 0.25 * ev["months"] or rise or fall),
        "why": [
            r
            for r, ok in (
                ("level outside training range in >=25% of months", outside >= 0.25 * ev["months"]),
                ("6m rise beyond training max", rise),
                ("6m fall beyond training min", fall),
            )
            if ok
        ],
    }
print(json.dumps(out, indent=1))
