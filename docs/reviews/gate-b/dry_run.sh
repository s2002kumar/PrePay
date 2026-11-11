#!/usr/bin/env bash
# Gate B exact synthetic dry run of the E01 procedure (ADR 0014 §9.3-9.4, runbook §10).
# Usage: dry_run.sh <synthetic data root> <E01 output dir> <V1 output dir>
# Build the synthetic world first (docs/reviews/PREPAY_2_GATE_A.md §7, `prepay synth --preset dev`).
# Run from the repository root with the project environment active (`python` = .venv).
# On Windows, pass Windows paths (cygpath -w) and keep the host awake (keep_awake.py).
set -uo pipefail
W="$1"; OUT="$2"; V1OUT="$3"; LOCK="$W/data.lock.json"
python -c "import prepay; print('prepay from', prepay.__file__)"
echo "commit $(git rev-parse --short HEAD) dirty_files=$(git status --porcelain | wc -l)"
step() { local name="$1"; shift; local t=$(date +%s); PREPAY_RESOURCE_REPORT="$OUT.$name.resource.json" python -m prepay.cli --log-level WARNING "$@"; local code=$?; echo "[$(date -u +%H:%M:%S)] $name exit=$code $(( $(date +%s) - t ))s"; }
# The V1 reference fold the pilot is compared with (the V1 code path, fraction 0.1).
ls -d "$V1OUT"/*V1-2007-12*/ >/dev/null 2>&1 || step v1-2007-12 experiment rolling-origin --data-root "$W" --lock "$LOCK" --out "$V1OUT" --train-sample-fraction 0.1 --origins 2007-12
V1RUN=$(ls -d "$V1OUT"/*V1-2007-12*/ | head -1)
# 1. The approved preflight (12 GiB), without waiting: on a busy laptop it refuses (exit 3).
step preflight-default experiment e01 run --stage pilot --data-root "$W" --lock "$LOCK" --out "$OUT" --reproduce-against "$V1RUN" --preflight-wait-minutes 0
# 2-4. The owner's staged procedure; synthetic data only may lower the preflight.
step pilot experiment e01 run --stage pilot --data-root "$W" --lock "$LOCK" --out "$OUT" --reproduce-against "$V1RUN" --min-free-commit-gib 4
step folds experiment e01 run --stage folds --data-root "$W" --lock "$LOCK" --out "$OUT" --min-free-commit-gib 4
step stability experiment e01 run --stage stability --data-root "$W" --lock "$LOCK" --out "$OUT" --min-free-commit-gib 4
echo DONE
