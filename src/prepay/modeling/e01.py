"""Experiment E01: out-of-range generalization on the rolling-origin folds (ADR 0014).

Everything E01 decides is fixed here, before any real-data run:

- the six ADR 0009 §4 origins and their regime classes (§4, from public PMMS rates);
- the families (§5), with B0 and B1 as references;
- the three comparison families with Bonferroni-simultaneous intervals, and the
  non-inferiority margin (§6);
- the reading rules R1-R7 (§7), computed by :func:`summarize`, never by hand.

E01 reads outcome months up to 2019-12 only. It is **development evidence (E1)** and
exploratory: it never confirms an improvement, and its regime classes are analogues of later
periods, not evidence about them. It doesn't read or change the forward study (ADR 0010).

Jobs (each runs in its own process under :mod:`prepay.modeling.e01_run`):

- :func:`run_fold` trains a fold fresh (or reuses it under an exact provenance match) and writes
  ``evaluations/e01.json``;
- :func:`run_stability` runs the S1 stability diagnostics (D6 samples, D7 seeds);
- :func:`summarize` and :func:`render_report` build the summary and the owner's local report.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from prepay import periods
from prepay.evaluation.forward import _verdicts, quintile_ae
from prepay.evaluation.regimes import regime_dimensions
from prepay.evaluation.segments import LOW_EVENTS, MIN_LOANS, POOR_BAND, segment_report
from prepay.evaluation.simultaneous import (
    FAMILY_ALPHA,
    REPLICATES,
    SEED,
    CellGroups,
    bonferroni_z,
    classify,
    month_block_mean,
    paired,
    ratio,
    simultaneous,
    two_way_suite,
)
from prepay.features.derived import DERIVED_VERSION, augment
from prepay.features.panel import rate_path_from_warehouse
from prepay.ingest.lock import DataLock
from prepay.io import read_json, write_json_atomic
from prepay.modeling import metrics
from prepay.modeling.experiment import (
    PROVENANCE_FIELDS,
    SUPPORT_PROFILE,
    V1_ORIGINS,
    ExperimentConfig,
    ExperimentWindows,
    evaluate_fold,
    find_or_run,
    preset,
)
from prepay.modeling.lockbox import read_only
from prepay.modeling.probes import probe_models
from prepay.modeling.registry import MANIFEST
from prepay.modeling.windows import Window, read_window
from prepay.provenance import (
    canonical_digest,
    feature_contract_digest,
    git_sha,
    software_lock_digest,
)
from prepay.reliability.support import SupportProfile
from prepay.resources import StageRecorder
from prepay.transform import warehouse_path

log = logging.getLogger(__name__)

EXPERIMENT = "E01"
ADR = "0014"
LABEL = (
    "Development evidence (E1), exploratory. Outcome months up to 2019-12 only. Not "
    "confirmation of performance on 2020-2026 or on any future month (ADR 0014)."
)
#: ADR 0014 §4, from public FRED PMMS rates (docs/reviews/gate-a/fold-regimes.json).
REGIME_SHIFT = ("2007-12", "2009-12", "2011-12", "2013-12")
CONTROL = ("2015-12", "2017-12")
ORIGINS = tuple(periods.to_iso(o) for o in V1_ORIGINS)
TRAIN_SAMPLE_FRACTION = 0.1
FOLD_REPORT = Path("evaluations") / "e01.json"
SUMMARY = "e01-summary.json"
REPORT = "e01-report.md"

B0, B1, B2, M1 = "B0_psa", "B1_lookup", "B2_logistic", "M1_lightgbm"
X1, X2, X3, H1 = "X1_factored_gbm", "X2_factored_gbm", "X3_factored_gbm", "H1_constrained_hazard"
FAMILIES = (B0, B1, B2, M1, X1, X2, X3, H1)
CANDIDATES = (B2, M1, X1, X2, X3, H1)
REFERENCES = (B0, B1)

#: ADR 0014 §6 comparison families (candidate, reference); each spans every fold.
COMPARISON_FAMILIES: dict[str, tuple[tuple[str, str], ...]] = {
    "F-M1": tuple((c, M1) for c in (B2, X1, X2, X3, H1)),
    "F-B2": tuple((c, B2) for c in (M1, X1, X2, X3, H1)),
    "F-DESIGN": ((X1, M1), (X2, X1), (X3, X2), (H1, X2), (H1, B2)),
}
#: ADR 0014 §7 R3: what each design pair bundles (from the model code).
DESIGN_BUNDLES: dict[tuple[str, str], dict[str, Any]] = {
    (X1, M1): {
        "single_choice": False,
        "differs_in": "factored two-booster structure vs joint softmax; market_rate_t1, "
        "note_rate_pct and pmms_application_based removed from both boosters; payoff hazard "
        "non-decreasing in incentive",
    },
    (X2, X1): {
        "single_choice": True,
        "differs_in": "only the burnout constraint (payoff hazard non-increasing in burnout); "
        "each model is still tuned on its own",
    },
    (X3, X2): {
        "single_choice": False,
        "differs_in": "three derived behavioral features (new opportunity, new five-year low, "
        "payment saving %), each constrained non-decreasing",
    },
    (H1, X2): {
        "single_choice": False,
        "differs_in": "penalized logistic with piecewise-linear terms vs trees; logit-linear vs "
        "flat tails; H1 drops loan size and remaining payments, adds new opportunity, hinge and "
        "seasonal terms; different credit model",
    },
    (H1, B2): {
        "single_choice": False,
        "differs_in": "factored vs joint form; monotone constraints; no rate levels or loan "
        "size; different bases and features",
    },
}
#: ADR 0014 §6: non-inferiority margin, relative to the reference's mean log loss in the fold.
MARGIN_RELATIVE = 0.005
#: ADR 0014 §7 R2/R3: classes needed in at least this many of the four regime-shift folds.
SHIFT_MAJORITY = 3
#: ADR 0014 §8 S1.
S1: dict[str, tuple[str, ...]] = {
    "samples": (B2, M1, X2, H1),
    "seeds": (M1, X2),
}
STABILITY_REPLICATES = 5
#: Families fitted by convex optimization without a seed: their seed SD is zero by construction.
SEEDLESS = (B0, B1, B2, H1)
#: D2 flags that block a nomination (R7). ``flat_extrapolation`` is informational (ADR 0009 §6).
BLOCKING_D2_FLAGS = ("incentive_ice_violations", "burnout_ice_violations", "level_raises_payoffs")
PROBE_REFERENCE_FRACTION = 0.02


class E01Error(RuntimeError):
    """A requested E01 step violates the pre-registration (ADR 0014)."""


@dataclasses.dataclass(frozen=True)
class Overrides:
    """Settings for synthetic test worlds only; a real-data lock refuses every override."""

    origins: tuple[str, ...] = ORIGINS
    train_sample_fraction: float | None = TRAIN_SAMPLE_FRACTION
    config: tuple[tuple[str, Any], ...] = ()
    replicates: int = REPLICATES
    stability_replicates: int = STABILITY_REPLICATES

    @classmethod
    def from_json(cls, payload: Mapping[str, Any] | None) -> Overrides:
        if not payload:
            return cls()
        unknown = set(payload) - {f.name for f in dataclasses.fields(cls)}
        if unknown:
            raise E01Error(f"unknown overrides {sorted(unknown)}")
        values = dict(payload)
        if "origins" in values:
            values["origins"] = tuple(values["origins"])
        if "config" in values:
            values["config"] = tuple(
                (k, tuple(v) if isinstance(v, list) else v) for k, v in values["config"].items()
            )
        return cls(**values)

    def is_default(self) -> bool:
        return self == Overrides()

    def check(self, lock: DataLock) -> None:
        if not lock.synthetic and not self.is_default():
            raise E01Error("E01 settings are fixed by ADR 0014; overrides need a synthetic lock")
        unknown = set(self.origins) - set(ORIGINS)
        if unknown:
            raise E01Error(f"origins outside ADR 0014 §4: {sorted(unknown)}")


def regime_class(origin: str) -> str:
    if origin in REGIME_SHIFT:
        return "regime_shift"
    if origin in CONTROL:
        return "control"
    raise E01Error(f"{origin} is not an ADR 0014 origin")


def fold_config(origin: str, overrides: Overrides = Overrides()) -> ExperimentConfig:  # noqa: B008
    """The E01 fold of ``origin``: ADR 0009 §4 windows, every E01 family, fraction 0.1."""
    config = ExperimentConfig(
        f"{EXPERIMENT}-{origin}",
        ExperimentWindows.rolling_origin(periods.parse_iso(origin)),
        FAMILIES,
        designated=B2,
        train_sample_fraction=overrides.train_sample_fraction,
        sample_index=0,
    )
    return dataclasses.replace(config, **dict(overrides.config))


def stability_config(kind: str, cutoff_month: int, overrides: Overrides) -> ExperimentConfig:
    """S1 base configuration: the DEV2017 windows, the S1 families of ``kind``."""
    if kind not in S1:
        raise E01Error(f"stability kind must be one of {sorted(S1)}")
    windows = preset("DEV2017", cutoff_month).windows
    config = ExperimentConfig(
        f"{EXPERIMENT}-S1",
        windows,
        S1[kind],
        designated=S1[kind][0],
        train_sample_fraction=overrides.train_sample_fraction,
    )
    return dataclasses.replace(config, **dict(overrides.config))


# --------------------------------------------------------------------------- execution identity
#: What one E01 execution is bound to (Gate B review, 2026-11-10). The pilot, the folds and S1
#: share every field; a change of code, dependency lock, data lock, features or configuration
#: starts a new E01 directory and a new pilot. Runs of different revisions are never mixed.
IDENTITY_FIELDS = (
    "git_sha",
    "software_lock_digest",
    "data_lock_fingerprint",
    "feature_contract_digest",
    "derived_feature_version",
    "configuration_digest",
)
#: The identity fields that every run manifest records too.
RUN_IDENTITY_FIELDS = IDENTITY_FIELDS[:-1]


def protocol() -> dict[str, Any]:
    """ADR 0014's fixed settings as data: origins, families, comparisons, margin, rules and S1."""
    return {
        "experiment": EXPERIMENT,
        "adr": ADR,
        "regime_shift": REGIME_SHIFT,
        "control": CONTROL,
        "families": FAMILIES,
        "comparison_families": COMPARISON_FAMILIES,
        "design_bundles": {f"{a} vs {b}": v for (a, b), v in DESIGN_BUNDLES.items()},
        "margin_relative": MARGIN_RELATIVE,
        "shift_majority": SHIFT_MAJORITY,
        "s1": S1,
        "seedless": SEEDLESS,
        "blocking_d2_flags": BLOCKING_D2_FLAGS,
        "probe_reference_fraction": PROBE_REFERENCE_FRACTION,
        "bootstrap": {"seed": SEED, "family_alpha": FAMILY_ALPHA},
    }


def execution_identity(lock: DataLock, overrides: Overrides) -> dict[str, Any]:
    """The identity an E01 execution would have now.

    ``configuration_digest`` covers the protocol, the overrides, and every fold and S1
    configuration, so a protocol edit changes the identity even in a synthetic test's dirty tree.
    """
    cutoff = periods.parse_iso(lock.performance_cutoff_month)
    configuration = {
        "protocol": protocol(),
        "overrides": dataclasses.asdict(overrides),
        "folds": {o: dataclasses.asdict(fold_config(o, overrides)) for o in overrides.origins},
        "stability": {k: dataclasses.asdict(stability_config(k, cutoff, overrides)) for k in S1},
    }
    return {
        "git_sha": git_sha(),
        "software_lock_digest": software_lock_digest(),
        "data_lock_fingerprint": lock.fingerprint(),
        "feature_contract_digest": feature_contract_digest(),
        "derived_feature_version": DERIVED_VERSION,
        "configuration_digest": canonical_digest(configuration),
    }


def identity_digest(identity: Mapping[str, Any]) -> str:
    return canonical_digest({k: identity.get(k) for k in IDENTITY_FIELDS})


def identity_mismatches(provenance: Mapping[str, Any], identity: Mapping[str, Any]) -> list[str]:
    """The identity fields in which a run's recorded provenance differs from ``identity``."""
    return [k for k in RUN_IDENTITY_FIELDS if provenance.get(k) != identity.get(k)]


# --------------------------------------------------------------------------- fold job
def folds_dir(root: Path) -> Path:
    return root / "folds"


def stability_dir(root: Path) -> Path:
    return root / "stability"


def run_fold(
    data_root: Path,
    lock: DataLock,
    root: Path,
    origin: str,
    overrides: Overrides = Overrides(),  # noqa: B008
) -> tuple[Path, str]:
    """Train (or reuse) the fold of ``origin`` and write its E01 evaluation once.

    Returns ``(run_dir, status)``, status ``evaluated`` or ``reused``. A run whose provenance
    differs, or an interrupted run directory, is refused (ADR 0014 §9.1).
    """
    overrides.check(lock)
    if origin not in overrides.origins:
        raise E01Error(f"{origin} is not among this E01 run's origins")
    regime_class(origin)
    config = fold_config(origin, overrides)
    run_dir, reused = find_or_run(
        data_root, lock, folds_dir(root), config, evaluate=False, save_support=True
    )
    target = run_dir / FOLD_REPORT
    if target.is_file():
        return run_dir, "reused"
    report = evaluate_e01(
        run_dir,
        data_root,
        lock,
        origin,
        replicates=overrides.replicates,
    )
    write_json_atomic(target, report)
    read_only(target)
    log.info("E01 fold evaluated", extra={"origin": origin, "reused_training": reused})
    return run_dir, "evaluated"


def _cell_groups(batch: Any, rates: Any) -> tuple[dict[str, CellGroups], dict[str, Any]]:
    """ADR 0009 §5 regime cells: row codes per dimension, and loans and payoffs per cell."""
    groups: dict[str, CellGroups] = {}
    counts: dict[str, Any] = {}
    clusters = batch.clusters()
    payoff = batch.outcome_class == 1
    for dimension in regime_dimensions(rates):
        labels = tuple(dimension.labels)
        distinct, inverse = np.unique(dimension.assign(batch).astype(str), return_inverse=True)
        position = {label: i for i, label in enumerate(labels)}
        mapped = np.array([position.get(str(v), -1) for v in distinct], dtype=np.int64)
        codes = mapped[np.asarray(inverse, dtype=np.int64).reshape(-1)]
        groups[dimension.name] = CellGroups(labels, codes)
        counts[dimension.name] = {
            label: {
                "loans": int(np.unique(clusters[codes == i]).shape[0]),
                "payoffs": int(payoff[codes == i].sum()),
            }
            for i, label in enumerate(labels)
            if (codes == i).any()
        }
    return groups, counts


def evaluate_e01(
    run_dir: Path,
    data_root: Path,
    lock: DataLock,
    origin: str,
    *,
    replicates: int = REPLICATES,
    seed: int = SEED,
) -> dict[str, Any]:
    """The E01 fold report: the development report plus every ADR 0014 §6 measure."""
    stage = StageRecorder()
    fold = evaluate_fold(run_dir, data_root, lock, stage)
    manifest = read_json(run_dir / MANIFEST)
    batch, predictions, rates = fold.batch, fold.predictions, fold.rates
    models = tuple(name for name in FAMILIES if name in predictions)
    y = batch.outcome_class
    log_loss = np.column_stack([metrics.row_log_loss(predictions[m], y) for m in models])
    payoff = np.column_stack([predictions[m][:, 1] for m in models])
    groups, cell_counts = _cell_groups(batch, rates)
    suite = two_way_suite(
        batch.clusters(),
        batch.target_month,
        models,
        log_loss,
        payoff,
        (y == 1).astype(np.float64),
        groups,
        replicates=replicates,
        seed=seed,
    )
    del log_loss, payoff
    stage("two_way_bootstrap")

    pairs: dict[tuple[str, str], list[str]] = {}
    for family, members in COMPARISON_FAMILIES.items():
        for pair in members:
            pairs.setdefault(pair, []).append(family)
    for candidate in CANDIDATES:
        for reference in REFERENCES:
            pairs.setdefault((candidate, reference), []).append("reference")
    comparisons = [
        {**paired(suite, a, b), "families": tags}
        for (a, b), tags in pairs.items()
        if a in models and b in models
    ]

    cells: dict[str, Any] = {}
    for dim, group in groups.items():
        cells[dim] = {}
        for k, label in enumerate(group.labels):
            if label not in cell_counts[dim]:
                continue
            info = dict(cell_counts[dim][label])
            if info["loans"] < MIN_LOANS:
                cells[dim][label] = {"suppressed": f"fewer than {MIN_LOANS} loans"}
                continue
            info["low_event"] = info["payoffs"] < LOW_EVENTS
            info["models"] = {
                m: ratio(suite.cell_ae[dim][k, j], suite.cell_ae_draws[dim][:, k, j])
                for j, m in enumerate(models)
            }
            cells[dim][label] = info

    results = fold.report["metrics"]
    cpr = {}
    for m in models:
        monthly = results[m]["cpr_proxy"]["monthly"]
        errors = np.array([(r["cpr_model"] - r["cpr_observed"]) * 100 for r in monthly])
        cpr[m] = {**month_block_mean(errors, replicates=replicates, seed=seed), "unit": "pp"}
    tolerances = {
        m: _verdicts(
            m,
            results[m],
            quintile_ae(batch, predictions[m]),
            segment_report(batch, {m: predictions[m]}, selected=m),
            fold.cohort,
            fold.runoff,
        )
        for m in models
    }
    stage("tolerances")

    support_path = run_dir / SUPPORT_PROFILE
    support: dict[str, Any]
    if support_path.is_file():
        profile = SupportProfile.from_json(read_json(support_path))
        support = {
            "rows": profile.assess(batch.features),
            "balance": profile.assess(batch.features, batch.exposure_upb),
        }
    else:
        support = {"note": "the run has no support profile"}
    rows = batch.rows
    calibrate = manifest["windows"]["calibrate"]
    reference_window = Window(
        "reference",
        "validation",
        periods.parse_iso(calibrate["first"]),
        periods.parse_iso(calibrate["last"]),
    )
    con: duckdb.DuckDBPyConnection = duckdb.connect(str(warehouse_path(data_root)), read_only=True)
    try:
        probe_rows = augment(
            read_window(con, reference_window, sample_fraction=PROBE_REFERENCE_FRACTION),
            rate_path_from_warehouse(con),
        )
    finally:
        con.close()
    probes = probe_models(fold.models, probe_rows, manifest.get("feature_support"))
    stage("probes")
    return {
        "kind": "prepay-e01-fold",
        "experiment": EXPERIMENT,
        "adr": ADR,
        "evidence_class": fold.report["evidence_class"],
        "label": LABEL,
        "origin": origin,
        "regime_class": regime_class(origin),
        "window": fold.report["window"],
        "run_id": manifest["run_id"],
        "synthetic": manifest["synthetic"],
        "provenance": {k: manifest.get(k) for k in (*PROVENANCE_FIELDS, "git_dirty")},
        "models": list(models),
        "evaluation_rows": rows,
        "bootstrap": {"method": "two_way pigeonhole (loan x month)", "replicates": replicates},
        "log_loss": {m: float(suite.mean_log_loss[j]) for j, m in enumerate(models)},
        "comparisons": comparisons,
        "payoff_ae": {
            m: ratio(suite.payoff_ae[j], suite.payoff_ae_draws[:, j]) for j, m in enumerate(models)
        },
        "fifth_ae": {
            m: {
                k: ratio(suite.fifth_ae[k][j], suite.fifth_ae_draws[k][:, j])
                for k in ("bottom", "top")
            }
            for j, m in enumerate(models)
        },
        "regime_cells": cells,
        "cpr_bias_pp": cpr,
        "tolerances": tolerances,
        "probes": {"reference_rows": probes["reference_rows"], "flags": probes["flags"]},
        "probe_curves": probes["probes"],
        "support": support,
        "development": fold.report,
        "stages": stage.stages,
    }


# --------------------------------------------------------------------------- stability job
def run_stability(
    data_root: Path,
    lock: DataLock,
    root: Path,
    kind: str,
    overrides: Overrides = Overrides(),  # noqa: B008
) -> Path:
    """S1 (ADR 0014 §8): D6 samples or D7 seeds; replicate runs resume by provenance."""
    from prepay.modeling.diagnostics import stability

    overrides.check(lock)
    base = stability_config(kind, periods.parse_iso(lock.performance_cutoff_month), overrides)

    def runner(data: Path, lk: DataLock, out: Path, config: ExperimentConfig) -> Path:
        return find_or_run(data, lk, out, config)[0]

    return stability(
        data_root,
        lock,
        stability_dir(root),
        kind=kind,
        base=base,
        replicates=overrides.stability_replicates,
        experiment_prefix=f"{EXPERIMENT}-",
        runner=runner,
    )


# --------------------------------------------------------------------------- summary
def _fold_reports(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    base = folds_dir(root)
    if not base.is_dir():
        return out
    for run_dir in sorted(base.iterdir()):
        target = run_dir / FOLD_REPORT
        if target.is_file():
            report = read_json(target)
            out[report["origin"]] = report
    return out


def _stability_reports(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    base = stability_dir(root)
    for kind in S1:
        found = sorted(base.glob(f"stability-{kind}-*.json")) if base.is_dir() else []
        if found:
            out[kind] = read_json(found[-1])
    return out


def _stability_sd(stability: Mapping[str, Any]) -> dict[str, dict[str, float | None]]:
    """Measured SDs of tune-window log loss per family; seedless families have seed SD 0."""
    out: dict[str, dict[str, float | None]] = {}
    for kind in S1:
        report = stability.get(kind)
        measured = report["families"] if report else {}
        out[kind] = {}
        for family in FAMILIES:
            if family in measured:
                out[kind][family] = float(measured[family]["tune_log_loss_sd"])
            elif kind == "seeds" and family in SEEDLESS:
                out[kind][family] = 0.0
            else:
                out[kind][family] = None
    return out


def _fragility(estimate: float, sds: Mapping[str, float | None], a: str, b: str) -> str:
    sa, sb = sds.get(a), sds.get(b)
    if sa is None or sb is None:
        return "not_assessable"
    return "fragile" if abs(estimate) < max(sa, sb) else "not_fragile"


def summarize(
    root: Path,
    *,
    origins: Sequence[str] = ORIGINS,
    ledger: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The E01 summary: every comparison classified, and R1-R7 as computed fields.

    ``origins`` are the run's declared folds: all six for real data (a synthetic test world may
    declare fewer). Each family's Bonferroni size counts its comparisons over every declared
    fold, whether or not the fold has finished, so the intervals don't widen as folds arrive.

    With a ledger, every fold and S1 run must have the ledger's execution identity.
    """
    _check_run_identities(root, ledger)
    folds = {o: r for o, r in _fold_reports(root).items() if o in origins}
    stability = _stability_reports(root)
    sds = _stability_sd(stability)
    expected = [o for o in ORIGINS if o in origins]
    family_sizes = {f: len(members) * len(expected) for f, members in COMPARISON_FAMILIES.items()}
    z = {f: bonferroni_z(n) for f, n in family_sizes.items()}

    comparisons: list[dict[str, Any]] = []
    for origin, report in sorted(folds.items()):
        for entry in report["comparisons"]:
            margin = MARGIN_RELATIVE * float(entry["reference_log_loss"])
            for family in entry["families"]:
                row = {
                    "origin": origin,
                    "regime_class": report["regime_class"],
                    "family": family,
                    **{k: entry[k] for k in ("candidate", "reference", "estimate", "se")},
                    "relative_to_reference": entry["relative_to_reference"],
                    "unadjusted_low": entry["unadjusted_low"],
                    "unadjusted_high": entry["unadjusted_high"],
                    "margin": margin,
                    "sampling_fragility": _fragility(
                        entry["estimate"], sds["samples"], entry["candidate"], entry["reference"]
                    ),
                    "seed_fragility": _fragility(
                        entry["estimate"], sds["seeds"], entry["candidate"], entry["reference"]
                    ),
                }
                if family in z:
                    low, high = simultaneous(entry["estimate"], entry["se"], z[family])
                    row |= {
                        "simultaneous_low": low,
                        "simultaneous_high": high,
                        "class": classify(low, high, margin),
                    }
                else:
                    row["class"] = "descriptive_only"
                comparisons.append(row)

    def classes(family: str, candidate: str, reference: str) -> dict[str, str]:
        return {
            c["origin"]: c["class"]
            for c in comparisons
            if c["family"] == family and c["candidate"] == candidate and c["reference"] == reference
        }

    rules = {
        "R1_description": _r1(folds, comparisons),
        "R2_consistency": {
            family: {
                candidate: _r2(classes(family, candidate, reference), expected)
                for candidate, reference in COMPARISON_FAMILIES[family]
            }
            for family in ("F-M1", "F-B2")
        },
        "R3_design_bundles": {
            f"{a} - {b}": {
                **DESIGN_BUNDLES[(a, b)],
                **_r3(classes("F-DESIGN", a, b), expected),
            }
            for a, b in COMPARISON_FAMILIES["F-DESIGN"]
        },
        "R4_calibration_transfer": _r4(folds),
        "R5_financial_materiality": _r5(folds),
        "R6_stability": {
            "role": "robustness diagnostic; not a test or a gate (ADR 0014 §7 R6)",
            "tune_log_loss_sd": sds,
            "unstable_flags": {
                kind: {f: v["unstable"] for f, v in report["families"].items()}
                for kind, report in stability.items()
            },
        },
    }
    rules["R7_nomination"] = _r7(folds, rules["R2_consistency"], comparisons)
    complete = len(folds) == len(expected) and set(stability) == set(S1)
    first = next(iter(folds.values()), None)
    return {
        "kind": "prepay-e01-summary",
        "experiment": EXPERIMENT,
        "adr": ADR,
        "label": LABEL,
        "evidence_class": first["evidence_class"] if first else None,
        "synthetic": first["synthetic"] if first else None,
        "complete": complete,
        "folds_expected": expected,
        "folds_completed": sorted(folds),
        "stability_completed": sorted(stability),
        "definitions": {
            "difference": "candidate minus reference mean log loss, nats per loan-month; "
            "negative = candidate has lower loss",
            "simultaneous_interval": f"Wald, estimate +/- z x two-way bootstrap SE; z for "
            f"familywise alpha {FAMILY_ALPHA} (Bonferroni) over each family's size",
            "family_sizes": family_sizes,
            "z": z,
            "margin": f"{MARGIN_RELATIVE:.1%} of the reference's mean log loss in the fold",
            "classes": {
                "lower_loss": "simultaneous interval entirely below 0",
                "higher_loss": "simultaneous interval entirely above 0",
                "non_inferior": "upper limit below the margin; lower loss not shown",
                "inconclusive": "neither; not evidence of equivalence or non-inferiority",
                "descriptive_only": "a reference comparison (B0, B1): unadjusted interval only",
            },
            "regime_shift_origins": list(REGIME_SHIFT),
            "control_origins": list(CONTROL),
            "shift_majority": SHIFT_MAJORITY,
        },
        "folds": {origin: _fold_digest(report) for origin, report in sorted(folds.items())},
        "comparisons": comparisons,
        "rules": rules,
        "provenance": {
            origin: {"run_id": report["run_id"], **report["provenance"]}
            for origin, report in sorted(folds.items())
        },
        "ledger": _ledger_digest(ledger),
    }


def _fold_digest(report: Mapping[str, Any]) -> dict[str, Any]:
    """The per-fold numbers the reading rules and the local report use."""
    dev = report["development"]
    out: dict[str, Any] = {
        "regime_class": report["regime_class"],
        "window": report["window"],
        "evaluation_rows": report["evaluation_rows"],
        "log_loss": report["log_loss"],
        "brier": {m: dev["metrics"][m]["brier"] for m in report["models"]},
        "payoff_ae": report["payoff_ae"],
        "fifth_ae": report["fifth_ae"],
        "cpr_bias_pp": report["cpr_bias_pp"],
        "cpr_mae_pp": {m: dev["metrics"][m]["cpr_proxy"]["mae_pp"] for m in report["models"]},
        "support": {
            weighting: {
                k: report["support"].get(weighting, {}).get(k)
                for k in ("verdict", "outside_share", "sparse_share")
            }
            for weighting in ("rows", "balance")
        },
        "d2_flags": report["probes"]["flags"],
        "tolerances": {
            m: {
                k: v.get("pass")
                for k, v in report["tolerances"][m]["checks"].items()
                if isinstance(v, dict)
            }
            for m in report["models"]
        },
        "cohort_attribution": dev["cohort_attribution"],
        "runoff": {
            m: dev["runoff_backtest"].get("models", {}).get(m, {}) for m in report["models"]
        },
        "stages": report["stages"],
    }
    return out


def _r1(folds: Mapping[str, Any], comparisons: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ranks: dict[str, list[int]] = {}
    gaps: dict[str, list[float]] = {}
    per_fold: dict[str, list[str]] = {}
    for origin, report in sorted(folds.items()):
        losses = report["log_loss"]
        order = sorted(losses, key=losses.__getitem__)
        per_fold[origin] = order
        best = losses[order[0]]
        for name, value in losses.items():
            ranks.setdefault(name, []).append(order.index(name) + 1)
            gaps.setdefault(name, []).append((value - best) / best if best > 0 else 0.0)
    counts: dict[str, dict[str, dict[str, int]]] = {}
    for c in comparisons:
        if c["family"] in ("F-M1", "F-B2"):
            entry = counts.setdefault(c["family"], {}).setdefault(c["candidate"], {})
            entry[c["class"]] = entry.get(c["class"], 0) + 1
    return {
        "note": "point estimates; ranks are descriptive, not tests",
        "order_by_fold": per_fold,
        "mean_rank": {n: float(np.mean(v)) for n, v in sorted(ranks.items())},
        "worst_relative_gap_to_fold_best": {n: float(max(v)) for n, v in sorted(gaps.items())},
        "class_counts": counts,
    }


def _r2(by_fold: Mapping[str, str], expected: Sequence[str]) -> dict[str, Any]:
    shift = [o for o in REGIME_SHIFT if o in expected]
    control = [o for o in CONTROL if o in expected]
    missing = [o for o in (*shift, *control) if o not in by_fold]
    lower = sum(by_fold.get(o) == "lower_loss" for o in shift)
    controls_ok = all(by_fold.get(o) in ("lower_loss", "non_inferior") for o in control)
    needed = min(SHIFT_MAJORITY, len(shift))
    if missing:
        result = "incomplete"
    elif lower >= needed and controls_ok:
        result = "consistent_advantage"
    elif lower >= needed:
        result = "advantage_on_shift_folds_control_loss_not_ruled_out"
    else:
        result = "no_consistent_advantage"
    return {
        "result": result,
        "lower_loss_shift_folds": lower,
        "shift_folds": shift,
        "classes": dict(by_fold),
        "reading": "a consistency pattern in development data, not proof of generalization",
    }


def _r3(by_fold: Mapping[str, str], expected: Sequence[str]) -> dict[str, Any]:
    shift = [o for o in REGIME_SHIFT if o in expected]
    needed = min(SHIFT_MAJORITY, len(shift))
    lower = sum(by_fold.get(o) == "lower_loss" for o in shift)
    higher = sum(by_fold.get(o) == "higher_loss" for o in shift)
    if any(o not in by_fold for o in shift):
        result = "incomplete"
    elif lower >= needed:
        result = "consistently_lower_loss"
    elif higher >= needed:
        result = "consistently_higher_loss"
    else:
        result = "no_consistent_difference"
    return {
        "result": result,
        "classes": dict(by_fold),
        "reading": "a comparison of bundled design choices; no single cause is attributed",
    }


def _r4(folds: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for origin, report in sorted(folds.items()):
        for dim, cells in report["regime_cells"].items():
            for label, cell in cells.items():
                if "suppressed" in cell or cell["low_event"]:
                    continue
                for model, ae in cell["models"].items():
                    entry = out.setdefault(model, {"transfers": True, "outside_band": []})
                    low, high = ae["low"], ae["high"]
                    inside = (
                        low is not None
                        and high is not None
                        and POOR_BAND[0] <= low
                        and high <= POOR_BAND[1]
                    )
                    if not inside:
                        entry["transfers"] = False
                        entry["outside_band"].append(f"{origin} {dim}={label}")
    return {
        "rule": f"every regime cell with >= {LOW_EVENTS} payoffs has its unadjusted two-way A/E "
        f"interval inside {list(POOR_BAND)} in every fold (a diagnostic)",
        "models": out,
    }


def _r5(folds: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for origin, report in sorted(folds.items()):
        for model, verdict in report["tolerances"].items():
            checks = verdict["checks"]
            flags = {
                key: {
                    "error": checks[key].get("error_pp", checks[key].get("error_years")),
                    "tolerance": checks[key].get(
                        "tolerance_pp", checks[key].get("tolerance_years")
                    ),
                    "within_tolerance": checks[key].get("pass"),
                }
                for key in ("T3", "T4")
                if key in checks
            }
            out.setdefault(origin, {})[model] = flags
    return {"note": "hindsight-rate run-off errors vs ADR 0010 T3/T4; descriptive", "folds": out}


def _r7(
    folds: Mapping[str, Any],
    r2: Mapping[str, Any],
    comparisons: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for candidate, _ in COMPARISON_FAMILIES["F-M1"]:
        reasons = []
        if r2["F-M1"][candidate]["result"] != "consistent_advantage":
            reasons.append("R2 vs M1 does not hold")
        higher_b2 = [
            c["origin"]
            for c in comparisons
            if c["family"] == "F-B2" and c["candidate"] == candidate and c["class"] == "higher_loss"
        ]
        if higher_b2:
            reasons.append(f"higher loss than B2 in {', '.join(higher_b2)}")
        flagged = sorted(
            f"{origin}: {flag}"
            for origin, report in folds.items()
            for flag in BLOCKING_D2_FLAGS
            if report["probes"]["flags"].get(candidate, {}).get(flag)
        )
        if flagged:
            reasons.append("D2 flags to explain: " + "; ".join(flagged))
        out[candidate] = {"nominated": not reasons, "reasons": reasons}
    return {
        "rule": "R2 holds vs M1, never higher loss than B2, no blocking D2 flag (ADR 0014 §7)",
        "note": "a recommendation to the owner only; registration is a separate decision and is "
        "judged only on months after its own seen-through date",
        "candidates": out,
        "nominated": sorted(c for c, v in out.items() if v["nominated"]),
    }


def _check_run_identities(root: Path, ledger: Mapping[str, Any] | None) -> None:
    """Refuse to summarize runs made under another execution identity than the ledger's."""
    identity = (ledger or {}).get("identity")
    if identity is None:
        return
    foreign = [
        str(report["run_id"])
        for report in _fold_reports(root).values()
        if identity_mismatches(report["provenance"], identity)
    ]
    base = stability_dir(root)
    runs = sorted(p for p in base.iterdir() if (p / MANIFEST).is_file()) if base.is_dir() else []
    foreign += [p.name for p in runs if identity_mismatches(read_json(p / MANIFEST), identity)]
    if foreign:
        raise E01Error(f"runs of another execution identity can't be summarized: {foreign}")


def _ledger_digest(ledger: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not ledger:
        return None
    return {
        "identity_digest": ledger.get("identity_digest"),
        "reproduction": next(
            (j.get("reproduction") for j in ledger.get("jobs", []) if j.get("reproduction")),
            None,
        ),
        "waiver": ledger.get("waiver"),
    }


def write_summary(
    root: Path, *, origins: Sequence[str] = ORIGINS, ledger: Mapping[str, Any] | None = None
) -> Path:
    """Write ``e01-summary.json`` (rewritten as folds finish) and the owner's local report."""
    from prepay.modeling.e01_report import render_report

    summary = summarize(root, origins=origins, ledger=ledger)
    target = root / SUMMARY
    write_json_atomic(target, summary)
    (root / REPORT).write_text(render_report(summary), encoding="utf-8", newline="\n")
    return target
