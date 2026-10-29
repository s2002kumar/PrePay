"""Model run registry: JSON/LightGBM-text artifacts plus a run manifest with every digest.

Layout of ``artifacts/runs/<run_id>/``::

    run-manifest.json      data lock, feature contract, windows, configs, selection, digests
    preprocessor.json      train-only preprocessing parameters
    models/<name>.json     model parameters (and models/M1_lightgbm.txt booster; factored
                           families add models/<name>.credit.txt and models/<name>.payoff.txt)
    validation.json        metrics of every model on Validation A and B
    seal.json              written once by `prepay seal`
    evaluations/first.json written once by `prepay evaluate-lockbox`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prepay.io import atomic_path, read_json, write_json_atomic
from prepay.modeling.challengers import ConstrainedHazard, FactoredGbm
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import (
    GbmModel,
    HazardModel,
    LogisticModel,
    LookupBaseline,
    PsaBaseline,
    TemperatureCalibrated,
)

MANIFEST = "run-manifest.json"


def _write_text(path: Path, text: str) -> None:
    with atomic_path(path) as tmp:
        tmp.write_text(text, encoding="utf-8", newline="\n")


def save_models(run_dir: Path, pre: Preprocessor, models: dict[str, HazardModel]) -> None:
    write_json_atomic(run_dir / "preprocessor.json", pre.to_json())
    for name, model in models.items():
        write_json_atomic(run_dir / "models" / f"{name}.json", model.to_json())
        if isinstance(model, GbmModel):
            _write_text(run_dir / "models" / f"{name}.txt", model.booster_text)
        if isinstance(model, FactoredGbm):
            _write_text(run_dir / "models" / f"{name}.credit.txt", model.credit_text)
            _write_text(run_dir / "models" / f"{name}.payoff.txt", model.payoff_text)


def _load_model(run_dir: Path, name: str, pre: Preprocessor) -> HazardModel:
    payload = read_json(run_dir / "models" / f"{name}.json")
    family = payload["family"]
    if family == PsaBaseline.family:
        return PsaBaseline(credit_rate=float(payload["credit_rate"]), speed=float(payload["speed"]))
    if family == LookupBaseline.family:
        return LookupBaseline(
            table=payload["table"],
            marginal=payload["marginal"],
            prior_strength=float(payload["prior_strength"]),
            age_edges=tuple(payload["age_edges"]),
            incentive_edges=tuple(payload["incentive_edges"]),
        )
    if family == LogisticModel.family:
        return LogisticModel(
            pre, payload["coef"], payload["intercept"], float(payload["c_regularization"])
        )
    if family == GbmModel.family:
        text = (run_dir / "models" / f"{name}.txt").read_text(encoding="utf-8")
        return GbmModel(pre, text, payload["params"], int(payload["best_iteration"]))
    if family == FactoredGbm.family:
        return FactoredGbm(
            pre,
            payload["variant"],
            (run_dir / "models" / f"{name}.credit.txt").read_text(encoding="utf-8"),
            (run_dir / "models" / f"{name}.payoff.txt").read_text(encoding="utf-8"),
            payload["params"],
            {k: int(v) for k, v in payload["iterations"].items()},
        )
    if family == ConstrainedHazard.family:
        return ConstrainedHazard.from_json(payload, pre)
    raise ValueError(f"unknown model family {family!r}")


def training_sample(manifest: dict[str, Any]) -> tuple[float | None, int]:
    """``(fraction, index)`` of a run's loan-hash training sample (primary or experiment)."""
    if "training_sample" in manifest:  # experiment run (ADR 0009 §8)
        sample = manifest["training_sample"]
        return sample["fraction"], int(sample["index"])
    return manifest["training_config"]["train_sample_fraction"], 0


@dataclass(frozen=True)
class Run:
    run_dir: Path
    manifest: dict[str, Any]
    models: dict[str, HazardModel]

    @property
    def selected(self) -> HazardModel:
        """The pre-registered selection, with its calibration if one was adopted."""
        selection = self.manifest["selection"]
        model = self.models[selection["selected"]]
        temperature = selection.get("temperature")
        return TemperatureCalibrated(model, float(temperature)) if temperature else model

    def calibrated(self, name: str) -> HazardModel:
        """Model ``name`` with its own pre-declared calibration.

        Experiment runs decide calibration for every model (ADR 0010 §1). In a primary run
        (ADR 0004) only the selected model has a calibration decision; the others are raw.
        """
        decisions = self.manifest.get("calibration")
        if decisions is None:
            selection = self.manifest["selection"]
            return self.selected if name == selection["selected"] else self.models[name]
        temperature = decisions[name].get("temperature")
        model = self.models[name]
        return TemperatureCalibrated(model, float(temperature)) if temperature else model


def load_run(run_dir: Path) -> Run:
    manifest = read_json(run_dir / MANIFEST)
    pre = Preprocessor.from_json(read_json(run_dir / "preprocessor.json"))
    models = {name: _load_model(run_dir, name, pre) for name in manifest["models"]}
    return Run(run_dir, manifest, models)
