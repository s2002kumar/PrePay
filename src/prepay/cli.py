"""``prepay`` command-line interface. Each subcommand exits non-zero on any violation."""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logs.configure(args.log_level)
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except Exception:
        log.exception("command failed", extra={"command": args.command})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
