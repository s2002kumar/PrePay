"""The public demo bundle: a sealed, synthetic-trained run plus fictional-world inputs.

``build_bundle`` runs the whole research pipeline on fictional data (generate, lock, ingest,
transform, train, seal, lockbox) and copies only public-safe artifacts. ``load_bundle``
refuses any bundle or run not marked synthetic, or whose seal no longer verifies, so a model
trained on restricted data can't be served by accident (ARCHITECTURE §5, §8).
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from prepay.features.machine import RatePath
from prepay.io import read_json, write_json_atomic
from prepay.modeling.lockbox import load_seal
from prepay.modeling.registry import Run, load_run
from prepay.provenance import git_sha, tree_digest
from prepay.reliability.support import SupportProfile

BUNDLE_MANIFEST = "bundle-manifest.json"
NOTICE = (
    "Fictional portfolio and synthetic-trained model for demonstration only. Not Freddie Mac "
    "data, not a forecast of real mortgages, and not financial advice."
)


class BundleError(RuntimeError):
    """The demo bundle is missing, not synthetic, or fails integrity checks."""


@dataclass(frozen=True)
class DemoBundle:
    root: Path
    manifest: dict[str, Any]
    run: Run
    rates: RatePath
    model_quality: dict[str, Any]
    profile: SupportProfile | None = None  # R1 applicability monitor (ADR 0009 §7)

    @property
    def support(self) -> dict[str, dict[str, float]]:
        return dict(self.run.manifest.get("feature_support", {}))


def load_bundle(root: Path) -> DemoBundle:
    manifest_path = root / BUNDLE_MANIFEST
    if not manifest_path.is_file():
        raise BundleError(f"no demo bundle at {root}; build one with `prepay demo build`")
    manifest = read_json(manifest_path)
    run_dir = root / "run"
    run = load_run(run_dir)
    if manifest.get("synthetic") is not True or run.manifest.get("synthetic") is not True:
        raise BundleError("refusing to serve a bundle or model not marked synthetic")
    load_seal(run_dir)  # raises if any artifact changed after sealing
    if tree_digest(root, exclude=(BUNDLE_MANIFEST,)) != manifest["content_digest"]:
        raise BundleError("bundle contents differ from its manifest digest")
    rates_payload = read_json(root / "rates.json")
    rates = RatePath(
        first_month=int(rates_payload["first_month"]),
        rate_30y=np.asarray(rates_payload["rate_30y"], dtype=np.float64),
        rate_15y=np.asarray(rates_payload["rate_15y"], dtype=np.float64),
        application_based=np.asarray(rates_payload["application_based"], dtype=bool),
    )
    support = root / "support.json"
    profile = SupportProfile.from_json(read_json(support)) if support.is_file() else None
    return DemoBundle(root, manifest, run, rates, read_json(root / "model_quality.json"), profile)


def _quality_summary(run_dir: Path) -> dict[str, Any]:
    manifest = read_json(run_dir / "run-manifest.json")
    validation = read_json(run_dir / "validation.json")
    first = read_json(run_dir / "evaluations" / "first.json")

    def compact(result: dict[str, Any]) -> dict[str, Any]:
        return {
            "rows": result["rows"],
            "events": result["events"],
            "log_loss": result["log_loss"],
            "log_loss_interval": result.get("log_loss_interval"),
            "brier": result["brier"],
            "prepay_auroc": result["prepay"]["auroc"],
            "prepay_ece": result["prepay"]["ece"],
            "prepay_reliability": result["prepay"]["reliability"],
            "credit_average_precision": result["credit"]["average_precision"],
            "credit_prevalence": result["credit"]["prevalence"],
            "cpr_proxy_bias_pp": result["cpr_proxy"]["bias_pp"],
            "cpr_proxy_mae_pp": result["cpr_proxy"]["mae_pp"],
            "cpr_proxy_monthly": result["cpr_proxy"]["monthly"],
        }

    models = list(manifest["models"])
    holdout = {}
    for window, result in first["results"].items():
        if "selected" not in result:
            continue
        holdout[window] = {
            "label": result["window"],
            "models": {m: compact(result[m]) for m in [*models, "selected"]},
            "flags": {
                k: v
                for k, v in result["_flags"].items()
                if k not in ("paired_difference_vs", "gbm_vs_baselines")
            },
            "gbm_vs_baselines": result["_flags"]["gbm_vs_baselines"],
        }
    return {
        "synthetic": True,
        "notice": "Metrics on fictional synthetic data only; not evidence of real-world accuracy.",
        "run_id": manifest["run_id"],
        "windows": manifest["windows"],
        "selection": manifest["selection"],
        "validation": {
            m: {w: compact(validation[m][w]) for w in ("validation_a", "validation_b")}
            for m in models
        },
        "truth_recovery": validation.get("_truth_recovery"),
        "holdout": holdout,
        "cohort_backtests": first["cohort_backtests"],
        "real_data_status": "Real-data evaluation runs privately; no real-data result is "
        "published in this demo.",
    }


def _force_remove(function: Any, path: str, _: BaseException) -> None:
    """Seals and first evaluations are written read-only; clear the flag to rebuild."""
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    function(path)


def assemble_bundle(
    out: Path,
    run_dir: Path,
    bronze_root: Path,
    *,
    preset: str,
    support_profile: SupportProfile | None = None,
) -> Path:
    """Copy a sealed, lockbox-evaluated synthetic run plus its rate history into ``out``.

    ``support_profile`` (fitted on the run's own training rows) lets the API state whether each
    projection is inside the model's training support.
    """
    from prepay.features.panel import rate_path_from_bronze

    if read_json(run_dir / "run-manifest.json").get("synthetic") is not True:
        raise BundleError("only runs trained on synthetic data can be bundled")
    load_seal(run_dir)
    rates = rate_path_from_bronze(bronze_root)
    if out.exists():
        shutil.rmtree(out, onexc=_force_remove)
    shutil.copytree(run_dir, out / "run")
    write_json_atomic(
        out / "rates.json",
        {
            "source": "synthetic weekly PMMS-format series (prepay synth); fictional values",
            "first_month": rates.first_month,
            "rate_30y": rates.rate_30y.tolist(),
            "rate_15y": rates.rate_15y.tolist(),
            "application_based": rates.application_based.tolist(),
        },
    )
    write_json_atomic(out / "model_quality.json", _quality_summary(run_dir))
    if support_profile is not None:
        write_json_atomic(out / "support.json", support_profile.to_json())
    write_json_atomic(
        out / BUNDLE_MANIFEST,
        {
            "kind": "prepay-demo-bundle",
            "synthetic": True,
            "notice": NOTICE,
            "preset": preset,
            "git_sha": git_sha(),
            "content_digest": tree_digest(out, exclude=(BUNDLE_MANIFEST,)),
        },
    )
    load_bundle(out)  # verify what was written
    return out


def build_bundle(out: Path, *, preset: str = "ci", work_dir: Path | None = None) -> Path:
    """Run the fictional pipeline end to end and assemble a verified bundle at ``out``."""
    from prepay.ingest import ingest_all
    from prepay.ingest.lock import create_lock
    from prepay.modeling.lockbox import evaluate_lockbox, seal
    from prepay.modeling.train import train
    from prepay.reliability.support import profile_for_run
    from prepay.synthetic.config import PRESETS
    from prepay.synthetic.dataset import generate_dataset
    from prepay.transform import run_dbt

    with tempfile.TemporaryDirectory(dir=work_dir) as tmp:
        work = Path(tmp)
        config = dataclasses.replace(PRESETS[preset], anomalies=False)
        generate_dataset(config, work / "source")
        lock = create_lock(
            work / "source" / "raw",
            release=config.release,
            terms_reference="",
            synthetic_manifest=work / "source" / "manifest.json",
        )
        ingest_all(work / "source" / "raw", lock, work / "data" / "bronze")
        run_dbt(work / "data", lock)
        run_dir = train(work / "data", lock, work / "runs", truth_dir=work / "source" / "truth")
        seal(run_dir)
        evaluate_lockbox(run_dir, work / "data", lock)
        assemble_bundle(
            out,
            run_dir,
            work / "data" / "bronze",
            preset=preset,
            support_profile=profile_for_run(work / "data", run_dir),
        )
        _make_writable(work)
    return out


def _make_writable(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
