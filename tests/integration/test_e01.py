"""E01 (ADR 0014) on the tiny synthetic pipeline: fold reports, resume, safeguards, orchestration.

The tiny world starts in 2006, so these tests declare the later folds through the synthetic-only
overrides; a real-data lock refuses every override.
"""

from __future__ import annotations

import dataclasses
import json
import os
import shutil
from pathlib import Path
from typing import Any

import duckdb
import pytest

from prepay import periods
from prepay.cli import main
from prepay.ingest.lock import DataLock
from prepay.io import read_json
from prepay.modeling import e01, e01_run
from prepay.modeling import experiment as experiment_module
from prepay.modeling import windows as windows_module
from prepay.modeling.e01 import (
    COMPARISON_FAMILIES,
    DESIGN_BUNDLES,
    FAMILIES,
    E01Error,
    Overrides,
    fold_config,
    run_fold,
    summarize,
)
from prepay.modeling.e01_report import PRIVATE_BANNER, SYNTHETIC_BANNER, render_report
from prepay.modeling.experiment import (
    DEVELOPMENT_FAMILIES,
    MANIFEST,
    ExperimentConfig,
    ExperimentWindows,
    ProvenanceError,
    run_experiment,
)
from prepay.provenance import REPO_ROOT

FAST = {
    "logistic_c_grid": [0.1],
    "gbm_num_leaves_grid": [7],
    "gbm_max_rounds": 60,
    "hazard_l2_grid": [1e-3],
}
ORIGINS = ["2013-12", "2015-12", "2017-12"]
OVERRIDES = {
    "origins": ORIGINS,
    "train_sample_fraction": None,
    "config": FAST,
    "replicates": 40,
    "stability_replicates": 2,
}


def _lock_file(lock: DataLock, path: Path) -> Path:
    from prepay.ingest.lock import write_lock

    write_lock(lock, path)
    return path


@pytest.fixture(scope="module")
def e01_root(built: tuple[Path, DataLock], tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Pilot (2013-12) and the other folds, run in process through the CLI, with a V1 twin."""
    root, lock = built
    base = tmp_path_factory.mktemp("e01")
    out = base / "e01"
    overrides = Overrides.from_json(OVERRIDES)
    v1_config = dataclasses.replace(
        fold_config("2013-12", overrides),
        experiment_id="V1-2013-12",
        models=DEVELOPMENT_FAMILIES,
    )
    v1 = run_experiment(root, lock, base / "v1", v1_config)
    lock_path = _lock_file(lock, base / "lock.json")
    common = ["--data-root", str(root), "--lock", str(lock_path), "--out", str(out)]
    common += ["--synthetic-overrides", json.dumps(OVERRIDES)]
    small = ["--min-free-commit-gib", "0", "--budget-commit-gib", "64"]
    assert main(["experiment", "e01", "run", "--stage", "pilot", *common, *small,
                 "--reproduce-against", str(v1)]) == 0  # fmt: skip
    assert main(["experiment", "e01", "run", "--stage", "folds", *common, *small]) == 0
    return out


def test_fold_report_holds_every_pre_registered_measure(e01_root: Path) -> None:
    report = read_json(next((e01_root / "folds").glob("*E01-2015-12*")) / e01.FOLD_REPORT)
    assert report["evidence_class"] == "synthetic"
    assert report["label"].startswith("Development evidence (E1), exploratory")
    assert report["regime_class"] == "control"
    assert report["models"] == list(FAMILIES)  # B0 is now fitted in the fold
    pairs = {(c["candidate"], c["reference"]): c for c in report["comparisons"]}
    for family, members in COMPARISON_FAMILIES.items():
        for pair in members:
            assert family in pairs[pair]["families"]
    assert "reference" in pairs[("X2_factored_gbm", "B1_lookup")]["families"]
    entry = pairs[("X1_factored_gbm", "M1_lightgbm")]
    assert entry["se"] > 0
    assert entry["unadjusted_low"] <= entry["estimate"] <= entry["unadjusted_high"]
    assert set(report["fifth_ae"]["H1_constrained_hazard"]) == {"bottom", "top"}
    assert set(report["regime_cells"]) == {"rate_level_band", "rate_change_6m", "new_low"}
    assert report["cpr_bias_pp"]["B2_logistic"]["kind"] == "month_block_percentile_95"
    assert set(report["tolerances"]["M1_lightgbm"]["checks"]) >= {"T1", "T2", "T3", "T5", "T6"}
    assert "level_raises_payoffs" in report["probes"]["flags"]["M1_lightgbm"]
    assert report["support"]["balance"]["verdict"] in ("supported", "extrapolating", "unsupported")
    stages = [s["stage"] for s in report["stages"]]
    assert stages[:3] == ["load", "cohort_backtest", "runoff_backtest"]
    assert stages[-1] == "probes"
    assert all("process_peak_rss_bytes" in s and "commit_now_bytes" in s for s in report["stages"])


def test_pilot_reproduces_the_v1_model_files_byte_for_byte(e01_root: Path) -> None:
    ledger = read_json(e01_root / e01_run.LEDGER)
    pilot = next(j for j in ledger["jobs"] if j["job"] == "fold 2013-12")
    assert pilot["outcome"] == "ok"
    check = pilot["reproduction"]
    assert check["identical"] is True
    assert check["differing_files"] == []
    assert check["compared_files"] >= 8  # seven V1 families' files plus the preprocessor


def test_ledger_holds_metadata_only(e01_root: Path) -> None:
    ledger = read_json(e01_root / e01_run.LEDGER)
    allowed = {
        "job",
        "started_utc",
        "finished_utc",
        "outcome",
        "exit_code",
        "seconds",
        "peak_commit_bytes",
        "peak_rss_bytes",
        "start_commit_bytes",
        "baseline_commit_bytes",
        "job_peak_bytes",
        "within_budget",
        "free_commit_before_bytes",
        "projected_peak_bytes",
        "reproduction",
        "run_id",
        "verification",
    }
    for job in ledger["jobs"]:
        assert set(job) <= allowed, set(job) - allowed
    assert [j["job"] for j in ledger["jobs"]] == [
        "fold 2013-12",
        "summary",
        "fold 2015-12",
        "fold 2017-12",
        "summary",
    ]
    assert all("projected_peak_bytes" in j for j in ledger["jobs"][2:4])
    for job in (j for j in ledger["jobs"] if j["job"].startswith("fold")):
        # Implementation booleans ran in a child after every fold; only check names are kept.
        assert job["verification"]["gating_failures"] == []
        assert set(job["verification"]["failed_checks"]) <= {"clean_code"}


def test_summary_classifies_every_family_comparison_and_computes_the_rules(
    e01_root: Path,
) -> None:
    summary = summarize(e01_root, origins=ORIGINS, ledger=read_json(e01_root / e01_run.LEDGER))
    assert summary["folds_completed"] == ORIGINS
    assert summary["complete"] is False  # stability S1 hasn't run here
    sizes = summary["definitions"]["family_sizes"]
    assert sizes == {f: len(m) * len(ORIGINS) for f, m in COMPARISON_FAMILIES.items()}
    family_rows = [c for c in summary["comparisons"] if c["family"] in COMPARISON_FAMILIES]
    assert len(family_rows) == sum(sizes.values())
    for row in family_rows:
        assert row["class"] in ("lower_loss", "higher_loss", "non_inferior", "inconclusive")
        assert row["simultaneous_low"] <= row["estimate"] <= row["simultaneous_high"]
        assert row["margin"] > 0
        assert row["sampling_fragility"] == "not_assessable"  # S1 not run: nothing imputed
    rules = summary["rules"]
    assert set(rules["R2_consistency"]["F-M1"]) == {c for c, _ in COMPARISON_FAMILIES["F-M1"]}
    for result in rules["R3_design_bundles"].values():
        assert "no single cause" in result["reading"]
    singles = [k for k, v in rules["R3_design_bundles"].items() if v["single_choice"]]
    assert singles == ["X2_factored_gbm - X1_factored_gbm"]
    assert set(rules["R7_nomination"]["candidates"]) == {c for c, _ in COMPARISON_FAMILIES["F-M1"]}
    assert summary["ledger"]["reproduction"]["identical"] is True


def test_local_report_is_deterministic_and_labeled(e01_root: Path) -> None:
    summary = read_json(e01_root / e01.SUMMARY)
    text = render_report(summary)
    assert text == render_report(summary)
    assert SYNTHETIC_BANNER in text
    assert PRIVATE_BANNER not in text
    assert "Development evidence (E1), exploratory" in text
    assert "not evidence of equivalence" in text
    # Byte-identical on every platform: no CRLF on Windows.
    assert (e01_root / e01.REPORT).read_bytes() == text.encode("utf-8")
    real = {**summary, "synthetic": False}
    assert PRIVATE_BANNER in render_report(real)


def test_report_bytes_do_not_depend_on_platform(tmp_path: Path) -> None:
    """An E01 directory with no folds yet still gets a report, written with LF line endings."""
    e01.write_summary(tmp_path)
    assert read_json(tmp_path / e01.SUMMARY)["complete"] is False
    report = (tmp_path / e01.REPORT).read_bytes()
    assert b"\r" not in report
    assert report == render_report(read_json(tmp_path / e01.SUMMARY)).encode("utf-8")


def test_a_finished_fold_is_reused_without_retraining(
    e01_root: Path, built: tuple[Path, DataLock], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock = built

    def refuse(*args: object, **kwargs: object) -> Path:
        raise AssertionError("a matching fold must be reused, not retrained")

    monkeypatch.setattr(experiment_module, "run_experiment", refuse)
    run_dir, status = run_fold(root, lock, e01_root, "2015-12", Overrides.from_json(OVERRIDES))
    assert status == "reused"
    assert "E01-2015-12" in run_dir.name


def test_a_trained_fold_without_evaluation_is_evaluated_not_retrained(
    built: tuple[Path, DataLock], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock = built
    overrides = Overrides.from_json(OVERRIDES)
    run_experiment(
        root,
        lock,
        e01.folds_dir(tmp_path),
        fold_config("2017-12", overrides),
        evaluate=False,
        save_support=True,
    )

    def refuse(*args: object, **kwargs: object) -> Path:
        raise AssertionError("the trained fold must be evaluated, not retrained")

    monkeypatch.setattr(experiment_module, "run_experiment", refuse)
    requested: list[int] = []
    original = windows_module.read_panel

    def spy(con: duckdb.DuckDBPyConnection, first: int, last: int, **kwargs: object) -> Any:
        requested.append(last)
        return original(con, first, last, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(windows_module, "read_panel", spy)
    run_dir, status = run_fold(root, lock, tmp_path, "2017-12", overrides)
    assert status == "evaluated"
    assert (run_dir / e01.FOLD_REPORT).is_file()
    assert max(requested) <= periods.month(2019, 12)  # development months only


def test_runs_with_other_provenance_or_interrupted_runs_are_refused(
    e01_root: Path, built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    overrides = Overrides.from_json(OVERRIDES)
    source = next((e01_root / "folds").glob("*E01-2015-12*"))
    copy = e01.folds_dir(tmp_path) / source.name
    shutil.copytree(source, copy)
    manifest_path = copy / MANIFEST
    os.chmod(manifest_path, 0o644)
    manifest = read_json(manifest_path)
    manifest["config_digest"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ProvenanceError, match="config_digest"):
        run_fold(root, lock, tmp_path, "2015-12", overrides)
    manifest_path.unlink()
    with pytest.raises(ProvenanceError, match="interrupted"):
        run_fold(root, lock, tmp_path, "2015-12", overrides)


def test_real_data_refuses_overrides_and_loosened_safeguards(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    real = dataclasses.replace(lock, synthetic=False)
    with pytest.raises(E01Error, match="overrides need a synthetic lock"):
        Overrides.from_json(OVERRIDES).check(real)
    lock_path = _lock_file(real, tmp_path / "lock.json")
    outside = tmp_path / "e01"

    def options(**changes: Any) -> e01_run.Options:
        base = e01_run.Options(root, lock_path, outside, "pilot", reproduce_against=tmp_path)
        return dataclasses.replace(base, **changes)

    cases = {
        "only the pilot": options(stage="all"),
        "below 12 GiB": options(min_free_commit_bytes=8 * e01_run.GIB),
        "above 10 GiB": options(budget_bytes=11 * e01_run.GIB),
        "needs --reproduce-against": options(reproduce_against=None),
        "outside the repository": options(root=REPO_ROOT / "e01-out"),
    }
    for message, case in cases.items():
        with pytest.raises(E01Error, match=message.split()[-1]):
            e01_run.check_options(case, real, Overrides())


def test_orchestrator_stops_on_stop_file_preflight_budget_and_mismatch(
    e01_root: Path, built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    root, lock = built
    lock_path = _lock_file(lock, tmp_path / "lock.json")

    def fake_spawn(peak: int, failed: list[str] | None = None) -> e01_run.Spawn:
        def spawn(args: list[str], report: Path) -> int:
            if "verify" in args:  # the implementation-check child writes its own report
                out = Path(args[args.index("--out") + 1])
                out.write_text(json.dumps({"failed": failed or []}))
                return 2 if failed else 0
            report.write_text(json.dumps({"peak_rss_bytes": peak, "peak_commit_bytes": peak}))
            return 0

        return spawn

    def options(out: Path, **changes: Any) -> e01_run.Options:
        base = e01_run.Options(
            root,
            lock_path,
            out,
            "pilot",
            min_free_commit_bytes=0,
            preflight_wait_seconds=0,
            overrides=OVERRIDES,
        )
        return dataclasses.replace(base, **changes)

    stop = tmp_path / "stop"
    stop.mkdir()
    (stop / e01_run.STOP).write_text("")
    assert e01_run.run(options(stop), spawn=fake_spawn(1)) == e01_run.EXIT_STOPPED

    starved = options(tmp_path / "pre", min_free_commit_bytes=10)
    code = e01_run.run(starved, spawn=fake_spawn(1), free_commit=lambda: 1, sleep=lambda s: None)
    assert code == e01_run.EXIT_PREFLIGHT
    assert read_json(tmp_path / "pre" / e01_run.LEDGER)["jobs"][-1]["outcome"] == "preflight_failed"

    # The STOP file ends a preflight wait at its next poll, not after the whole wait.
    waiting = options(tmp_path / "wait", min_free_commit_bytes=10, preflight_wait_seconds=7200)

    def stop_while_waiting(seconds: float) -> None:
        (tmp_path / "wait" / e01_run.STOP).write_text("")

    code = e01_run.run(
        waiting, spawn=fake_spawn(1), free_commit=lambda: 1, sleep=stop_while_waiting
    )
    assert code == e01_run.EXIT_STOPPED
    assert read_json(tmp_path / "wait" / e01_run.LEDGER)["jobs"][-1]["outcome"] == "stopped_by_file"

    heavy = options(tmp_path / "budget", budget_bytes=100)
    assert e01_run.run(heavy, spawn=fake_spawn(101)) == e01_run.EXIT_BUDGET

    # A failed implementation check stops the queue; a dirty tree alone doesn't, on synthetic data.
    checked = tmp_path / "checked"
    shutil.copytree(e01_root / "folds", checked / "folds")
    broken = options(checked, budget_bytes=2**62)
    assert e01_run.run(broken, spawn=fake_spawn(1, ["M1_lightgbm.coherent"])) == e01_run.EXIT_VERIFY
    record = read_json(checked / e01_run.LEDGER)["jobs"][-1]
    assert record["outcome"] == "verification_failed"
    assert record["verification"]["gating_failures"] == ["M1_lightgbm.coherent"]
    assert e01_run.run(broken, spawn=fake_spawn(1, ["clean_code"])) == e01_run.EXIT_OK

    # A pilot whose model files differ from the reference stops, and the folds wait for a waiver.
    mismatch = tmp_path / "mismatch"
    shutil.copytree(e01_root / "folds", mismatch / "folds")
    pilot = next((mismatch / "folds").glob("*E01-2013-12*"))
    v1 = tmp_path / "v1"
    shutil.copytree(pilot, v1)
    os.chmod(v1 / MANIFEST, 0o644)
    manifest = read_json(v1 / MANIFEST)
    manifest["experiment_id"] = "V1-2013-12"
    (v1 / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    booster = v1 / "models" / "M1_lightgbm.txt"
    os.chmod(booster, 0o644)
    booster.write_text(booster.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    pilot_options = options(mismatch, reproduce_against=v1, budget_bytes=2**62)
    assert e01_run.run(pilot_options, spawn=fake_spawn(1)) == e01_run.EXIT_REPRODUCTION
    record = read_json(mismatch / e01_run.LEDGER)["jobs"][-1]
    assert record["reproduction"]["differing_files"] == ["models/M1_lightgbm.txt"]
    folds = options(mismatch, stage="folds", budget_bytes=2**62)
    with pytest.raises(E01Error, match="waive"):
        e01_run.run(folds, spawn=fake_spawn(1))


def test_projection_scales_everything_above_the_baseline_by_the_largest_ratio() -> None:
    pilot = {"start_commit_bytes": 10, "baseline_commit_bytes": 1_000, "job_peak_bytes": 3_000}
    assert e01_run.projected_peak(pilot, (100, 50), (300, 100)) == 1_000 + 2_000 * 3
    assert e01_run.projected_peak(pilot, (100, 50), (50, 25)) == 3_000  # never scaled down
    # Without a post-import baseline the start is used, and fixed costs are scaled too.
    early = {"start_commit_bytes": 10, "job_peak_bytes": 3_000}
    assert e01_run.projected_peak(early, (100, 50), (300, 100)) == 10 + 2_990 * 3


def test_design_bundles_cover_every_design_pair() -> None:
    assert set(DESIGN_BUNDLES) == set(COMPARISON_FAMILIES["F-DESIGN"])


def test_fold_configs_follow_adr_0014() -> None:
    config = fold_config("2009-12")
    assert config.experiment_id == "E01-2009-12"
    assert config.models == FAMILIES
    assert config.train_sample_fraction == 0.1
    assert config.sample_index == 0
    assert config.windows == ExperimentWindows.rolling_origin(periods.month(2009, 12))
    assert isinstance(config, ExperimentConfig)
    with pytest.raises(E01Error, match="not an ADR 0014 origin"):
        e01.regime_class("2008-12")


def test_stability_s1_resumes_and_feeds_the_robustness_diagnostic(
    e01_root: Path, built: tuple[Path, DataLock], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, lock = built
    out = tmp_path / "e01"
    shutil.copytree(e01_root / "folds", out / "folds")
    overrides = Overrides.from_json({**OVERRIDES, "train_sample_fraction": 0.5})
    for kind in e01.S1:
        e01.run_stability(root, lock, out, kind, overrides)
    runs = sorted(p.name for p in (out / "stability").iterdir() if p.is_dir())
    assert len(runs) == 4  # 2 loan samples + 2 seeds
    assert all("-E01-D" in name for name in runs)

    def refuse(*args: object, **kwargs: object) -> Path:
        raise AssertionError("finished replicates must be reused")

    monkeypatch.setattr(experiment_module, "run_experiment", refuse)
    e01.run_stability(root, lock, out, "seeds", overrides)  # resumes from the finished replicates

    summary = summarize(out, origins=ORIGINS)
    assert summary["stability_completed"] == ["samples", "seeds"]
    assert summary["complete"] is True
    sds = summary["rules"]["R6_stability"]["tune_log_loss_sd"]
    assert sds["samples"]["B2_logistic"] is not None
    assert sds["samples"]["X1_factored_gbm"] is None  # not measured in S1, never imputed
    assert sds["seeds"]["B2_logistic"] == 0.0  # seedless convex fit: zero by construction
    assert sds["seeds"]["X3_factored_gbm"] is None
    m1_vs_b2 = next(
        c
        for c in summary["comparisons"]
        if c["family"] == "F-B2" and c["candidate"] == "M1_lightgbm"
    )
    assert m1_vs_b2["sampling_fragility"] in ("fragile", "not_fragile")
    x1 = next(
        c
        for c in summary["comparisons"]
        if c["family"] == "F-M1" and c["candidate"] == "X1_factored_gbm"
    )
    assert x1["sampling_fragility"] == "not_assessable"


def test_only_one_orchestrator_runs_on_a_directory(
    built: tuple[Path, DataLock], tmp_path: Path
) -> None:
    """Gate B dry run: a stopped shell's children kept running on Windows, and two orchestrators
    wrote the same directory. The run lock refuses the second and is released on every exit."""
    root, lock = built
    lock_path = _lock_file(lock, tmp_path / "lock.json")
    out = tmp_path / "e01"
    options = e01_run.Options(
        root, lock_path, out, "pilot", min_free_commit_bytes=0, overrides=OVERRIDES
    )
    out.mkdir()
    held = e01_run.acquire_run_lock(out, "folds")
    with pytest.raises(E01Error, match="another E01 run holds"):
        e01_run.run(options)
    held.unlink()
    (out / e01_run.STOP).write_text("")
    assert e01_run.run(options) == e01_run.EXIT_STOPPED
    assert not (out / e01_run.RUN_LOCK).exists()  # released after a stop, too
