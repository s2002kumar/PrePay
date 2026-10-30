"""Implementation checks for an experiment run that reveal nothing about its accuracy (R2).

Every check is a boolean software invariant. None is a metric, a rate or a distribution, so the
result can be shared even while real-data outputs stay private (ADR 0009 §3).

- **Manifest:** complete, trained by clean code (no dirty tree), on the expected lock and preset.
- **Seal:** present and verifying (artifacts unchanged since sealing).
- **Reload:** two independent loads predict bit-identically, and every row is a coherent simplex.
- **Level invariance** (X1-X3, H1): shifting the market and note rates together by +250 bp, with
  the PMMS method flag flipped, leaves predictions bit-identical.
- **Monotone hazard** (X1-X3, H1): the payoff hazard never falls as incentive rises, and never
  rises with burnout where constrained.
- **Derived parity:** derived features from panel rows and warehouse rates equal those from the
  state machine and bronze rates.

All of these gate ``all_pass``.

Fitted-model *properties* are reported separately and don't gate ``all_pass``. For each model:
whether any step along a coherent incentive grid lowers the final payoff probability by more
than 1e-6 a month (the ADR 0010 amendment 2 materiality). ADR 0008 allows the factored families'
unconstrained credit hazard to cause such a decrease, so a ``False`` there is a finding, not a
bug.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import duckdb
import numpy as np

from prepay import periods
from prepay.features.batch import PanelBatch
from prepay.features.derived import DERIVED_NUMERIC, augment
from prepay.features.machine import compute_features
from prepay.features.panel import (
    load_statics,
    rate_path_from_bronze,
    rate_path_from_warehouse,
)
from prepay.ingest.lock import DataLock
from prepay.io import read_json
from prepay.modeling.challengers import (
    VARIANTS,
    ConstrainedHazard,
    FactoredGbm,
    ice_violation_share,
)
from prepay.modeling.experiment import EXPERIMENT_KIND, preset, setter
from prepay.modeling.lockbox import SEAL, SealError, load_seal
from prepay.modeling.registry import MANIFEST, load_run
from prepay.modeling.windows import Window, read_window
from prepay.transform import warehouse_path

REQUIRED_KEYS = (
    "run_id",
    "experiment_id",
    "evidence_class",
    "data_lock_fingerprint",
    "feature_contract_digest",
    "derived_feature_version",
    "software_lock_digest",
    "git_sha",
    "git_dirty",
    "duckdb_version",
    "windows",
    "config_digest",
    "training_sample",
    "models",
    "selection",
    "calibration",
)
SAMPLE_FRACTION = 0.02
MAX_ROWS = 5000
LEVEL_SHIFT_PCT = 2.5
INCENTIVE_GRID = tuple(float(v) for v in range(-400, 301, 50))
BURNOUT_GRID = tuple(float(v) for v in range(0, 121, 12))


class _PayoffHazard:
    def __init__(self, model: FactoredGbm | ConstrainedHazard) -> None:
        self.model = model

    def predict_proba(self, batch: PanelBatch) -> np.ndarray:
        _, h = self.model.hazards(batch)
        return np.column_stack([1.0 - h, h, np.zeros_like(h)])


def _sample(con: duckdb.DuckDBPyConnection, manifest: dict[str, Any]) -> PanelBatch:
    window = manifest["windows"]["calibrate"]
    batch = read_window(
        con,
        Window(
            "verify",
            "validation",
            periods.parse_iso(window["first"]),
            periods.parse_iso(window["last"]),
        ),
        sample_fraction=SAMPLE_FRACTION,
    )
    return batch.slice(0, min(batch.rows, MAX_ROWS))


def _level_shift(batch: PanelBatch) -> PanelBatch:
    def column(name: str) -> np.ndarray:
        return np.asarray(batch.features[name], dtype=np.float64)

    return replace(
        batch,
        features={
            **batch.features,
            "market_rate_t1": column("market_rate_t1") + LEVEL_SHIFT_PCT,
            "note_rate_pct": column("note_rate_pct") + LEVEL_SHIFT_PCT,
            "pmms_application_based": 1.0 - column("pmms_application_based"),
        },
    )


def verify_run(
    run_dir: Path, data_root: Path, lock: DataLock, *, preset_name: str | None = None
) -> dict[str, Any]:
    """Boolean implementation checks for one experiment run."""
    from prepay.evaluation.forward import monotonicity

    manifest = read_json(run_dir / MANIFEST)
    checks: dict[str, bool] = {
        "manifest_complete": all(key in manifest for key in REQUIRED_KEYS),
        "experiment_kind": manifest.get("kind") == EXPERIMENT_KIND,
        "clean_code": manifest.get("git_dirty") is False,
        "trained_on_this_lock": manifest.get("data_lock_fingerprint") == lock.fingerprint(),
    }
    if preset_name is not None:
        expected = preset(preset_name, periods.parse_iso(lock.performance_cutoff_month))
        windows = expected.windows.windows()
        checks["preset_windows_match"] = all(
            manifest["windows"].get(name, {}).get("first") == periods.to_iso(w.first)
            and manifest["windows"].get(name, {}).get("last") == periods.to_iso(w.last)
            for name, w in windows.items()
            if name != "train"
        ) and manifest["windows"]["train"]["last"] == periods.to_iso(windows["train"].last)
        checks["preset_models_match"] = list(manifest["models"]) == list(expected.models)
    if (run_dir / SEAL).is_file():
        try:
            load_seal(run_dir)
            checks["seal_intact"] = True
        except SealError:
            checks["seal_intact"] = False
    else:
        checks["seal_intact"] = False

    with duckdb.connect(str(warehouse_path(data_root)), read_only=True) as con:
        rates = rate_path_from_warehouse(con)
        loan_ids, statics = load_statics(con)
        batch = augment(_sample(con, manifest), rates)
    checks["sample_has_rows"] = batch.rows > 0
    position = {lid: i for i, lid in enumerate(loan_ids)}
    loan_index = np.array([position[lid] for lid in batch.loan_id], dtype=np.int64)
    bronze = rate_path_from_bronze(data_root / "bronze")
    machine = augment(
        PanelBatch(
            loan_id=batch.loan_id,
            target_month=batch.target_month,
            outcome_class=batch.outcome_class,
            exposure_upb=batch.exposure_upb,
            features=compute_features(statics, bronze, loan_index, batch.target_month),
        ),
        bronze,
    )
    checks["derived_feature_parity"] = all(
        np.allclose(
            np.asarray(batch.features[n], dtype=float),
            np.asarray(machine.features[n], dtype=float),
            rtol=1e-12,
            atol=1e-9,
            equal_nan=True,
        )
        for n in DERIVED_NUMERIC
    )

    properties: dict[str, bool] = {}
    first, second = load_run(run_dir), load_run(run_dir)
    for name in first.models:
        model = first.calibrated(name)
        p = model.predict_proba(batch)
        checks[f"{name}.reload_identical"] = bool(
            np.array_equal(p, second.calibrated(name).predict_proba(batch))
        )
        checks[f"{name}.coherent"] = bool(
            np.all(p >= 0) and np.allclose(p.sum(axis=1), 1.0, atol=1e-9)
        )
        base = first.models[name]
        if isinstance(base, FactoredGbm | ConstrainedHazard):
            checks[f"{name}.level_invariant"] = bool(
                np.array_equal(p, model.predict_proba(_level_shift(batch)))
            )
            hazard = _PayoffHazard(base)
            checks[f"{name}.hazard_monotone_incentive"] = (
                ice_violation_share(
                    hazard, batch, setter("incentive_bps"), INCENTIVE_GRID, direction=1
                )
                == 0.0
            )
            constrained_burnout = isinstance(base, ConstrainedHazard) or (
                "burnout_months" in VARIANTS[base.variant].payoff_monotone
            )
            if constrained_burnout:
                checks[f"{name}.hazard_monotone_burnout"] = (
                    ice_violation_share(
                        hazard, batch, setter("burnout_months"), BURNOUT_GRID, direction=-1
                    )
                    == 0.0
                )
        report = monotonicity(model, batch)
        properties[f"{name}.no_material_payoff_decrease"] = (
            report["share_rows_with_material_decrease"] == 0.0
        )
    failed = sorted(k for k, ok in checks.items() if not ok)
    return {
        "kind": "prepay-run-verification",
        "run_id": manifest.get("run_id"),
        "preset": preset_name,
        "checks": checks,
        "failed": failed,
        "properties": properties,
        "all_pass": not failed,
        "note": "boolean software invariants only; no metric, rate or distribution",
    }
