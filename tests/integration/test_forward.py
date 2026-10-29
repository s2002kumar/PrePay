"""Forward evaluation (ADR 0008 mechanism, ADR 0010) end to end on synthetic releases.

Members are trained and sealed on a Release-47-layout synthetic world whose cutoff is 2025-06.
The shared Release-48 world (cutoff 2026-06) then plays the later release: it holds exactly 12
forward months.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
import stat
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from prepay import periods
from prepay.cli import main
from prepay.evaluation import forward as forward_module
from prepay.evaluation.forward import (
    ADR0010_COMPARISONS,
    ForwardError,
    check_forward_lock,
    evaluate,
    holm,
    load_registration,
    paired_test,
    register,
)
from prepay.features.panel import PanelBatch
from prepay.ingest import ingest_all
from prepay.ingest.lock import DataLock, create_lock
from prepay.modeling.experiment import preset, run_experiment
from prepay.modeling.lockbox import seal
from prepay.modeling.train import TrainingConfig, train
from prepay.synthetic.dataset import generate_dataset
from prepay.transform import run_dbt
from tests.conftest import TINY_CONFIG

FAST = TrainingConfig(logistic_c_grid=(0.1,), gbm_num_leaves_grid=(7,), gbm_max_rounds=60)
EARLIER = dataclasses.replace(TINY_CONFIG, last_vintage=2025, cutoff="2025-06", release=47)
COMPARISONS = tuple(c for c in ADR0010_COMPARISONS if "REFIT2026" not in c.candidate + c.reference)


@pytest.fixture(scope="module")
def earlier_world(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, DataLock]:
    source = tmp_path_factory.mktemp("earlier-source")
    generate_dataset(EARLIER, source)
    root = tmp_path_factory.mktemp("earlier")
    lock = create_lock(
        source / "raw", release=47, terms_reference="", synthetic_manifest=source / "manifest.json"
    )
    ingest_all(source / "raw", lock, root / "bronze")
    run_dbt(root, lock)
    return root, lock


@pytest.fixture(scope="module")
def members(
    earlier_world: tuple[Path, DataLock], tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Path]:
    root, lock = earlier_world
    runs = tmp_path_factory.mktemp("member-runs")
    primary = train(root, lock, runs, FAST)
    dev = run_experiment(
        root,
        lock,
        runs,
        dataclasses.replace(
            preset("DEV2017", periods.month(2025, 6)),
            gbm_num_leaves_grid=(7,),
            gbm_max_rounds=60,
            hazard_l2_grid=(1e-3,),
        ),
    )
    for run_dir in (primary, dev):
        seal(run_dir)
    return {"REF": primary, "DEV2017": dev}


@pytest.fixture(scope="module")
def registry(
    members: dict[str, Path],
    earlier_world: tuple[Path, DataLock],
    tmp_path_factory: pytest.TempPathFactory,
) -> Path:
    directory = tmp_path_factory.mktemp("registry")
    register(directory, members, earlier_world[1], comparisons=COMPARISONS)
    return directory


@pytest.fixture(scope="module")
def first_report(
    registry: Path, built: tuple[Path, DataLock]
) -> tuple[dict, list[tuple[int, int]]]:
    root, lock = built
    requested: list[tuple[int, int]] = []
    original = forward_module.read_panel

    def spy(con: object, first: int, last: int, **kwargs: object) -> PanelBatch:
        requested.append((first, last))
        return original(con, first, last, **kwargs)  # type: ignore[arg-type]

    forward_module.read_panel = spy  # type: ignore[assignment]
    try:
        target = evaluate(registry, root, lock)
    finally:
        forward_module.read_panel = original
    return json.loads(target.read_text(encoding="utf-8")), requested


def test_registration_is_write_once_and_tied_to_the_members_lock(
    registry: Path,
    members: dict[str, Path],
    earlier_world: tuple[Path, DataLock],
    built: tuple[Path, DataLock],
    tmp_path: Path,
) -> None:
    registration = load_registration(registry)
    assert registration.payload["seen_through"] == "2025-06"
    assert {c["id"] for c in registration.payload["comparisons"]} == {
        "P1",
        "P2",
        "P3",
        "P4",
        "S1",
        "S2",
        "S3",
    }
    with pytest.raises(ForwardError, match="written once"):
        register(registry, members, earlier_world[1], comparisons=COMPARISONS)
    with pytest.raises(ForwardError, match="registering data lock"):
        register(tmp_path, members, built[1], comparisons=COMPARISONS)
    with pytest.raises(ForwardError, match="unknown model"):
        register(tmp_path / "x", members, earlier_world[1])  # REFIT2026 comparisons, no member


def test_forward_locks_must_be_new_later_and_long_enough(
    registry: Path, earlier_world: tuple[Path, DataLock], built: tuple[Path, DataLock]
) -> None:
    registration = load_registration(registry)
    assert check_forward_lock(registration, built[1]) == 12
    with pytest.raises(ForwardError, match="own lock"):
        check_forward_lock(registration, earlier_world[1])

    def fake(release: int, cutoff: str) -> SimpleNamespace:
        return SimpleNamespace(
            fingerprint=lambda: "f" * 64, release=release, performance_cutoff_month=cutoff
        )

    with pytest.raises(ForwardError, match="later Freddie Mac release"):
        check_forward_lock(registration, fake(47, "2026-06"))  # type: ignore[arg-type]
    with pytest.raises(ForwardError, match="no interim looks"):
        check_forward_lock(registration, fake(48, "2026-05"))  # type: ignore[arg-type]


def test_the_first_evaluation_reads_only_forward_months(
    first_report: tuple[dict, list[tuple[int, int]]],
) -> None:
    report, requested = first_report
    assert requested
    assert min(first for first, _ in requested) == periods.month(2025, 7)
    assert report["primary_opening"] is True
    assert report["forward_months"] == "2025-07..2026-06"
    assert report["forward_month_count"] == 12
    assert report["evidence_class"] == "synthetic"


def test_the_report_holds_families_tolerances_and_scope(
    first_report: tuple[dict, list[tuple[int, int]]],
) -> None:
    report, _ = first_report
    comparisons = report["comparisons"]
    for key in ("P1", "P2", "P3", "P4", "S1", "S2", "S3"):
        assert {"estimate", "low", "high", "p_one_sided", "holm"} <= set(comparisons[key])
    primary = [comparisons[k]["holm"]["p_holm"] for k in ("P1", "P2", "P3", "P4")]
    assert all(0.0 < p <= 1.0 for p in primary)
    verdicts = report["tolerance_verdicts"]
    assert "REF/selected" in verdicts
    assert "DEV2017/selected" not in verdicts  # experiment runs never select
    for verdict in verdicts.values():
        assert {"T1", "T2", "T3", "T5", "T6"} <= set(verdict["checks"])
        assert "T4" not in verdict["checks"]  # only 12 forward months
        assert isinstance(verdict["fit_for_stated_use"], bool)
    assert set(report["regime_of_forward_rows"]) == {"level_band", "rate_change_6m", "new_low"}
    assert "regime" in report["scope"]


def test_each_lock_is_evaluated_once(
    first_report: tuple[dict, list[tuple[int, int]]], registry: Path, built: tuple[Path, DataLock]
) -> None:
    root, lock = built
    with pytest.raises(ForwardError, match="evaluated once"):
        evaluate(registry, root, lock)
    lock_path = registry.parent / "built.lock.json"
    lock_path.write_text(json.dumps(lock.to_json()), encoding="utf-8")
    code = main(
        [
            "forward",
            "evaluate",
            "--registry",
            str(registry),
            "--data-root",
            str(root),
            "--lock",
            str(lock_path),
        ]
    )
    assert code == 1  # the CLI reports the same refusal as a failure


def test_tampered_members_or_registrations_are_refused(
    members: dict[str, Path],
    earlier_world: tuple[Path, DataLock],
    built: tuple[Path, DataLock],
    tmp_path: Path,
) -> None:
    copies = {}
    for label, run_dir in members.items():
        copies[label] = tmp_path / label / run_dir.name
        shutil.copytree(run_dir, copies[label])
    directory = tmp_path / "registry"
    register(directory, copies, earlier_world[1], comparisons=COMPARISONS)

    model = copies["DEV2017"] / "models" / "X1_factored_gbm.payoff.txt"
    model.write_text(model.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ForwardError, match="DEV2017"):
        evaluate(directory, built[0], built[1])

    target = directory / "forward-registration.json"
    os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
    payload = json.loads(target.read_text(encoding="utf-8"))
    payload["tolerances"]["T3_pool_factor_12m_pp"]["absolute_pp"] = 5.0
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ForwardError, match="modified"):
        load_registration(directory)


def test_holm_and_the_paired_bootstrap() -> None:
    decisions = holm({"a": 0.01, "b": 0.04, "c": 0.03})
    assert decisions["a"]["p_holm"] == pytest.approx(0.03)
    assert decisions["c"]["p_holm"] == pytest.approx(0.06)
    assert decisions["b"]["p_holm"] == pytest.approx(0.06)  # monotone step-down
    assert decisions["a"]["reject"] is True
    assert decisions["b"]["reject"] is False
    rng = np.random.default_rng(3)
    clusters = np.repeat(np.arange(500), 4)
    better = paired_test(clusters, rng.normal(-0.01, 0.02, 2000), replicates=400)
    worse = paired_test(clusters, rng.normal(0.01, 0.02, 2000), replicates=400)
    assert better["p_one_sided"] < 0.01
    assert better["high"] < 0
    assert worse["p_one_sided"] > 0.99
