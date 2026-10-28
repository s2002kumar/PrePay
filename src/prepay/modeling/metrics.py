"""Proper scoring rules, reliability, discrimination, CPR proxy and loan-clustered bootstrap.

All metrics take ``p`` as ``(n, 3)`` probabilities in class order (active, prepay, credit) and
``y`` as outcome class codes. Uncertainty intervals resample whole **loans** (rows of one loan are
dependent), are seeded, and are labelled as bootstrap sampling intervals.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from prepay.arrays import FloatArray, IntArray
from prepay.features.batch import PanelBatch
from prepay.finance.amortization import contractual_month
from prepay.finance.rates import cpr_from_smm

EPS = 1e-15


def row_log_loss(p: FloatArray, y: IntArray) -> FloatArray:
    return np.asarray(-np.log(np.clip(p[np.arange(y.shape[0]), y], EPS, 1.0)), dtype=np.float64)


def row_brier(p: FloatArray, y: IntArray) -> FloatArray:
    onehot = np.zeros_like(p)
    onehot[np.arange(y.shape[0]), y] = 1.0
    return np.asarray(((p - onehot) ** 2).sum(axis=1), dtype=np.float64)


def reliability(score: FloatArray, hit: FloatArray, bins: int = 10) -> list[dict[str, float]]:
    """Equal-count bins of predicted probability with observed frequency (rare-class friendly)."""
    order = np.argsort(score, kind="stable")
    table = []
    for chunk in np.array_split(order, bins):
        if chunk.size == 0:
            continue
        table.append(
            {
                "mean_predicted": float(score[chunk].mean()),
                "observed_rate": float(hit[chunk].mean()),
                "count": int(chunk.size),
            }
        )
    return table


def expected_calibration_error(table: list[dict[str, float]]) -> float:
    total = sum(row["count"] for row in table)
    return float(
        sum(
            row["count"] / total * abs(row["mean_predicted"] - row["observed_rate"])
            for row in table
        )
    )


def _ranking_metrics(score: FloatArray, hit: IntArray) -> dict[str, float | None]:
    from sklearn.metrics import average_precision_score, roc_auc_score

    if hit.min() == hit.max():
        return {"auroc": None, "average_precision": None, "prevalence": float(hit.mean())}
    return {
        "auroc": float(roc_auc_score(hit, score)),
        "average_precision": float(average_precision_score(hit, score)),
        "prevalence": float(hit.mean()),
    }


def remaining_after_scheduled(batch: PanelBatch) -> FloatArray:
    """``R_t = B_t - SP_t``: exposure after the month's scheduled principal (finance engine)."""
    _, scheduled = contractual_month(
        batch.exposure_upb,
        np.asarray(batch.features["note_rate_pct"], dtype=np.float64) / 100.0,
        np.maximum(np.asarray(batch.features["remaining_payments"], dtype=np.float64), 1).astype(
            np.int64
        ),
    )
    return np.asarray(batch.exposure_upb - scheduled, dtype=np.float64)


def cpr_proxy(batch: PanelBatch, p: FloatArray) -> dict[str, Any]:
    """Monthly balance-weighted full_payoff_only_CPR_proxy: model vs observed (FINANCIAL §4).

    ``SMM(t) = sum(w * x) / sum(w)`` with ``w = R_t`` and ``x`` the predicted payoff probability
    or the observed payoff indicator. Curtailments are not observed and not included.
    """
    weight = remaining_after_scheduled(batch)
    months = np.unique(batch.target_month)
    rows = []
    for m in months:
        mask = batch.target_month == m
        denominator = weight[mask].sum()
        if denominator <= 0:
            continue
        predicted = float((weight[mask] * p[mask, 1]).sum() / denominator)
        observed = float((weight[mask] * (batch.outcome_class[mask] == 1)).sum() / denominator)
        rows.append(
            {
                "month": int(m),
                "cpr_model": float(cpr_from_smm(predicted)),
                "cpr_observed": float(cpr_from_smm(observed)),
            }
        )
    errors = np.array([r["cpr_model"] - r["cpr_observed"] for r in rows])
    return {
        "statistic": "full_payoff_only_CPR_proxy",
        "monthly": rows,
        "bias_pp": float(errors.mean() * 100) if errors.size else None,
        "mae_pp": float(np.abs(errors).mean() * 100) if errors.size else None,
    }


@dataclass(frozen=True, slots=True)
class Interval:
    estimate: float
    low: float
    high: float
    kind: str = "loan_cluster_bootstrap_95"

    def as_dict(self) -> dict[str, float | str]:
        return {"estimate": self.estimate, "low": self.low, "high": self.high, "kind": self.kind}


def cluster_bootstrap_mean(
    loan_id: np.ndarray, values: FloatArray, *, replicates: int = 200, seed: int = 20261028
) -> Interval:
    """95% percentile interval of a row mean, resampling loans with replacement."""
    _, cluster = np.unique(loan_id, return_inverse=True)
    sums = np.bincount(cluster, weights=values)
    counts = np.bincount(cluster).astype(np.float64)
    rng = np.random.Generator(np.random.PCG64(seed))
    draws = rng.integers(0, sums.shape[0], size=(replicates, sums.shape[0]))
    means = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
    return Interval(
        float(values.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))
    )


def evaluate(batch: PanelBatch, p: FloatArray, *, bootstrap: bool = True) -> dict[str, Any]:
    y = batch.outcome_class
    ll = row_log_loss(p, y)
    brier = row_brier(p, y)
    result: dict[str, Any] = {
        "rows": batch.rows,
        "loans": len(np.unique(batch.loan_id)),
        "events": {"prepay": int((y == 1).sum()), "credit": int((y == 2).sum())},
        "log_loss": float(ll.mean()),
        "brier": float(brier.mean()),
        "prepay": {**_ranking_metrics(p[:, 1], (y == 1).astype(np.int64))},
        "credit": {**_ranking_metrics(p[:, 2], (y == 2).astype(np.int64))},
        "cpr_proxy": cpr_proxy(batch, p),
    }
    for name, column in (("prepay", 1), ("credit", 2)):
        table = reliability(p[:, column], (y == column).astype(np.float64))
        result[name]["reliability"] = table
        result[name]["ece"] = expected_calibration_error(table)
        result[name]["mean_predicted"] = float(p[:, column].mean())
    if bootstrap:
        result["log_loss_interval"] = cluster_bootstrap_mean(batch.loan_id, ll).as_dict()
        result["brier_interval"] = cluster_bootstrap_mean(batch.loan_id, brier).as_dict()
    return result


def paired_difference(
    batch: PanelBatch, p_candidate: FloatArray, p_reference: FloatArray
) -> dict[str, float | str]:
    """Log-loss difference (candidate - reference) with a loan-clustered interval; < 0 = better."""
    diff = row_log_loss(p_candidate, batch.outcome_class) - row_log_loss(
        p_reference, batch.outcome_class
    )
    return cluster_bootstrap_mean(batch.loan_id, diff).as_dict()
