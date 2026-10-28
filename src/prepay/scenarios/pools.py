"""Loan pools for projection, including the fictional demo pools served publicly.

Demo pools are generated from seeded distributions only. They read no file and no Freddie Mac
record, and are labeled ``fictional`` everywhere they appear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from prepay import periods
from prepay.arrays import FloatArray, IntArray
from prepay.features.machine import LoanStatics, census_region
from prepay.finance.amortization import contractual_balance_after


@dataclass(frozen=True)
class Pool:
    pool_id: str
    name: str
    description: str
    as_of_month: int  # balances are as of the end of this month (t0)
    statics: LoanStatics
    current_upb: FloatArray
    fictional: bool = True

    @property
    def remaining_payments(self) -> IntArray:
        return np.asarray(self.statics.maturity_month - self.as_of_month, dtype=np.int64)

    def summary(self) -> dict[str, Any]:
        s = self.statics
        weight = self.current_upb / self.current_upb.sum()
        age = self.as_of_month - s.first_payment_month + 1

        def mix(values: np.ndarray) -> dict[str, float]:
            keys = np.array(["unknown" if v is None else str(v) for v in values])
            return {k: round(float(weight[keys == k].sum()), 4) for k in sorted(set(keys))}

        def weighted(values: FloatArray) -> float | None:
            ok = np.isfinite(values)
            return float((values[ok] * weight[ok]).sum() / weight[ok].sum()) if ok.any() else None

        term = np.where(
            s.original_loan_term <= 180, "15y", np.where(s.original_loan_term <= 240, "20y", "30y")
        )
        return {
            "pool_id": self.pool_id,
            "name": self.name,
            "description": self.description,
            "fictional": self.fictional,
            "as_of": periods.to_iso(self.as_of_month),
            "loans": self.statics.count,
            "current_upb_usd": float(self.current_upb.sum()),
            "wac_pct": weighted(s.note_rate_pct),
            "wala_months": weighted(age.astype(np.float64)),
            "wam_months": weighted(self.remaining_payments.astype(np.float64)),
            "average_loan_size_usd": float(self.current_upb.mean()),
            "wa_credit_score": weighted(s.credit_score),
            "wa_original_ltv_pct": weighted(s.original_ltv),
            "term_mix": mix(term),
            "purpose_mix": mix(s.loan_purpose),
            "occupancy_mix": mix(s.occupancy_status),
            "region_mix": mix(np.array([census_region(x) for x in s.property_state], dtype=object)),
            "note_rate_histogram": _histogram(s.note_rate_pct, weight),
        }


def _histogram(values: FloatArray, weight: FloatArray) -> list[dict[str, float]]:
    edges = np.arange(np.floor(values.min() * 4) / 4, np.ceil(values.max() * 4) / 4 + 0.25, 0.25)
    if edges.size < 2:
        edges = np.array([values.min(), values.min() + 0.25])
    index = np.clip(np.searchsorted(edges, values, side="right") - 1, 0, edges.size - 2)
    share = np.bincount(index, weights=weight, minlength=edges.size - 1)
    return [
        {"low_pct": float(edges[i]), "high_pct": float(edges[i + 1]), "upb_share": float(v)}
        for i, v in enumerate(share)
    ]


# --------------------------------------------------------------------------- fictional pools
DEMO_AS_OF = periods.month(2026, 6)
STATES = ("CA", "TX", "FL", "NY", "IL", "PA", "OH", "GA", "NC", "WA", "CO", "AZ", "MA", "VA")


@dataclass(frozen=True, slots=True)
class DemoPoolSpec:
    pool_id: str
    name: str
    description: str
    origination_year: int
    term: int
    note_mean_pct: float
    note_sd_pct: float
    loans: int
    seed: int


DEMO_POOL_SPECS = (
    DemoPoolSpec(
        "fictional-2021-low-coupon",
        "2021 low-coupon pool (fictional)",
        "30-year loans originated in a fictional 2021 low-rate year; deeply out of the "
        "money at the as-of date.",
        2021,
        360,
        3.0,
        0.25,
        900,
        1,
    ),
    DemoPoolSpec(
        "fictional-2023-high-coupon",
        "2023 higher-coupon pool (fictional)",
        "30-year loans originated in a fictional 2023 high-rate year; near or in the "
        "money at the as-of date.",
        2023,
        360,
        6.9,
        0.3,
        900,
        2,
    ),
    DemoPoolSpec(
        "fictional-2013-seasoned",
        "Seasoned 2013 pool (fictional)",
        "Thirteen-year-seasoned 30-year loans with mid-range coupons and smaller balances.",
        2013,
        360,
        4.1,
        0.3,
        900,
        3,
    ),
    DemoPoolSpec(
        "fictional-2020-15-year",
        "2020 15-year pool (fictional)",
        "15-year loans from a fictional 2020 refinance wave.",
        2020,
        180,
        2.6,
        0.25,
        900,
        4,
    ),
)


def demo_pool(spec: DemoPoolSpec, as_of_month: int = DEMO_AS_OF) -> Pool:
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence([20261028, spec.seed])))
    n = spec.loans
    first_payment = periods.month(spec.origination_year, 1) + rng.integers(2, 14, n)
    maturity = first_payment + spec.term - 1
    note = np.round(rng.normal(spec.note_mean_pct, spec.note_sd_pct, n) * 8) / 8
    original_upb = np.clip(
        np.round(rng.lognormal(np.log(320_000), 0.45, n) / 1000) * 1000, 50_000, 1_200_000
    )
    paid = as_of_month - first_payment + 1
    current = np.array(
        [
            contractual_balance_after(float(b), float(c) / 100.0, spec.term, int(k))
            for b, c, k in zip(original_upb, note, paid, strict=True)
        ]
    )
    purpose = rng.choice(np.array(["P", "C", "N"]), n, p=[0.55, 0.2, 0.25]).astype(object)
    statics = LoanStatics(
        note_rate_pct=note,
        original_loan_term=np.full(n, spec.term, dtype=np.int64),
        first_payment_month=first_payment.astype(np.int64),
        maturity_month=maturity.astype(np.int64),
        original_upb=original_upb,
        credit_score=np.clip(np.round(rng.normal(752, 40, n)), 620, 840),
        original_ltv=np.clip(np.round(rng.normal(74, 13, n)), 20, 97),
        original_dti=np.clip(np.round(rng.normal(35, 8, n)), 5, 50),
        mi_pct=np.zeros(n),
        number_of_units=np.ones(n),
        number_of_borrowers=rng.choice(np.array([1.0, 2.0]), n, p=[0.45, 0.55]),
        loan_purpose=purpose,
        occupancy_status=rng.choice(np.array(["P", "I", "S"]), n, p=[0.9, 0.06, 0.04]).astype(
            object
        ),
        channel=rng.choice(np.array(["R", "B", "C", "T"]), n, p=[0.45, 0.1, 0.3, 0.15]).astype(
            object
        ),
        first_time_homebuyer=np.where(
            purpose == "P", rng.choice(np.array(["Y", "N"]), n), "N"
        ).astype(object),
        property_type=rng.choice(np.array(["SF", "PU", "CO"]), n, p=[0.68, 0.22, 0.1]).astype(
            object
        ),
        property_state=rng.choice(np.array(STATES), n).astype(object),
    )
    return Pool(spec.pool_id, spec.name, spec.description, as_of_month, statics, current)


def demo_pools() -> dict[str, Pool]:
    return {spec.pool_id: demo_pool(spec) for spec in DEMO_POOL_SPECS}
