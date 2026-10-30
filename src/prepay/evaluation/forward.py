"""Forward evaluation: the only confirmatory evidence of the reliability program.

This module implements the ADR 0008 mechanism under the ADR 0010 pre-registration and its
amendment 2.

**Registration** (:func:`register`) runs before any forward month exists. It records:

- each member run: run ID, seal SHA-256, candidate digest and models;
- the comparison families, interval method and business tolerances;
- the minimum number of forward months and the *seen-through* month.

It writes one file, once. Members are identified by content (seal SHA-256 and candidate
digest), not by path, so artifacts can be moved and remapped at evaluation time.

**Evaluation** (:func:`evaluate`) runs once per later data lock. It verifies, in order:

1. the registration digest and every member's seal;
2. that the lock is a later release with a different fingerprint, whose cutoff gives at least the
   minimum forward months (no interim looks);
3. that no report exists yet for that lock.

It then reads **only target months after the seen-through month** and scores every registered
model with its own pre-declared calibration. It writes a read-only report. The first report is
the primary opening; later locks add monitoring reports and never replace it.

**Rehearsal** (:func:`rehearse`) runs the same scoring on the twelve months *up to* the
seen-through month, using the members' own lock. It measures time and peak memory and catches
crashes before the one real opening. Its output is labeled as a rehearsal, not evidence.
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np

from prepay import periods
from prepay.arrays import FloatArray
from prepay.evaluation.cohort import Predictor
from prepay.evaluation.cohort import backtest as cohort_backtest
from prepay.evaluation.inference import loan_cluster, summarize, two_way
from prepay.evaluation.regimes import row_regimes
from prepay.evaluation.runoff import runoff_backtest
from prepay.evaluation.segments import LOW_EVENTS, POOR_BAND, segment_report
from prepay.features.batch import PanelBatch
from prepay.features.derived import augment
from prepay.features.panel import rate_path_from_bronze, rate_path_from_warehouse, read_panel
from prepay.ingest.lock import DataLock
from prepay.io import read_json, sha256_file, write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.lockbox import SEAL, SealError, load_seal, read_only
from prepay.modeling.probes import set_incentive
from prepay.modeling.registry import MANIFEST, Run, load_run
from prepay.provenance import canonical_digest
from prepay.transform import warehouse_path

REGISTRATION = "forward-registration.json"
EVALUATIONS = "evaluations"
REHEARSALS = "rehearsals"
MIN_FORWARD_MONTHS = 12
ALPHA = 0.05
REPLICATES = 1000
#: ADR 0010 amendment 2: decisions use the two-way (loan x month) pigeonhole bootstrap.
INTERVAL_METHOD = "two_way"
MONOTONE_REFERENCE_ROWS = 5000
MONOTONE_MATERIAL = 1e-6  # monthly probability; about 0.0012 pp of CPR
MONOTONE_GRID = tuple(float(v) for v in range(-400, 325, 25))


class ForwardError(RuntimeError):
    """The registration, a member run or the data lock fails a forward-evaluation rule."""


@dataclass(frozen=True, slots=True)
class Comparison:
    id: str
    candidate: str  # "<member>/<model>"; model "selected" is the run's sealed selection
    reference: str
    family: Literal["primary", "secondary"]
    question: str


#: ADR 0010 §3 and §4. ``REF`` is the sealed primary run; ``REF/selected`` is M1+T.
ADR0010_COMPARISONS = (
    Comparison("P1", "DEV2017/X1_factored_gbm", "REF/selected", "primary", "level removal"),
    Comparison("P2", "DEV2017/X2_factored_gbm", "REF/selected", "primary", "level + burnout"),
    Comparison("P3", "DEV2017/X1_factored_gbm", "REF/B1_lookup", "primary", "vs simple lookup"),
    Comparison("P4", "DEV2017/X2_factored_gbm", "REF/B1_lookup", "primary", "vs simple lookup"),
    Comparison("S1", "DEV2017/H1_constrained_hazard", "REF/selected", "secondary", "hazard"),
    Comparison("S2", "DEV2017/X3_factored_gbm", "REF/selected", "secondary", "behavioral"),
    Comparison("S3", "DEV2017/H1_constrained_hazard", "REF/B2_logistic", "secondary", "vs B2"),
    Comparison("S4", "REFIT2026/M1_lightgbm", "REF/selected", "secondary", "window, same method"),
    Comparison("S5", "REFIT2026/X2_factored_gbm", "DEV2017/X2_factored_gbm", "secondary", "window"),
    Comparison(
        "S6",
        "REFIT2026/H1_constrained_hazard",
        "DEV2017/H1_constrained_hazard",
        "secondary",
        "window",
    ),
    Comparison("S7", "REFIT2026/B2_logistic", "REF/B2_logistic", "secondary", "window, logistic"),
)

#: ADR 0010 §5 business tolerances, as amended (amendment 2), in hindsight mode.
TOLERANCES: dict[str, dict[str, float]] = {
    "T1_cpr_bias_pp": {"absolute_pp": 1.0, "relative": 0.15},
    "T2_incidence_12m_pp": {"absolute_pp": 1.0, "relative": 0.15},
    "T3_pool_factor_12m_pp": {"absolute_pp": 1.0, "relative_of_paydown": 0.10},
    "T4_wal_24m_years": {"absolute_years": 0.04, "relative_of_shortening": 0.10},
    "T5_poorly_served_share": {"max_share": 0.10},
    "T6_calibration": {
        "ae_low": 0.9,
        "ae_high": 1.1,
        "quintile_ae_low": POOR_BAND[0],
        "quintile_ae_high": POOR_BAND[1],
    },
}


# --------------------------------------------------------------------------- statistics
def holm(p_values: Mapping[str, float], alpha: float = ALPHA) -> dict[str, dict[str, Any]]:
    """Holm-Bonferroni step-down adjusted p-values and decisions within one family."""
    order = sorted(p_values, key=p_values.__getitem__)
    m = len(order)
    adjusted: dict[str, float] = {}
    running = 0.0
    for rank, key in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[key]))
        adjusted[key] = running
    return {
        key: {"p": p_values[key], "p_holm": adjusted[key], "reject": adjusted[key] < alpha}
        for key in p_values
    }


def paired_test(
    clusters: np.ndarray,
    difference: FloatArray,
    *,
    months: np.ndarray | None = None,
    method: str = INTERVAL_METHOD,
    replicates: int = REPLICATES,
    seed: int = 20261029,
) -> dict[str, Any]:
    """Mean paired difference with a decision interval and a one-sided p for "< 0".

    The decision interval is the two-way (loan x month) bootstrap when ``months`` is given and
    ``method`` is ``"two_way"``; the loan-cluster interval is always reported next to it.
    ``p = (1 + #{replicate mean >= 0}) / (replicates + 1)``.
    """
    estimate = float(difference.mean())
    loan = summarize(
        loan_cluster(clusters, difference, replicates=replicates, seed=seed),
        estimate,
        "loan_cluster",
    )
    if method == "two_way" and months is not None:
        decision = summarize(
            two_way(clusters, months, difference, replicates=replicates, seed=seed),
            estimate,
            "two_way",
        )
    else:
        decision = loan
    return {
        **decision.as_dict(),
        "kind": f"{decision.method}_bootstrap_{replicates}",
        "loan_cluster": loan.as_dict(),
    }


# --------------------------------------------------------------------------- registration
def _member_record(run_dir: Path) -> dict[str, Any]:
    sealed = load_seal(run_dir)  # verifies the candidate digest
    manifest = read_json(run_dir / MANIFEST)
    return {
        "run_dir": str(run_dir.resolve()),
        "run_id": manifest["run_id"],
        "kind": manifest.get("kind", "prepay-model-run"),
        "release": manifest["release"],
        "data_lock_fingerprint": manifest["data_lock_fingerprint"],
        "seal_sha256": sha256_file(run_dir / SEAL),
        "candidate_digest": sealed.payload["candidate_digest"],
        "models": manifest["models"],
        "synthetic": manifest["synthetic"],
    }


def _check_reference(ref: str, members: Mapping[str, dict[str, Any]]) -> None:
    label, _, model = ref.partition("/")
    if label not in members or (model != "selected" and model not in members[label]["models"]):
        raise ForwardError(f"comparison refers to unknown model {ref!r}")


def register(
    registry_dir: Path,
    members: Mapping[str, Path],
    lock: DataLock,
    *,
    comparisons: Sequence[Comparison] = ADR0010_COMPARISONS,
    min_months: int = MIN_FORWARD_MONTHS,
) -> Path:
    """Write the write-once registration; the seen-through month is ``lock``'s cutoff."""
    target = registry_dir / REGISTRATION
    if target.exists():
        raise ForwardError(f"{target} exists; a registration is written once")
    records = {label: _member_record(run_dir) for label, run_dir in members.items()}
    for label, record in records.items():
        if record["data_lock_fingerprint"] != lock.fingerprint():
            raise ForwardError(f"member {label} was not trained on the registering data lock")
    for comparison in comparisons:
        _check_reference(comparison.candidate, records)
        _check_reference(comparison.reference, records)
    payload: dict[str, Any] = {
        "kind": "prepay-forward-registration",
        "adr": "0010 (amendment 2)",
        "registered_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "seen_through": lock.performance_cutoff_month,
        "seen_through_release": lock.release,
        "min_forward_months": min_months,
        "members": records,
        "comparisons": [asdict(c) for c in comparisons],
        "tolerances": TOLERANCES,
        "alpha": ALPHA,
        "replicates": REPLICATES,
        "interval_method": INTERVAL_METHOD,
        "monotonicity_materiality": MONOTONE_MATERIAL,
    }
    payload["registration_digest"] = canonical_digest(payload)
    write_json_atomic(target, payload)
    read_only(target)
    return target


@dataclass(frozen=True)
class Registration:
    registry_dir: Path
    payload: dict[str, Any]
    member_dirs: Mapping[str, Path] | None = None

    @property
    def seen_through(self) -> int:
        return periods.parse_iso(self.payload["seen_through"])

    def member_dir(self, label: str) -> Path:
        """Where the member lives now: a remapped directory, or the registered one."""
        if self.member_dirs and label in self.member_dirs:
            return Path(self.member_dirs[label])
        return Path(self.payload["members"][label]["run_dir"])

    def verify(self) -> None:
        """Registration digest, and every member's seal, candidate digest and run ID."""
        body = {k: v for k, v in self.payload.items() if k != "registration_digest"}
        if canonical_digest(body) != self.payload["registration_digest"]:
            raise ForwardError("the forward registration was modified after it was written")
        unknown = set(self.member_dirs or {}) - set(self.payload["members"])
        if unknown:
            raise ForwardError(f"remapped members are not registered: {sorted(unknown)}")
        for label, record in self.payload["members"].items():
            run_dir = self.member_dir(label)
            if not (run_dir / SEAL).is_file():
                raise ForwardError(f"member {label}: no seal at {run_dir}")
            if sha256_file(run_dir / SEAL) != record["seal_sha256"]:
                raise ForwardError(f"member {label}: seal differs from the registered seal")
            try:
                sealed = load_seal(run_dir)
            except SealError as exc:  # artifacts changed after sealing
                raise ForwardError(f"member {label}: {exc}") from exc
            if sealed.payload["candidate_digest"] != record["candidate_digest"]:
                raise ForwardError(f"member {label}: candidate digest differs")
            if read_json(run_dir / MANIFEST)["run_id"] != record["run_id"]:
                raise ForwardError(f"member {label}: run ID differs")


def load_registration(
    registry_dir: Path, member_dirs: Mapping[str, Path] | None = None
) -> Registration:
    target = registry_dir / REGISTRATION
    if not target.is_file():
        raise ForwardError(f"no forward registration in {registry_dir}")
    registration = Registration(registry_dir, read_json(target), member_dirs)
    registration.verify()
    return registration


def check_forward_lock(registration: Registration, lock: DataLock) -> int:
    """The number of forward months ``lock`` holds; refuses locks that break ADR 0010 §2."""
    members = registration.payload["members"].values()
    if lock.fingerprint() in {m["data_lock_fingerprint"] for m in members}:
        raise ForwardError("the data lock is a member's own lock; forward months need a new one")
    if lock.release <= max(int(m["release"]) for m in members):
        raise ForwardError("forward evaluation needs a later Freddie Mac release")
    months = periods.parse_iso(lock.performance_cutoff_month) - registration.seen_through
    minimum = int(registration.payload["min_forward_months"])
    if months < minimum:
        raise ForwardError(
            f"the lock holds {months} forward months; at least {minimum} are needed "
            "(no interim looks, ADR 0010 §2)"
        )
    return months


# --------------------------------------------------------------------------- scoring
def _predictors(registration: Registration) -> dict[str, Predictor]:
    """Every registered model, each with its own pre-declared calibration."""
    models: dict[str, Predictor] = {}
    for label, record in registration.payload["members"].items():
        run: Run = load_run(registration.member_dir(label))
        # Only a primary run has a selection distinct from its models (ADR 0004); an experiment
        # run's designated model is already scored under its own name.
        if record["kind"] == "prepay-model-run":
            models[f"{label}/selected"] = run.selected
        for name in run.models:
            models[f"{label}/{name}"] = run.calibrated(name)
    return models


class _ForwardAccess:
    def __init__(self, registration: Registration) -> None:
        self.registration = registration

    def verify(self) -> None:
        self.registration.verify()


def _tolerance(observed: float, rule: dict[str, float]) -> float:
    return max(rule["absolute_pp"], rule["relative"] * abs(observed))


def quintile_ae(batch: PanelBatch, p: FloatArray) -> dict[str, float | None]:
    """Payoff A/E in the bottom and top fifth of rows ranked by predicted payoff probability."""
    order = np.argsort(p[:, 1], kind="stable")
    parts = np.array_split(order, 5)
    out: dict[str, float | None] = {}
    for label, rows in (("bottom", parts[0]), ("top", parts[-1])):
        expected = float(p[rows, 1].sum())
        observed = float((batch.outcome_class[rows] == 1).sum())
        out[label] = observed / expected if expected > 0 else None
    return out


def monotonicity(model: Predictor, reference: PanelBatch) -> dict[str, float]:
    """Final payoff probability along a coherent incentive grid (ADR 0010 amendment 2).

    Reported, not a tolerance. A decrease larger than ``MONOTONE_MATERIAL`` (monthly probability)
    in any step counts as material.
    """
    curves = np.column_stack(
        [np.asarray(model.predict_proba(set_incentive(reference, v)))[:, 1] for v in MONOTONE_GRID]
    )
    steps = np.diff(curves, axis=1)
    return {
        "rows": reference.rows,
        "share_rows_with_material_decrease": float(np.mean(np.any(steps < -MONOTONE_MATERIAL, 1)))
        if reference.rows
        else 0.0,
        "max_decrease": float(max(0.0, -steps.min())) if steps.size else 0.0,
        "materiality": MONOTONE_MATERIAL,
    }


def _verdicts(
    name: str,
    result: dict[str, Any],
    quintiles: dict[str, float | None],
    segments: dict[str, Any],
    cohort: dict[str, Any],
    runoff: dict[str, Any],
) -> dict[str, Any]:
    t = TOLERANCES
    checks: dict[str, Any] = {}
    monthly = result["cpr_proxy"]["monthly"]
    observed_cpr = float(np.mean([r["cpr_observed"] for r in monthly]) * 100) if monthly else 0.0
    bias = result["cpr_proxy"]["bias_pp"]
    t1 = _tolerance(observed_cpr, t["T1_cpr_bias_pp"])
    checks["T1"] = {
        "value_pp": bias,
        "tolerance_pp": t1,
        "pass": bias is not None and abs(bias) <= t1,
    }

    twelve = cohort.get("horizons", {}).get("12m")
    if twelve is not None:
        realized = float(twelve["realized_aalen_johansen_prepay"]) * 100
        model = float(twelve["models"][name]["hindsight_rates"]["prepay"]) * 100
        t2 = _tolerance(realized, t["T2_incidence_12m_pp"])
        bounds = cohort.get("censoring_sensitivity", {})
        incidence = bounds.get("prepay_incidence", {})
        interpretable = True
        if bounds.get("horizon_months") == 12 and incidence:
            low = float(incidence["bound_censored_never_pay_off"]) * 100
            high = float(incidence["bound_censored_all_pay_off"]) * 100
            interpretable = realized - t2 <= low and high <= realized + t2
        checks["T2"] = {
            "error_pp": model - realized,
            "tolerance_pp": t2,
            "interpretable": interpretable,
            "pass": abs(model - realized) <= t2 if interpretable else None,
        }
    hindsight = runoff.get("models", {}).get(name, {}).get("hindsight_rates")
    observed = runoff.get("observed", {})
    if hindsight is not None and "12m" in hindsight["pool_factor_error_pp"]:
        error = float(hindsight["pool_factor_error_pp"]["12m"])
        paydown = (1.0 - float(observed["pool_factor"]["12m"])) * 100
        rule = t["T3_pool_factor_12m_pp"]
        limit = max(rule["absolute_pp"], rule["relative_of_paydown"] * paydown)
        checks["T3"] = {"error_pp": error, "tolerance_pp": limit, "pass": abs(error) <= limit}
    if hindsight is not None and runoff.get("horizon_months") == 24:
        error = float(hindsight["wal_error_years"])
        shortening = 2.0 - float(observed["wal_truncated_years"])
        rule = t["T4_wal_24m_years"]
        limit = max(rule["absolute_years"], rule["relative_of_shortening"] * shortening)
        checks["T4"] = {"error_years": error, "tolerance_years": limit, "pass": abs(error) <= limit}

    cells = [
        cell
        for dimension in segments["dimensions"].values()
        for cell in dimension.values()
        if "suppressed" not in cell and not cell["low_event"]
    ]
    poor = sum(bool(c["poorly_served"]) for c in cells)
    share = poor / len(cells) if cells else 0.0
    checks["T5"] = {
        "cells": len(cells),
        "poorly_served": poor,
        "share": share,
        "pass": share <= t["T5_poorly_served_share"]["max_share"],
        "incentive_cells": {
            label: segments["dimensions"].get("incentive_bps", {}).get(label)
            for label in ("<-200", "[-200,-100)")
        },
    }
    expected = result["prepay"]["mean_predicted"] * result["rows"]
    ae = result["events"]["prepay"] / expected if expected > 0 else None
    rule6 = t["T6_calibration"]
    quintiles_ok = all(
        v is not None and rule6["quintile_ae_low"] <= v <= rule6["quintile_ae_high"]
        for v in quintiles.values()
    )
    checks["T6"] = {
        "payoff_ae": ae,
        "quintile_ae": quintiles,
        "pass": ae is not None and rule6["ae_low"] <= ae <= rule6["ae_high"] and quintiles_ok,
    }
    required = ["T1", "T2", "T3", "T5", "T6"] + (["T4"] if "T4" in checks else [])
    passed = [checks.get(k, {}).get("pass") for k in required]
    return {
        "checks": checks,
        "fit_for_stated_use": all(p is True for p in passed),
        "undetermined": [k for k, p in zip(required, passed, strict=True) if p is None],
    }


def _monotone_reference(batch: PanelBatch) -> PanelBatch:
    """A deterministic spread of rows (every k-th row) for the monotonicity report."""
    step = max(1, batch.rows // MONOTONE_REFERENCE_ROWS)
    index = np.arange(0, batch.rows, step)[:MONOTONE_REFERENCE_ROWS]
    return PanelBatch(
        loan_id=batch.loan_id[index],
        target_month=batch.target_month[index],
        outcome_class=batch.outcome_class[index],
        exposure_upb=batch.exposure_upb[index],
        features={k: v[index] for k, v in batch.features.items()},
        loan_code=None if batch.loan_code is None else batch.loan_code[index],
    )


def _score(
    registration: Registration,
    data_root: Path,
    first: int,
    last: int,
    *,
    stages: dict[str, dict[str, float]],
) -> dict[str, Any]:
    """Every registered model on target months ``first..last``; cohort t0 = ``first - 1``."""
    from prepay.resources import peak_rss_bytes

    clock = time.perf_counter()

    def stage(name: str) -> None:
        nonlocal clock
        now = time.perf_counter()
        stages[name] = {"seconds": round(now - clock, 1), "peak_rss_bytes": peak_rss_bytes()}
        clock = now

    models = _predictors(registration)
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        rates = rate_path_from_warehouse(con)
        batch = augment(read_panel(con, first, last), rates)
        if batch.rows == 0:
            raise ForwardError("no at-risk rows in the scored months")
        stage("read")
        access = _ForwardAccess(registration)
        history = rate_path_from_bronze(data_root / "bronze")
        cohort = cohort_backtest(con, models, history, first - 1, seal=access, cutoff_month=last)
        runoff = runoff_backtest(con, models, history, first - 1, seal=access, cutoff_month=last)
        stage("cohort_and_runoff")
    finally:
        con.close()
    predictions = {name: model.predict_proba(batch) for name, model in models.items()}
    results = {name: metrics.evaluate(batch, p) for name, p in predictions.items()}
    stage("predict_and_metrics")
    clusters = batch.clusters()
    tests: dict[str, dict[str, Any]] = {}
    for comparison in (Comparison(**c) for c in registration.payload["comparisons"]):
        difference = metrics.row_log_loss(
            predictions[comparison.candidate], batch.outcome_class
        ) - metrics.row_log_loss(predictions[comparison.reference], batch.outcome_class)
        tests[comparison.id] = {
            **asdict(comparison),
            **paired_test(
                clusters,
                difference,
                months=batch.target_month,
                method=str(registration.payload.get("interval_method", "loan_cluster")),
                replicates=int(registration.payload["replicates"]),
            ),
        }
    for family in ("primary", "secondary"):
        members = {k: float(v["p_one_sided"]) for k, v in tests.items() if v["family"] == family}
        for key, decision in holm(members, float(registration.payload["alpha"])).items():
            tests[key]["holm"] = decision
    stage("paired_tests")
    verdicts = {
        name: _verdicts(
            name,
            results[name],
            quintile_ae(batch, predictions[name]),
            segment_report(batch, {name: predictions[name]}, selected=name),
            cohort,
            runoff,
        )
        for name in models
    }
    stage("tolerances_and_segments")
    reference = _monotone_reference(batch)
    monotone = {name: monotonicity(model, reference) for name, model in models.items()}
    stage("monotonicity")
    regimes = row_regimes(batch, rates)
    return {
        "scored_months": f"{periods.to_iso(first)}..{periods.to_iso(last)}",
        "regime_of_scored_rows": {
            key: dict(zip(*np.unique(values.astype(str), return_counts=True), strict=True))
            for key, values in regimes.items()
        },
        "scope": "verdicts hold for the regime of these months only (ADR 0010 §6)",
        "metrics": results,
        "comparisons": tests,
        "tolerance_verdicts": verdicts,
        "monotonicity": monotone,
        "cohort_backtest": cohort,
        "runoff_backtest": runoff,
        "definitions": {
            "low_event_payoffs": LOW_EVENTS,
            "poorly_served_band": list(POOR_BAND),
            "tolerances": TOLERANCES,
            "interval_method": registration.payload.get("interval_method", "loan_cluster"),
        },
    }


def evaluate(
    registry_dir: Path,
    data_root: Path,
    lock: DataLock,
    *,
    member_dirs: Mapping[str, Path] | None = None,
) -> Path:
    """Score every registered model on forward months, once per data lock (ADR 0010)."""
    registration = load_registration(registry_dir, member_dirs)
    forward_months = check_forward_lock(registration, lock)
    out_dir = registry_dir / EVALUATIONS
    target = out_dir / f"{lock.fingerprint()[:16]}.json"
    if target.exists():
        raise ForwardError(f"{target.name} exists; each lock is evaluated once")
    earlier = [read_json(p) for p in sorted(out_dir.glob("*.json"))] if out_dir.is_dir() else []
    primary_opening = not any(report.get("primary_opening") for report in earlier)
    seen = registration.seen_through
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    stages: dict[str, dict[str, float]] = {}
    scored = _score(registration, data_root, seen + 1, cutoff, stages=stages)
    report = {
        "kind": "prepay-forward-evaluation",
        "evidence_class": "synthetic"
        if any(m["synthetic"] for m in registration.payload["members"].values())
        else "forward-confirmatory",
        "primary_opening": primary_opening,
        "registration_digest": registration.payload["registration_digest"],
        "data_lock_fingerprint": lock.fingerprint(),
        "release": lock.release,
        "forward_months": f"{periods.to_iso(seen + 1)}..{periods.to_iso(cutoff)}",
        "forward_month_count": forward_months,
        "evaluated_at_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "stages": stages,
        **scored,
    }
    write_json_atomic(target, _jsonable(report))
    read_only(target)
    return target


def rehearse(
    registry_dir: Path,
    data_root: Path,
    lock: DataLock,
    *,
    member_dirs: Mapping[str, Path] | None = None,
) -> Path:
    """Dress rehearsal on the twelve months up to the seen-through month (members' own lock).

    Runs the evaluation code end to end and records stage times and peak RSS, so the one real
    opening can't fail half way. It reads months the members have already seen (and opened
    holdout months), so its metrics are labeled as a rehearsal and are not evidence. It never
    writes into ``evaluations/`` and doesn't affect the primary opening.
    """
    registration = load_registration(registry_dir, member_dirs)
    fingerprints = {m["data_lock_fingerprint"] for m in registration.payload["members"].values()}
    if lock.fingerprint() not in fingerprints:
        raise ForwardError("a rehearsal uses the members' own lock, not a forward lock")
    seen = registration.seen_through
    stages: dict[str, dict[str, float]] = {}
    scored = _score(registration, data_root, seen - 11, seen, stages=stages)
    from prepay.resources import peak_rss_bytes

    report = {
        "kind": "prepay-forward-rehearsal",
        "evidence_class": "rehearsal (not evidence; reads months the members have seen)",
        "registration_digest": registration.payload["registration_digest"],
        "stages": stages,
        "peak_rss_bytes": peak_rss_bytes(),
        **scored,
    }
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    target = registry_dir / REHEARSALS / f"{stamp}.json"
    write_json_atomic(target, _jsonable(report))
    read_only(target)
    return target


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value
