"""Failure-hypothesis diagnostics (RELIABILITY_PLAN §6, ADR 0009 §6).

- **D1 era encoding.** How well each feature, alone, separates pre-2009 from later training rows
  (rank AUC, direction-free). A feature with AUC ≥ 0.8 can act as an era proxy.
- **D2 economic probes.** Partial dependence and ICE on reference rows for:
  - incentive;
  - **rate level at fixed incentive** (the note rate and the whole rate history move together);
  - burnout, age, seasonality and six-month rate change;
  - nominal loan size.

  Probes are coherent. Moving the market rate also moves incentive and the derived features
  exactly as a real rate path would, so a model is never scored on impossible rows.
- **D3 support maps.** :class:`prepay.reliability.support.SupportProfile` per window, from
  feature values only. No outcome is read.
- **D6 / D7 stability.** Disjoint loan samples or LightGBM seeds, refitted on the same windows.
  Validation log loss and the incentive response are compared across refits.

Flags are review triggers, never automatic model changes.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from prepay import periods
from prepay.arrays import FloatArray
from prepay.evaluation.cohort import Predictor
from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_NUMERIC
from prepay.features.spec import NUMERIC
from prepay.finance.amortization import level_payment
from prepay.finance.rates import cpr_from_smm

ERA_BREAK = periods.month(2009, 1)
ERA_AUC_FLAG = 0.8
ICE_FLAG_SHARE = 0.01
LEVEL_FLAG_RELATIVE = 0.10
TAIL_MIN_DECLINE = 0.05


# --------------------------------------------------------------------------- coherent setters
def _f(batch: PanelBatch, name: str) -> FloatArray:
    return np.asarray(batch.features[name], dtype=np.float64)


def _with(batch: PanelBatch, **columns: FloatArray) -> PanelBatch:
    return replace(batch, features={**batch.features, **columns})


def _saving(note_pct: FloatArray, market_pct: FloatArray, remaining: FloatArray) -> FloatArray:
    n = np.maximum(remaining, 1.0)
    return np.asarray(
        100.0
        * (1.0 - level_payment(1.0, market_pct / 100, n) / level_payment(1.0, note_pct / 100, n)),
        dtype=np.float64,
    )


def set_incentive(batch: PanelBatch, value: float) -> PanelBatch:
    """Move the t-1 market rate so that incentive = ``value`` (the note rate is the contract)."""
    note = _f(batch, "note_rate_pct")
    market = note - value / 100.0
    shift_bps = (_f(batch, "market_rate_t1") - market) * 100.0  # > 0 when the rate falls
    columns = {
        "incentive_bps": np.full(batch.rows, value),
        "market_rate_t1": market,
    }
    if "new_opportunity_bps" in batch.features:
        columns["new_opportunity_bps"] = _f(batch, "new_opportunity_bps") + shift_bps
        columns["new_low_bps"] = _f(batch, "new_low_bps") + shift_bps
        columns["payment_saving_pct"] = _saving(note, market, _f(batch, "remaining_payments"))
    return _with(batch, **columns)


def shift_level(batch: PanelBatch, delta_bps: float) -> PanelBatch:
    """Shift the whole rate history and the note rate by ``delta_bps``: incentive is unchanged.

    Gaps to earlier rates (new opportunity, new low) don't move either. Only absolute levels and
    the payment saving, which depends on the level by annuity arithmetic, change.
    """
    delta = delta_bps / 100.0
    note, market = _f(batch, "note_rate_pct") + delta, _f(batch, "market_rate_t1") + delta
    columns = {"note_rate_pct": note, "market_rate_t1": market}
    if "payment_saving_pct" in batch.features:
        columns["payment_saving_pct"] = _saving(note, market, _f(batch, "remaining_payments"))
    return _with(batch, **columns)


def setter(name: str) -> Callable[[PanelBatch, float], PanelBatch]:
    def set_value(batch: PanelBatch, value: float) -> PanelBatch:
        return _with(batch, **{name: np.full(batch.rows, value)})

    return set_value


def set_age(batch: PanelBatch, value: float) -> PanelBatch:
    remaining = _f(batch, "remaining_payments") + _f(batch, "loan_age") - value
    return _with(batch, loan_age=np.full(batch.rows, value), remaining_payments=remaining)


def set_month(batch: PanelBatch, value: float) -> PanelBatch:
    months = np.full(batch.rows, int(value), dtype=object)
    return replace(batch, features={**batch.features, "month_of_year": months})


def scale_loan_size(batch: PanelBatch, factor: float) -> PanelBatch:
    return _with(batch, log_original_upb=_f(batch, "log_original_upb") + np.log(factor))


@dataclass(frozen=True)
class Probe:
    name: str
    grid: tuple[float, ...]
    apply: Callable[[PanelBatch, float], PanelBatch]
    direction: int  # +1 expected non-decreasing, -1 non-increasing, 0 no constraint checked
    support_feature: str | None


PROBES = (
    Probe(
        "incentive",
        tuple(float(v) for v in range(-400, 325, 25)),
        set_incentive,
        1,
        "incentive_bps",
    ),
    Probe(
        "rate_level_at_fixed_incentive",
        tuple(float(v) for v in range(-300, 325, 50)),
        shift_level,
        0,
        "market_rate_t1",
    ),
    Probe(
        "burnout",
        (0.0, 6.0, 12.0, 24.0, 36.0, 48.0, 72.0, 96.0, 120.0),
        setter("burnout_months"),
        -1,
        "burnout_months",
    ),
    Probe(
        "loan_age", (1.0, 6.0, 12.0, 24.0, 36.0, 60.0, 120.0, 180.0, 240.0), set_age, 0, "loan_age"
    ),
    Probe("month_of_year", tuple(float(m) for m in range(1, 13)), set_month, 0, None),
    Probe(
        "rate_change_6m",
        tuple(float(v) for v in range(-200, 325, 50)),
        setter("rate_change_6m_bps"),
        0,
        "rate_change_6m_bps",
    ),
    Probe("nominal_loan_size", (1.0, 1.25, 1.5, 2.0), scale_loan_size, 0, None),
)


def _curves(model: Predictor, reference: PanelBatch, probe: Probe) -> FloatArray:
    """``(rows, grid)`` payoff probabilities."""
    return np.column_stack(
        [np.asarray(model.predict_proba(probe.apply(reference, v)))[:, 1] for v in probe.grid]
    )


def _index(grid: tuple[float, ...], value: float) -> int:
    return int(np.argmin(np.abs(np.asarray(grid) - value)))


def probe_models(
    models: Mapping[str, Predictor],
    reference: PanelBatch,
    support: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, Any]:
    """Every probe for every model, with ADR 0009 §6 flags and the probed feature's support."""
    out: dict[str, Any] = {"reference_rows": reference.rows, "probes": {}, "flags": {}}
    for probe in PROBES:
        entry: dict[str, Any] = {
            "grid": list(probe.grid),
            "training_support": (support or {}).get(probe.support_feature or "", None),
            "models": {},
        }
        for name, model in models.items():
            curves = _curves(model, reference, probe)
            mean = curves.mean(axis=0)
            row: dict[str, Any] = {
                "mean_smm": mean.tolist(),
                "mean_cpr": [float(cpr_from_smm(v)) for v in mean],
            }
            if probe.direction:
                steps = np.diff(curves, axis=1) * probe.direction
                row["ice_violation_share"] = float(np.mean(np.any(steps < -1e-12, axis=1)))
            entry["models"][name] = row
        out["probes"][probe.name] = entry
    for name in models:
        out["flags"][name] = _flags(name, out["probes"], support)
    return out


def _flags(
    name: str, probes: dict[str, Any], support: Mapping[str, Mapping[str, float]] | None
) -> dict[str, Any]:
    incentive = probes["incentive"]["models"][name]
    burnout = probes["burnout"]["models"][name]
    level = probes["rate_level_at_fixed_incentive"]
    level_curve = level["models"][name]["mean_smm"]
    base = level_curve[_index(tuple(level["grid"]), 0.0)]
    up = level_curve[_index(tuple(level["grid"]), 200.0)]
    level_change = (up - base) / base if base > 0 else None
    flags: dict[str, Any] = {
        "incentive_ice_violations": incentive["ice_violation_share"] > ICE_FLAG_SHARE,
        "burnout_ice_violations": burnout["ice_violation_share"] > ICE_FLAG_SHARE,
        "level_relative_change_plus_200bp": level_change,
        "level_raises_payoffs": level_change is not None and level_change > LEVEL_FLAG_RELATIVE,
    }
    edge = (support or {}).get("incentive_bps", {}).get("low")
    if edge is not None:
        grid = probes["incentive"]["grid"]
        curve = incentive["mean_smm"]
        at_edge = curve[_index(tuple(grid), edge)]
        below = curve[_index(tuple(grid), edge - 100.0)]
        decline = (at_edge - below) / at_edge if at_edge > 0 else None
        flags["tail_decline_per_100bp_below_support"] = decline
        flags["flat_extrapolation"] = decline is not None and decline < TAIL_MIN_DECLINE
    return flags


# --------------------------------------------------------------------------- D1
def era_encoding(train: PanelBatch, *, break_month: int = ERA_BREAK) -> dict[str, Any]:
    """Direction-free rank AUC of each numeric feature for "target month before ``break``"."""
    from sklearn.metrics import roc_auc_score

    early = (train.target_month < break_month).astype(np.int64)
    features: dict[str, Any] = {}
    if early.min() == early.max():
        return {"note": "the training rows don't span the era break", "features": features}
    names = [*NUMERIC, *(n for n in DERIVED_NUMERIC if n in train.features)]
    for name in names:
        values = _f(train, name)
        finite = np.isfinite(values)
        if finite.sum() < 2 or early[finite].min() == early[finite].max():
            features[name] = None
            continue
        auc = float(roc_auc_score(early[finite], values[finite]))
        features[name] = {"auc": max(auc, 1 - auc), "flag": max(auc, 1 - auc) >= ERA_AUC_FLAG}
    return {
        "break": periods.to_iso(break_month),
        "early_share": float(early.mean()),
        "rule": f"direction-free AUC >= {ERA_AUC_FLAG} flags a possible era proxy",
        "features": features,
        "flagged": sorted(k for k, v in features.items() if v and v["flag"]),
    }


# --------------------------------------------------------------------------- D6 / D7
def stability_summary(
    tune_losses: Mapping[str, list[float]], incentive_curves: Mapping[str, list[list[float]]]
) -> dict[str, Any]:
    """ADR 0009 §6 rule: SD across refits vs between-family gaps and the incentive response."""
    means = {name: float(np.mean(v)) for name, v in tune_losses.items()}
    ordered = sorted(means.values())
    gaps = [b - a for a, b in itertools.pairwise(ordered)]
    smallest_gap = min(gaps) if gaps else None
    families: dict[str, Any] = {}
    for name, losses in tune_losses.items():
        sd = float(np.std(losses, ddof=1)) if len(losses) > 1 else 0.0
        curves = np.asarray(incentive_curves.get(name, []), dtype=np.float64)
        curve_sd_ratio = (
            float(np.max(np.std(curves, axis=0, ddof=1) / np.maximum(curves.mean(axis=0), 1e-12)))
            if curves.ndim == 2 and curves.shape[0] > 1
            else None
        )
        unstable = (smallest_gap is not None and sd > smallest_gap / 4) or (
            curve_sd_ratio is not None and curve_sd_ratio > 0.10
        )
        families[name] = {
            "tune_log_loss": losses,
            "tune_log_loss_sd": sd,
            "incentive_response_max_relative_sd": curve_sd_ratio,
            "unstable": unstable,
        }
    return {
        "smallest_between_family_gap": smallest_gap,
        "rule": "unstable if SD > 1/4 of the smallest between-family gap, or the incentive "
        "response's relative SD exceeds 10% at any grid point",
        "families": families,
    }
