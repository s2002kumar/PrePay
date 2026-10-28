"""Pre-registered segment report (ADR 0006 §7): observed vs expected outcomes per cell.

The report describes sealed models on a holdout window and is never used to change them. Each
dimension partitions the window's at-risk rows by information known at the end of ``t-1``. Per
cell and model it reports observed vs expected (sum of predicted probabilities) payoffs and credit
dispositions. It also gives the payoff actual-to-expected ratio (A/E, with a loan-cluster bootstrap
interval for the selected model), mean log loss, and the balance-weighted payoff-only CPR proxy.
That proxy uses the same denominator as :func:`prepay.modeling.metrics.cpr_proxy`.

Cells with fewer than ``MIN_LOANS`` distinct loans are suppressed entirely. Cells with fewer than
``LOW_EVENTS`` observed payoffs are marked low-event. A cell is *poorly served* when the selected
model's A/E interval lies entirely outside ``POOR_BAND``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from prepay.arrays import FloatArray, IntArray
from prepay.features.batch import PanelBatch
from prepay.features.machine import ObjectArray
from prepay.finance.rates import cpr_from_smm
from prepay.modeling.metrics import remaining_after_scheduled, row_log_loss

MIN_LOANS = 25
LOW_EVENTS = 50
MIN_CREDIT_EVENTS = 100  # ADR 0006 §8: credit A/E only where enough events support it
POOR_BAND = (0.8, 1.25)


@dataclass(frozen=True)
class Dimension:
    name: str
    labels: tuple[str, ...]
    assign: Callable[[PanelBatch], ObjectArray]


def _numeric(batch: PanelBatch, name: str) -> FloatArray:
    return np.asarray(batch.features[name], dtype=np.float64)


def _bins(
    values: FloatArray, edges: tuple[float, ...], labels: tuple[str, ...], *, right: bool
) -> ObjectArray:
    """Label by bin; ``right=True`` makes upper edges inclusive. NaN maps to ``"missing"``."""
    index = np.searchsorted(np.asarray(edges), values, side="left" if right else "right")
    out = np.asarray(labels, dtype=object)[np.minimum(index, len(labels) - 1)]
    return np.asarray(np.where(np.isnan(values), "missing", out), dtype=object)


def _vintage(batch: PanelBatch) -> ObjectArray:
    first_payment = batch.target_month - _numeric(batch, "loan_age").astype(np.int64) + 1
    year = first_payment // 12
    edges = (2008, 2012, 2016, 2019, 2021)
    labels = ("<=2008", "2009-2012", "2013-2016", "2017-2019", "2020-2021", "2022+")
    return _bins(year.astype(np.float64), edges, labels, right=True)


def _age(batch: PanelBatch) -> ObjectArray:
    labels = ("1-12", "13-36", "37-60", "61-120", "121+")
    return _bins(_numeric(batch, "loan_age"), (12, 36, 60, 120), labels, right=True)


def _incentive(batch: PanelBatch) -> ObjectArray:
    labels = ("<-200", "[-200,-100)", "[-100,-25)", "[-25,25)", "[25,75)", "[75,150)", ">=150")
    edges = (-200, -100, -25, 25, 75, 150)
    return _bins(_numeric(batch, "incentive_bps"), edges, labels, right=False)


def _credit_score(batch: PanelBatch) -> ObjectArray:
    score = _numeric(batch, "credit_score")
    score = np.where(_numeric(batch, "credit_score_missing") == 1.0, np.nan, score)
    labels = ("<660", "660-719", "720-759", ">=760")
    return _bins(score, (660, 720, 760), labels, right=False)


def _ltv(batch: PanelBatch) -> ObjectArray:
    ltv = _numeric(batch, "original_ltv")
    ltv = np.where(_numeric(batch, "ltv_missing") == 1.0, np.nan, ltv)
    return _bins(ltv, (60, 80, 90), ("<=60", "60-80", "80-90", ">90"), right=True)


def _category(name: str, keep: tuple[str, ...]) -> Callable[[PanelBatch], ObjectArray]:
    def assign(batch: PanelBatch) -> ObjectArray:
        values = batch.features[name]
        known = np.isin(values.astype(str), keep)
        return np.asarray(np.where(known, values, "other"), dtype=object)

    return assign


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension(
        "vintage",
        ("<=2008", "2009-2012", "2013-2016", "2017-2019", "2020-2021", "2022+"),
        _vintage,
    ),
    Dimension("loan_age_months", ("1-12", "13-36", "37-60", "61-120", "121+"), _age),
    Dimension(
        "incentive_bps",
        ("<-200", "[-200,-100)", "[-100,-25)", "[-25,25)", "[25,75)", "[75,150)", ">=150"),
        _incentive,
    ),
    Dimension("credit_score", ("<660", "660-719", "720-759", ">=760", "missing"), _credit_score),
    Dimension("original_ltv", ("<=60", "60-80", "80-90", ">90", "missing"), _ltv),
    Dimension("loan_purpose", ("P", "C", "N", "other"), _category("loan_purpose", ("P", "C", "N"))),
    Dimension(
        "term", ("15y", "20y", "30y", "other"), _category("term_bucket", ("15y", "20y", "30y"))
    ),
)


def _ratio_interval(
    clusters: IntArray,
    observed: FloatArray,
    expected: FloatArray,
    *,
    replicates: int,
    seed: int,
) -> dict[str, float | str]:
    """Loan-cluster bootstrap 95% interval of ``sum(observed) / sum(expected)``."""
    _, cluster = np.unique(clusters, return_inverse=True)
    obs = np.bincount(cluster, weights=observed)
    exp = np.bincount(cluster, weights=expected)
    rng = np.random.Generator(np.random.PCG64(seed))
    n = obs.shape[0]
    ratios = np.empty(replicates)
    for b in range(replicates):
        pick = rng.integers(0, n, size=n)
        ratios[b] = obs[pick].sum() / exp[pick].sum()
    return {
        "low": float(np.quantile(ratios, 0.025)),
        "high": float(np.quantile(ratios, 0.975)),
        "kind": "loan_cluster_bootstrap_95",
    }


def _cell(
    batch: PanelBatch,
    mask: np.ndarray,
    predictions: Mapping[str, FloatArray],
    weight: FloatArray,
    clusters: IntArray,
    *,
    selected: str,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    loans = int(np.unique(clusters[mask]).shape[0])
    if loans < MIN_LOANS:
        return {"suppressed": f"fewer than {MIN_LOANS} loans"}
    y = batch.outcome_class[mask]
    payoff = (y == 1).astype(np.float64)
    observed_prepay = int(payoff.sum())
    observed_credit = int((y == 2).sum())
    w = weight[mask]
    w_total = float(w.sum())
    cell: dict[str, Any] = {
        "rows": int(mask.sum()),
        "loans": loans,
        "observed_prepay": observed_prepay,
        "observed_credit": observed_credit,
        "low_event": observed_prepay < LOW_EVENTS,
        "cpr_proxy_observed": float(cpr_from_smm((w * payoff).sum() / w_total))
        if w_total > 0
        else None,
        "models": {},
    }
    for name, p in predictions.items():
        pm = p[mask]
        expected_prepay = float(pm[:, 1].sum())
        expected_credit = float(pm[:, 2].sum())
        cell["models"][name] = {
            "expected_prepay": expected_prepay,
            "expected_credit": expected_credit,
            "prepay_ae": observed_prepay / expected_prepay if expected_prepay > 0 else None,
            "credit_ae": observed_credit / expected_credit
            if observed_credit >= MIN_CREDIT_EVENTS and expected_credit > 0
            else None,
            "log_loss": float(row_log_loss(pm, y).mean()),
            "cpr_proxy_model": float(cpr_from_smm((w * pm[:, 1]).sum() / w_total))
            if w_total > 0
            else None,
        }
    interval = _ratio_interval(
        clusters[mask],
        payoff,
        predictions[selected][mask, 1],
        replicates=replicates,
        seed=seed,
    )
    cell["models"][selected]["prepay_ae_interval"] = interval
    low, high = float(interval["low"]), float(interval["high"])
    cell["poorly_served"] = high < POOR_BAND[0] or low > POOR_BAND[1]
    return cell


def segment_report(
    batch: PanelBatch,
    predictions: Mapping[str, FloatArray],
    *,
    selected: str = "selected",
    replicates: int = 200,
    seed: int = 20261028,
) -> dict[str, Any]:
    """Every pre-registered dimension and cell for one window (ADR 0006 §7)."""
    weight = remaining_after_scheduled(batch)
    clusters = batch.clusters()
    dimensions: dict[str, Any] = {}
    for dimension in DIMENSIONS:
        labels = dimension.assign(batch)
        ordered = dimension.labels
        if "missing" not in ordered:  # e.g. an incentive with no market rate
            ordered = (*ordered, "missing")
        cells = {}
        for label in ordered:
            mask = labels == label
            if not mask.any():
                continue
            cells[label] = _cell(
                batch,
                mask,
                predictions,
                weight,
                clusters,
                selected=selected,
                replicates=replicates,
                seed=seed,
            )
        dimensions[dimension.name] = cells
    poorly_served = [
        f"{name}={label}"
        for name, cells in dimensions.items()
        for label, cell in cells.items()
        if cell.get("poorly_served")
    ]
    return {
        "definitions": {
            "expected": "sum of the model's month-t probabilities over the cell's rows",
            "prepay_ae": "observed payoffs / expected payoffs",
            "cpr_proxy": "balance-weighted payoff-only SMM over the cell, annualized "
            "(weights = balance after scheduled principal)",
            "min_loans": MIN_LOANS,
            "low_event_payoffs": LOW_EVENTS,
            "credit_ae_min_events": MIN_CREDIT_EVENTS,
            "poorly_served": f"selected model's A/E interval entirely outside {list(POOR_BAND)}",
        },
        "dimensions": dimensions,
        "poorly_served_cells": poorly_served,
    }
