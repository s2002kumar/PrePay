"""Behavior vs rate-path attribution (D5) and loan-hash sample clauses (ADR 0009 §9)."""

from __future__ import annotations

import pytest

from prepay.evaluation.attribution import cohort_attribution, runoff_attribution
from prepay.features.panel import sample_clause

COHORT = {
    "horizons": {
        "12m": {
            "realized_aalen_johansen_prepay": 0.10,
            "realized_prepay_interval": {"low": 0.09, "high": 0.11},
            "models": {
                "good": {
                    "hindsight_rates": {"prepay": 0.105},
                    "as_of_flat_rates": {"prepay": 0.20},
                },
                "bad": {
                    "hindsight_rates": {"prepay": 0.18},
                    "as_of_flat_rates": {"prepay": 0.25},
                },
            },
        }
    },
    "censoring_sensitivity": {
        "horizon_months": 12,
        "prepay_incidence": {
            "bound_censored_never_pay_off": 0.095,
            "bound_censored_all_pay_off": 0.13,
        },
    },
}


def test_cohort_errors_split_exactly_into_behavior_and_rate_path() -> None:
    out = cohort_attribution(COHORT)["horizons"]["12m"]["models"]
    good, bad = out["good"], out["bad"]
    assert good["behavioral_error_pp"] == pytest.approx(0.5)
    assert good["rate_path_error_pp"] == pytest.approx(9.5)
    assert good["total_error_pp"] == pytest.approx(10.0)
    assert good["behavioral_error_material"] is False  # inside interval and censoring bounds
    assert bad["behavioral_error_pp"] == pytest.approx(8.0)
    assert bad["behavioral_outside_censoring_bounds"] is True
    assert bad["behavioral_error_material"] is True


def test_attribution_passes_through_reports_without_horizons() -> None:
    assert cohort_attribution({"note": "empty cohort"}) == {"note": "empty cohort"}
    assert runoff_attribution({"note": "x"}) == {"note": "x"}


def test_runoff_attribution_decomposes_pool_factor_and_wal() -> None:
    report = {
        "observed": {"pool_factor": {"12m": 0.90}, "wal_truncated_years": 0.95},
        "models": {
            "m": {
                "hindsight_rates": {"pool_factor": {"12m": 0.88}, "wal_truncated_years": 0.94},
                "as_of_flat_rates": {"pool_factor": {"12m": 0.93}, "wal_truncated_years": 0.97},
            }
        },
    }
    out = runoff_attribution(report)["models"]["m"]
    assert out["pool_factor"]["12m"]["behavioral_error_pp"] == pytest.approx(-2.0)
    assert out["pool_factor"]["12m"]["rate_path_error_pp"] == pytest.approx(5.0)
    assert out["wal_truncated_years"]["total_error"] == pytest.approx(0.02)


def test_sample_clauses_are_disjoint_and_index_zero_is_unchanged() -> None:
    assert sample_clause(0.1) == "hash(loan_id) % 10000 < 1000"
    assert sample_clause(0.1, 0) == sample_clause(0.1)
    assert sample_clause(0.1, 3) == "hash(loan_id) % 10000 between 3000 and 3999"
    assert sample_clause(None) == "true"
    with pytest.raises(ValueError, match="disjoint"):
        sample_clause(0.5, 2)
    with pytest.raises(ValueError, match="sample_fraction"):
        sample_clause(None, 1)
