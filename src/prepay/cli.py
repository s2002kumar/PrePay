"""``prepay`` command-line interface. Each subcommand exits non-zero on any violation."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from prepay import __version__, logs

log = logging.getLogger("prepay.cli")


def _cmd_synth(args: argparse.Namespace) -> int:
    from prepay.synthetic.config import PRESETS
    from prepay.synthetic.dataset import generate_dataset

    config = PRESETS[args.preset]
    requested = {
        "seed": args.seed,
        "anomalies": args.anomalies,
        "first_vintage": args.first_vintage,
        "loans_per_vintage": args.loans_per_vintage,
    }
    overrides = {k: v for k, v in requested.items() if v is not None}
    config = dataclasses.replace(config, **overrides)
    started = time.perf_counter()
    manifest = generate_dataset(config, Path(args.out))
    log.info(
        "synthetic dataset generated",
        extra={
            "out": args.out,
            "preset": args.preset,
            "seconds": round(time.perf_counter() - started, 2),
            "totals": manifest["totals"],
        },
    )
    json.dump(manifest["totals"], sys.stdout)
    sys.stdout.write("\n")
    return 0


def _emit(payload: object) -> None:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def _cmd_lock_create(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import create_lock, write_lock

    lock = create_lock(
        Path(args.raw_dir),
        release=args.release,
        terms_reference=args.terms_reference or "",
        synthetic_manifest=Path(args.synthetic_manifest) if args.synthetic_manifest else None,
    )
    write_lock(lock, Path(args.out))
    _emit(
        {
            "lock": args.out,
            "files": len(lock.sflld) + len(lock.pmms),
            "fingerprint": lock.fingerprint(),
            "synthetic": lock.synthetic,
        }
    )
    return 0


def _cmd_lock_verify(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import read_lock, verify_lock

    problems = verify_lock(read_lock(Path(args.lock)), Path(args.raw_dir))
    _emit({"lock": args.lock, "ok": not problems, "problems": problems})
    return 0 if not problems else 2


def _cmd_ingest(args: argparse.Namespace) -> int:
    from prepay.ingest import ingest_all
    from prepay.ingest.lock import read_lock

    summary = ingest_all(
        Path(args.raw_dir),
        read_lock(Path(args.lock)),
        Path(args.data_root) / "bronze",
        allow_malformed=args.allow_malformed,
    )
    _emit(
        {k: summary[k] for k in ("synthetic", "release", "performance_cutoff")}
        | {"vintages": len(summary["vintages"])}
    )
    return 0


def _cmd_transform(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import read_lock
    from prepay.transform import run_dbt, warehouse_path

    started = time.perf_counter()
    run_dbt(Path(args.data_root), read_lock(Path(args.lock)), command=args.dbt_command)
    _emit(
        {
            "warehouse": warehouse_path(Path(args.data_root)).as_posix(),
            "seconds": round(time.perf_counter() - started, 2),
        }
    )
    return 0


def _cmd_train(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import read_lock
    from prepay.modeling.train import TrainingConfig, train

    config = TrainingConfig(train_sample_fraction=args.train_sample_fraction)
    run_dir = train(
        Path(args.data_root),
        read_lock(Path(args.lock)),
        Path(args.out),
        config,
        truth_dir=Path(args.truth_dir) if args.truth_dir else None,
    )
    manifest = json.loads((run_dir / "run-manifest.json").read_text(encoding="utf-8"))
    _emit(
        {
            "run": run_dir.as_posix(),
            "selected": manifest["selection"]["selected"],
            "validation_a_log_loss": manifest["selection"]["validation_a_log_loss"],
            "calibration_adopted": manifest["selection"]["calibration"]["adopted"],
            "synthetic": manifest["synthetic"],
        }
    )
    return 0


def _cmd_seal(args: argparse.Namespace) -> int:
    from prepay.modeling.lockbox import seal

    sealed = seal(Path(args.run))
    _emit({k: sealed.payload[k] for k in ("run_id", "candidate", "candidate_digest")})
    return 0


def _cmd_evaluate_lockbox(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import read_lock
    from prepay.modeling.lockbox import evaluate_lockbox

    report = evaluate_lockbox(Path(args.run), Path(args.data_root), read_lock(Path(args.lock)))
    summary = {
        window: {
            "rows": result.get("rows", result.get("selected", {}).get("rows")),
            "selected_log_loss": result.get("selected", {}).get("log_loss"),
            "flags": {
                k: v for k, v in result.get("_flags", {}).items() if k != "paired_difference_vs"
            },
        }
        for window, result in report["results"].items()
    }
    _emit({"run_id": report["run_id"], "synthetic": report["synthetic"], "windows": summary})
    return 0


def _cmd_finance_report(args: argparse.Namespace) -> int:
    from prepay.finance.validation import render_report

    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(), encoding="utf-8", newline="\n")
    _emit({"written": target.as_posix()})
    return 0


def _cmd_demo_build(args: argparse.Namespace) -> int:
    from prepay.api.bundle import build_bundle

    out = build_bundle(Path(args.out), preset=args.preset)
    _emit({"bundle": out.as_posix(), "preset": args.preset})
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from prepay.api.app import create_app

    static = Path(args.web_dist) if args.web_dist else None
    uvicorn.run(
        create_app(Path(args.bundle), static),
        host=args.host,
        port=args.port,
        proxy_headers=args.proxy_headers,
        server_header=False,
    )
    return 0


def _cmd_publication_check(args: argparse.Namespace) -> int:
    from prepay.publication import scan_history, scan_repository, scan_tree

    root = Path(args.root)
    findings = scan_repository(root)
    for spec in args.tree:
        label, _, path = spec.partition("=")
        findings += scan_tree(Path(path), label)
    if args.history:
        findings += scan_history(root)
    _emit(
        {
            "ok": not findings,
            "findings": [
                {"location": f.location, "rule": f.rule, "detail": f.detail} for f in findings
            ],
        }
    )
    return 0 if not findings else 3


def _cmd_benchmark(args: argparse.Namespace) -> int:
    from prepay.benchmark import run

    result = run(args.preset, Path(args.work_dir), report_dir=Path(args.report_dir))
    _emit({k: result[k] for k in ("dataset", "stages", "throughput_rows_per_second", "host")})
    return 0


def _cmd_rates_fetch(args: argparse.Namespace) -> int:
    from prepay.ingest.lock import PMMS_SERIES
    from prepay.ingest.pmms import fetch_series

    _emit([fetch_series(series, Path(args.out)) for series in PMMS_SERIES])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prepay",
        description="Prepay mortgage cash-flow research tool. Synthetic commands need no data.",
    )
    parser.add_argument("--version", action="version", version=f"prepay {__version__}")
    parser.add_argument(
        "--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"]
    )
    sub = parser.add_subparsers(dest="command", required=True)

    synth = sub.add_parser(
        "synth",
        help="generate a fictional SFLLD-format dataset with known ground truth",
        description=(
            "Write deterministic synthetic sample_YYYY.zip files (SFLLD Release 47/48 layout), "
            "FRED-format synthetic rate CSVs, ground-truth hazards and a manifest. "
            "The output is fictional and safe to use in public CI."
        ),
    )
    synth.add_argument("--preset", choices=["ci", "dev", "benchmark"], default="ci")
    synth.add_argument("--out", required=True, help="output directory (created if missing)")
    synth.add_argument("--seed", type=int, help="override the preset's root seed")
    synth.add_argument("--first-vintage", type=int, help="override the first origination year")
    synth.add_argument("--loans-per-vintage", type=int, help="override loans per full vintage")
    anomaly = synth.add_mutually_exclusive_group()
    anomaly.add_argument(
        "--anomalies",
        dest="anomalies",
        action="store_true",
        default=None,
        help="inject documented data-quality anomalies",
    )
    anomaly.add_argument(
        "--no-anomalies", dest="anomalies", action="store_false", help="generate clean files only"
    )
    synth.set_defaults(handler=_cmd_synth)

    lock = sub.add_parser("data-lock", help="create or verify the source-file lock (no rows)")
    lock_sub = lock.add_subparsers(dest="lock_command", required=True)
    create = lock_sub.add_parser(
        "create",
        help="hash every source file and declare its release",
        description=(
            "Record name, size and SHA-256 of each sflld/sample_YYYY.zip and pmms/*.csv under "
            "--raw-dir. Real data requires --release and --terms-reference; synthetic data takes "
            "both from --synthetic-manifest."
        ),
    )
    create.add_argument("--raw-dir", required=True)
    create.add_argument("--out", required=True, help="lock path, e.g. configs/data.lock.json")
    create.add_argument("--release", type=int, default=48)
    create.add_argument("--terms-reference", help="how/when the Freddie Mac terms were accepted")
    create.add_argument("--synthetic-manifest", help="manifest.json of a prepay synth dataset")
    create.set_defaults(handler=_cmd_lock_create)
    verify = lock_sub.add_parser("verify", help="fail (exit 2) if any file differs from the lock")
    verify.add_argument("--raw-dir", required=True)
    verify.add_argument("--lock", required=True)
    verify.set_defaults(handler=_cmd_lock_verify)

    ingest = sub.add_parser(
        "ingest",
        help="verify the lock, then stream sources to bronze Parquet",
        description=(
            "Idempotent: unchanged inputs are reused, changed inputs are rebuilt atomically. "
            "Malformed rows stop the run unless --allow-malformed quarantines and counts them."
        ),
    )
    ingest.add_argument("--raw-dir", required=True)
    ingest.add_argument("--lock", required=True)
    ingest.add_argument(
        "--data-root", required=True, help="bronze is written to <data-root>/bronze"
    )
    ingest.add_argument("--allow-malformed", action="store_true")
    ingest.set_defaults(handler=_cmd_ingest)

    transform = sub.add_parser(
        "transform",
        help="build silver/gold tables with dbt and run every data test",
        description=(
            "Runs the dbt project in transform/ on <data-root>/bronze into "
            "<data-root>/warehouse/prepay.duckdb. The performance cutoff comes from the lock."
        ),
    )
    transform.add_argument("--data-root", required=True)
    transform.add_argument("--lock", required=True)
    transform.add_argument("--dbt-command", default="build", choices=["build", "run", "test"])
    transform.set_defaults(handler=_cmd_transform)

    train_cmd = sub.add_parser(
        "train",
        help="fit B0/B1/B2 baselines and the LightGBM candidate; select on validation only",
        description=(
            "Reads train/validation windows from the gold panel (test windows are refused), "
            "tunes on validation A, selects by the pre-registered rule, decides calibration on "
            "validation B and writes a run directory with JSON/LightGBM-text artifacts."
        ),
    )
    train_cmd.add_argument("--data-root", required=True)
    train_cmd.add_argument("--lock", required=True)
    train_cmd.add_argument("--out", default="artifacts/runs")
    train_cmd.add_argument(
        "--train-sample-fraction",
        type=float,
        help="loan-consistent hash sample of the training window",
    )
    train_cmd.add_argument("--truth-dir", help="synthetic truth/ directory for recovery checks")
    train_cmd.set_defaults(handler=_cmd_train)

    seal_cmd = sub.add_parser("seal", help="freeze a run's candidate before any holdout access")
    seal_cmd.add_argument("--run", required=True, help="artifacts/runs/<run_id>")
    seal_cmd.set_defaults(handler=_cmd_seal)

    lockbox = sub.add_parser(
        "evaluate-lockbox",
        help="one-shot evaluation of a sealed run on the test windows (refuses a second run)",
    )
    lockbox.add_argument("--run", required=True)
    lockbox.add_argument("--data-root", required=True)
    lockbox.add_argument("--lock", required=True)
    lockbox.set_defaults(handler=_cmd_evaluate_lockbox)

    report = sub.add_parser(
        "finance-report", help="regenerate the finance engine validation disclosures (markdown)"
    )
    report.add_argument("--out", default="docs/validation/FINANCE_ENGINE.md")
    report.set_defaults(handler=_cmd_finance_report)

    demo = sub.add_parser("demo", help="public demo bundle (fictional data only)")
    demo_sub = demo.add_subparsers(dest="demo_command", required=True)
    demo_build = demo_sub.add_parser(
        "build",
        help="run the fictional pipeline end to end and assemble a sealed demo bundle",
    )
    demo_build.add_argument("--out", default="build/demo")
    demo_build.add_argument("--preset", choices=["ci", "dev"], default="ci")
    demo_build.set_defaults(handler=_cmd_demo_build)

    serve = sub.add_parser("serve", help="serve the demo API and web UI (fictional data only)")
    serve.add_argument("--bundle", default="build/demo")
    serve.add_argument("--web-dist", default="web/dist")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--proxy-headers",
        action="store_true",
        help="trust X-Forwarded-For (only behind a trusted reverse proxy)",
    )
    serve.set_defaults(handler=_cmd_serve)

    publication = sub.add_parser(
        "publication-check",
        help="fail (exit 3) if tracked files or build outputs contain restricted data or secrets",
    )
    publication.add_argument("--root", default=".")
    publication.add_argument(
        "--tree",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="also scan a build output, e.g. web=web/dist or demo=build/demo",
    )
    publication.add_argument(
        "--history", action="store_true", help="also scan all Git history for credential patterns"
    )
    publication.set_defaults(handler=_cmd_publication_check)

    bench = sub.add_parser(
        "benchmark",
        help="measure wall time, peak RSS and throughput of the pipeline on synthetic data",
    )
    bench.add_argument("--preset", choices=["ci", "dev", "benchmark"], default="dev")
    bench.add_argument("--work-dir", default="scratch/benchmark")
    bench.add_argument("--report-dir", default="reports/benchmarks")
    bench.set_defaults(handler=_cmd_benchmark)

    rates = sub.add_parser("rates", help="public mortgage-rate series")
    rates_sub = rates.add_subparsers(dest="rates_command", required=True)
    fetch = rates_sub.add_parser(
        "fetch",
        help="download FRED MORTGAGE30US/MORTGAGE15US (network; local research only)",
    )
    fetch.add_argument("--out", required=True, help="directory, e.g. data/raw/pmms")
    fetch.set_defaults(handler=_cmd_rates_fetch)
    return parser


def _write_resource_report(started: float) -> None:
    """Record this command's duration and peak RSS when a benchmark asks for it."""
    target = os.environ.get("PREPAY_RESOURCE_REPORT")
    if not target:
        return
    from prepay.io import write_json_atomic
    from prepay.resources import peak_rss_bytes

    write_json_atomic(
        Path(target),
        {"seconds": round(time.perf_counter() - started, 3), "peak_rss_bytes": peak_rss_bytes()},
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logs.configure(args.log_level)
    handler: Callable[[argparse.Namespace], int] = args.handler
    started = time.perf_counter()
    try:
        code = handler(args)
    except Exception:
        log.exception("command failed", extra={"command": args.command})
        return 1
    _write_resource_report(started)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
