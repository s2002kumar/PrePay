"""Model run registry: JSON/LightGBM-text artifacts plus a run manifest with every digest.

Layout of ``artifacts/runs/<run_id>/``::

    run-manifest.json      data lock, feature contract, windows, configs, selection, digests
    preprocessor.json      train-only preprocessing parameters
    models/<name>.json     model parameters (and models/M1_lightgbm.txt booster)
    validation.json        metrics of every model on Validation A and B
    seal.json              written once by `prepay seal`
    evaluations/first.json written once by `prepay evaluate-lockbox`
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from prepay.io import atomic_path, read_json, write_json_atomic
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


def save_models(run_dir: Path, pre: Preprocessor, models: dict[str, HazardModel]) -> None:
    write_json_atomic(run_dir / "preprocessor.json", pre.to_json())
    for name, model in models.items():
        write_json_atomic(run_dir / "models" / f"{name}.json", model.to_json())
        if isinstance(model, GbmModel):
            with atomic_path(run_dir / "models" / f"{name}.txt") as tmp:
                tmp.write_text(model.booster_text, encoding="utf-8", newline="\n")


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
    raise ValueError(f"unknown model family {family!r}")


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


def load_run(run_dir: Path) -> Run:
    manifest = read_json(run_dir / MANIFEST)
    pre = Preprocessor.from_json(read_json(run_dir / "preprocessor.json"))
    models = {name: _load_model(run_dir, name, pre) for name in manifest["models"]}
    return Run(run_dir, manifest, models)
