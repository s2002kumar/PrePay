"""The owner's E01 report renders every predefined metric, flag and rule (ADR 0014 §9.6).

A hand-built summary with the shape :func:`prepay.modeling.e01.summarize` writes: fast, so the
rendering rules are tested without the synthetic E01 run (the integration tests render that).
"""

from __future__ import annotations

import copy
from typing import Any

from prepay.modeling.e01 import B2, COMPARISON_FAMILIES, FAMILIES, LABEL, M1, X1, X2
from prepay.modeling.e01_report import DEFINITIONS, PRIVATE_BANNER, READING, render_report

ORIGIN = "2009-12"
RUN_ID = "20261116T000000Z-E01-2009-12-abcdef12"
D2_REASON = f"D2 flags to explain: {ORIGIN}: incentive_ice_violations"


def _ratio(value: float) -> dict[str, float]:
    return {"estimate": value, "low": value - 0.05, "high": value + 0.05}


def _runoff_mode(scale: float) -> dict[str, Any]:
    # Keys in reverse length order: the report must sort horizons by length.
    errors = {"24m": 0.9 * scale, "12m": 0.4 * scale, "6m": 0.1 * scale}
    return {"pool_factor_error_pp": errors, "wal_error_years": 0.012 * scale}


def _attribution_row(model: str, horizon: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "behavioral_error_pp": 0.3,
        "rate_path_error_pp": -0.1,
        "total_error_pp": 0.2,
        "behavioral_outside_realized_interval": model == M1,
    }
    if horizon == "12m":  # the censoring-bound horizon: only there is materiality read
        row["behavioral_error_material"] = model == M1
    return row


def _d2(model: str) -> dict[str, Any]:
    return {
        "incentive_ice_violations": model == X1,
        "burnout_ice_violations": False,
        "level_relative_change_plus_200bp": 0.02,
        "level_raises_payoffs": False,
        "tail_decline_per_100bp_below_support": 0.2,
        "flat_extrapolation": model == B2,
    }


def _fold() -> dict[str, Any]:
    models = FAMILIES
    support = {"verdict": "inside", "outside_share": 0.01, "sparse_share": 0.02}
    checks = {"T1": True, "T2": None, "T3": True, "T4": False, "T5": True, "T6": True}
    horizons = ("24m", "12m", "6m")
    return {
        "regime_class": "regime_shift",
        "window": "2010-01..2011-12",
        "evaluation_rows": 1000,
        "log_loss": {m: 0.05 + 0.001 * i for i, m in enumerate(models)},
        "brier": dict.fromkeys(models, 0.01),
        "payoff_ae": {m: _ratio(1.0) for m in models},
        "fifth_ae": {m: {"bottom": _ratio(0.9), "top": _ratio(1.1)} for m in models},
        "cpr_bias_pp": {m: {"estimate": 0.1, "low": -0.2, "high": 0.4} for m in models},
        "cpr_mae_pp": dict.fromkeys(models, 0.5),
        "support": {"rows": dict(support), "balance": dict(support)},
        "d2_flags": {m: _d2(m) for m in models},
        "tolerances": {m: dict(checks) for m in models},
        "cohort_attribution": {
            "identity": "total = behavioral + rate path",
            "unit": "pp",
            "horizons": {
                h: {
                    "realized_prepay": 0.06,
                    "models": {m: _attribution_row(m, h) for m in models},
                }
                for h in horizons
            },
        },
        "runoff": {
            m: {"hindsight_rates": _runoff_mode(1.0), "as_of_flat_rates": _runoff_mode(2.0)}
            for m in models
        },
        "stages": {},
    }


def _rules() -> dict[str, Any]:
    f_m1, f_b2 = COMPARISON_FAMILIES["F-M1"], COMPARISON_FAMILIES["F-B2"]
    reasons = {c: ["R2 vs M1 does not hold"] for c, _ in f_m1}
    reasons[X1] = [*reasons[X1], D2_REASON]
    r2 = {"result": "incomplete", "lower_loss_shift_folds": 0, "shift_folds": [ORIGIN]}
    r3 = {"result": "incomplete", "differs_in": "a bundle", "single_choice": False}
    t3 = {"error": 0.4, "tolerance": 1.0, "within_tolerance": True}
    t4 = {"error": 0.2, "tolerance": 0.1, "within_tolerance": False}
    outside = [f"{ORIGIN} incentive_bps=<-200"]
    return {
        "R1_description": {
            "order_by_fold": {ORIGIN: list(FAMILIES)},
            "mean_rank": {m: float(i + 1) for i, m in enumerate(FAMILIES)},
            "worst_relative_gap_to_fold_best": {m: 0.01 * i for i, m in enumerate(FAMILIES)},
            "class_counts": {
                "F-M1": {c: {"inconclusive": 1} for c, _ in f_m1},
                "F-B2": {c: {"higher_loss": 1} for c, _ in f_b2},
            },
        },
        "R2_consistency": {
            "F-M1": {c: dict(r2) for c, _ in f_m1},
            "F-B2": {c: dict(r2) for c, _ in f_b2},
        },
        "R3_design_bundles": {f"{a} - {b}": dict(r3) for a, b in COMPARISON_FAMILIES["F-DESIGN"]},
        "R4_calibration_transfer": {
            "models": {
                M1: {"transfers": True, "outside_band": []},
                X1: {"transfers": False, "outside_band": outside},
            }
        },
        "R5_financial_materiality": {
            "folds": {ORIGIN: {m: {"T3": dict(t3), "T4": dict(t4)} for m in FAMILIES}}
        },
        "R6_stability": {
            "tune_log_loss_sd": {"samples": {M1: 1e-4, X2: 2e-4}},
            "unstable_flags": {"samples": {M1: False, X2: True}},
        },
        "R7_nomination": {
            "candidates": {c: {"nominated": False, "reasons": reasons[c]} for c, _ in f_m1},
            "nominated": [],
        },
    }


def _summary() -> dict[str, Any]:
    comparison = {
        "origin": ORIGIN,
        "regime_class": "regime_shift",
        "family": "F-M1",
        "candidate": X1,
        "reference": M1,
        "estimate": -1e-4,
        "relative_to_reference": -0.002,
        "simultaneous_low": -2e-4,
        "simultaneous_high": 1e-5,
        "class": "inconclusive",
        "sampling_fragility": "not_fragile",
    }
    return {
        "kind": "prepay-e01-summary",
        "label": LABEL,
        "evidence_class": "E1_development",
        "synthetic": False,
        "complete": False,
        "folds_expected": [ORIGIN],
        "folds_completed": [ORIGIN],
        "stability_completed": ["samples"],
        "folds": {ORIGIN: _fold()},
        "comparisons": [comparison],
        "rules": _rules(),
        "provenance": {
            ORIGIN: {"run_id": RUN_ID, "git_sha": "95efdc87e7cba0c8", "git_dirty": False}
        },
        "ledger": {"identity_digest": "8c06e10b", "reproduction": {"identical": True}},
    }


def _section(text: str, heading: str, end: str = "####") -> str:
    return text.split(heading)[1].split(end)[0]


def _reversed_keys(value: Any) -> Any:
    """The same summary with every mapping's keys in reverse order (lists keep theirs)."""
    if isinstance(value, dict):
        return {k: _reversed_keys(value[k]) for k in reversed(list(value))}
    if isinstance(value, list):
        return [_reversed_keys(v) for v in value]
    return value


def test_the_report_frames_e01_as_development_evidence_not_confirmation() -> None:
    text = render_report(_summary())
    assert PRIVATE_BANNER in text
    assert READING in text
    assert "not prospective confirmation" in text
    assert "no figure in it is a validated forecast" in text
    assert text.index(READING) < text.index("## Status")  # read before any number
    assert "- Evidence class: E1_development." in text


def test_r7_reasons_and_d2_flags_are_shown_as_computed() -> None:
    text = render_report(_summary())
    assert "this report doesn't explain or waive any flag" in text
    assert f"- X1: not nominated. R2 vs M1 does not hold; {D2_REASON}." in text
    d2 = _section(text, "#### Economic diagnostics (D2 probes)")
    assert "| X1 | **yes** | no | +2.0% | no | 20.0% | no |" in d2  # a blocking flag is bold
    assert "| B2 | no | no | +2.0% | no | 20.0% | yes |" in d2  # informational: not bold
    for definition in DEFINITIONS:
        assert f"- {definition}" in text


def test_every_rule_and_fold_measure_has_a_section() -> None:
    text = render_report(_summary())
    for heading in (
        "**R1** (description; ranks are point estimates, not tests):",
        "#### Calibration by predicted payoff",
        "#### Run-off (cohort active at t0)",
        "#### Tolerances",
        "#### Payoff incidence attribution",
        "## Provenance",
        "## Definitions",
        "## Caveats",
    ):
        assert heading in text
    ranked = "B0 < B1 < B2 < M1 < X1 < X2 < X3 < H1"
    assert f"- {ORIGIN}, by log loss (lowest first): {ranked}." in text
    assert "| M1 | 4.00 | 3.00% | n/a | higher loss 1 |" in text  # M1 isn't an F-M1 candidate
    assert "| B2 | 3.00 | 2.00% | inconclusive 1 | n/a |" in text
    assert f"- X1, cells outside [0.8, 1.25]: {ORIGIN} incentive_bps=<-200" in text
    assert "across loan samples: X2; across seeds: not measured." in text
    assert "| X1 | 0.900 [0.850, 0.950] | 1.100 [1.050, 1.150] |" in text
    t3, t4 = "+0.40 vs +/-1.00 pp: pass", "+0.200 vs +/-0.100 years: **fail**"
    assert f"| M1 | pass | undetermined | {t3} | {t4} | pass | pass |" in text
    assert "`8c06e10b`" in text
    assert f"| {ORIGIN} | `{RUN_ID}` | `95efdc87e7cb` | yes |" in text


def test_horizons_sort_by_length_and_materiality_reads_only_where_defined() -> None:
    text = render_report(_summary())
    runoff = _section(text, "#### Run-off (cohort active at t0)")
    columns = " | ".join(f"Pool-factor error {h}, pp" for h in ("6m", "12m", "24m"))
    assert f"| Model | Rates | {columns} | Truncated WAL error, years |" in runoff
    assert "| M1 | hindsight | +0.10 | +0.40 | +0.90 | +0.012 |" in runoff
    assert "| M1 | as-of flat | +0.20 | +0.80 | +1.80 | +0.024 |" in runoff
    attribution = _section(text, "#### Payoff incidence attribution", "## ")
    assert "(Aalen-Johansen): 6m 6.00%, 12m 6.00%, 24m 6.00%." in attribution
    assert "| 12m | M1 | +0.30 | -0.10 | +0.20 | yes | yes |" in attribution
    assert "| 6m | M1 | +0.30 | -0.10 | +0.20 | yes | n/a |" in attribution
    assert attribution.index("| 6m |") < attribution.index("| 12m |") < attribution.index("| 24m |")


def test_the_text_depends_on_values_not_on_key_order() -> None:
    summary = _summary()
    assert render_report(summary) == render_report(_reversed_keys(summary))


def test_missing_measures_read_not_available_instead_of_failing() -> None:
    summary = _summary()
    fold = summary["folds"][ORIGIN]
    fold["runoff"] = {m: {} for m in FAMILIES}
    fold["cohort_attribution"] = {"note": "no mature horizon"}
    for flags in fold["d2_flags"].values():
        del flags["tail_decline_per_100bp_below_support"], flags["flat_extrapolation"]
    del summary["rules"]["R6_stability"]["unstable_flags"]
    text = render_report(summary)
    assert "n/a: the fold has no run-off backtest." in text
    assert "n/a: no mature horizon." in text
    assert "| X1 | **yes** | no | +2.0% | no | n/a | n/a |" in text
    assert "across loan samples: not measured; across seeds: not measured." in text
    assert "None" not in text


def test_rendering_does_not_change_the_summary() -> None:
    summary = _summary()
    before = copy.deepcopy(summary)
    render_report(summary)
    assert summary == before
