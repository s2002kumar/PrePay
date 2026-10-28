"""The model feature contract: every feature, its type, and where its information comes from.

All features describe month ``t`` using information available at the end of ``t-1``. The gold
panel (dbt) and the scenario state machine (:mod:`prepay.features.machine`) must produce
identical values for these columns on historical paths; a parity test enforces it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    kind: Literal["numeric", "categorical"]
    source: Literal["origination", "contract", "rates", "calendar"]
    description: str


FEATURES: tuple[FeatureSpec, ...] = (
    FeatureSpec(
        "credit_score",
        "numeric",
        "origination",
        "Classic FICO at origination; NULL if not available",
    ),
    FeatureSpec("credit_score_missing", "numeric", "origination", "1 if FICO not available"),
    FeatureSpec("original_ltv", "numeric", "origination", "Original LTV, percent"),
    FeatureSpec("ltv_missing", "numeric", "origination", "1 if LTV not available"),
    FeatureSpec("original_dti", "numeric", "origination", "Original DTI, percent"),
    FeatureSpec("dti_missing", "numeric", "origination", "1 if DTI not available"),
    FeatureSpec("mi_pct", "numeric", "origination", "Mortgage insurance coverage, percent"),
    FeatureSpec("log_original_upb", "numeric", "origination", "ln(original UPB, USD)"),
    FeatureSpec("note_rate_pct", "numeric", "origination", "Contract note rate, percent/yr"),
    FeatureSpec("number_of_units", "numeric", "origination", "Dwelling units"),
    FeatureSpec("term_bucket", "categorical", "origination", "15y / 20y / 30y"),
    FeatureSpec("loan_purpose", "categorical", "origination", "P / C / N / R"),
    FeatureSpec("occupancy_status", "categorical", "origination", "P / I / S"),
    FeatureSpec("channel", "categorical", "origination", "R / B / C / T"),
    FeatureSpec("first_time_homebuyer", "categorical", "origination", "Y / N"),
    FeatureSpec("property_type", "categorical", "origination", "SF / PU / CO / MH / CP"),
    FeatureSpec("census_region", "categorical", "origination", "US census region of the property"),
    FeatureSpec(
        "multiple_borrowers",
        "numeric",
        "origination",
        "1 if more than one borrower (era-consistent)",
    ),
    FeatureSpec("month_of_year", "categorical", "calendar", "Calendar month of t (seasonality)"),
    FeatureSpec(
        "loan_age",
        "numeric",
        "contract",
        "Months since first payment, 1 in the first payment month",
    ),
    FeatureSpec(
        "remaining_payments", "numeric", "contract", "Contract payments remaining including t"
    ),
    FeatureSpec("market_rate_t1", "numeric", "rates", "Matched-term PMMS at end of t-1, percent"),
    FeatureSpec("incentive_bps", "numeric", "rates", "(note - market_rate_t1) x 100"),
    FeatureSpec("rate_change_6m_bps", "numeric", "rates", "(PMMS end t-1 minus end t-7) x 100"),
    FeatureSpec(
        "burnout_months",
        "numeric",
        "rates",
        "Months in [first payment, t-1] with incentive > 50 bp",
    ),
    FeatureSpec(
        "sato_bps", "numeric", "rates", "(note - PMMS at end of month before first payment) x 100"
    ),
    FeatureSpec(
        "pmms_application_based",
        "numeric",
        "rates",
        "1 if the t-1 PMMS observation is post 2022-11-17 method",
    ),
)

NUMERIC = tuple(f.name for f in FEATURES if f.kind == "numeric")
CATEGORICAL = tuple(f.name for f in FEATURES if f.kind == "categorical")
