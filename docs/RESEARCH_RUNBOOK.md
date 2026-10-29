# Private research runbook (real Freddie Mac data)

This runbook is for a researcher who has **lawfully obtained** the Freddie Mac Single-Family
Loan-Level Dataset. Everything here runs on your own machine. Nothing in this workflow uploads
data, and none of it belongs in public CI.

> Freddie Mac's dataset terms limit use to internal/research purposes. Public results are
> allowed only if they are noncommercial and cannot be used to recreate any part of the dataset.
> Keep raw files, bronze/silver/gold tables, trained models and reports under the gitignored
> `data/`, `artifacts/` and `reports/` directories. Read
> [the terms](https://capitalmarkets.freddiemac.com/crt/docs/pdfs/fre_terms_conditions_sflld.pdf)
> before publishing anything derived.

## 1. Obtain the files

1. Register and sign in at Freddie Mac **Clarity** (linked from the
   [dataset page](https://www.freddiemac.com/research/datasets/sf-loanlevel-dataset)) and
   accept the dataset terms. Note the date. You'll record it in the data lock.
2. Download the **Standard sample** files `sample_YYYY.zip` for the vintages you need. The
   modeling windows (MODELING §5) need outcome months from before 2018 through the cutoff, so
   download every vintage from 1999 on if disk allows (the full sample is several GB compressed).
3. Note the **release** from the Release Notes (Release 48: published 2026-10-28, cutoff
   2026-06-30). Only Releases 47 and 48 are supported (ADR 0002).
4. Prefer a disk location **outside cloud-synced folders** (OneDrive, Dropbox), so licensed files
   aren't copied to third-party storage. Point `--raw-dir`/`--data-root` there if the repository
   itself lives in a synced folder.

```
<raw-dir>/
  sflld/sample_1999.zip … sample_2026.zip
  pmms/MORTGAGE30US.csv  MORTGAGE15US.csv
```

## 2. Fetch public mortgage rates

```bash
uv run prepay rates fetch --out <raw-dir>/pmms
```

This downloads FRED `MORTGAGE30US` and `MORTGAGE15US`, validates the format, and writes a
`.retrieval.json` sidecar with the URL, UTC retrieval time and SHA-256.

## 3. Lock the inputs

```bash
uv run prepay data-lock create --raw-dir <raw-dir> --release 48 \
  --terms-reference "Accepted Freddie Mac SFLLD terms at Clarity registration on YYYY-MM-DD" \
  --out configs/data.lock.json
uv run prepay data-lock verify --raw-dir <raw-dir> --lock configs/data.lock.json
```

The lock holds only file names, sizes, SHA-256 digests, the release and cutoffs. It contains no
rows or credentials. Ingest refuses any file that differs from it. Corrections from a new
Freddie Mac release mean a new download and a new lock, never an in-place edit.

## 4. Ingest to bronze

```bash
uv run prepay ingest --raw-dir <raw-dir> --lock configs/data.lock.json --data-root <data-root>
```

- Verifies every locked file, then streams each archive member (bounded memory) into
  `<data-root>/bronze/sflld/release=R/vintage=Y/{origination,performance}.parquet`, preserving
  every field exactly plus `_source_file` and `_source_row`.
- Any row with the wrong number of fields **stops** the run and reports line numbers only. If you
  have checked the cause, rerun with `--allow-malformed` to skip and count such rows.
- Reruns reuse unchanged vintages; changed inputs rebuild atomically.
- `<data-root>/bronze/_ingest_summary.json` reports row counts, malformed rows, per-field
  domain violations and each member's period range (counts only).
- **Release check.** A performance record dated after the locked release's cutoff stops the run:
  the file can't belong to that release. A dataset whose latest reporting period is earlier than
  the cutoff is also refused, because that is what an older release locked under the wrong
  number looks like. Pass `--allow-early-end` only for a deliberate download of old vintages.
- Ingest streams each member in 8 MiB blocks, so its memory stays well under 1 GiB even for the
  full sample.

## 5. Transform to silver/gold (dbt)

```bash
uv run prepay transform --data-root <data-root> --lock configs/data.lock.json
```

This runs every dbt model and data test in `transform/` into
`<data-root>/warehouse/prepay.duckdb`, using the lock's performance cutoff. On a 16 GB machine,
pass `--memory-limit 8GB`. DuckDB then spills large joins and windows to
`prepay.duckdb.tmp` (allow tens of GB of free disk) instead of exhausting memory. It builds typed
staging with sentinels mapped to NULL, per-loan quarantine and exclusion findings
(`agg_data_quality`, counts only), first events (MODELING §2 decision table), and the gold
`fct_hazard_panel` with point-in-time features. Any failed test stops the run. Definitions are in
ADR 0003.

## 5b. Profile and audit (aggregates only)

```bash
uv run prepay profile --data-root <data-root> --lock configs/data.lock.json   --out reports/real/profile.json --outcomes-through 2019-12
uv run prepay audit --data-root <data-root> --lock configs/data.lock.json   --out reports/real/audit.json            # exit 2 on any disagreement
uv run prepay fingerprint --data-root <data-root> --out reports/real/warehouse-fingerprint.json
```

- `profile` reports volumes, quality findings, missingness, chronology and UPB disclosure.
  Event and loss distributions stop at `--outcomes-through`, so outcomes in the sealed windows
  stay unseen until the lockbox opens (ADR 0006 §6).
- `audit` compares dbt quarantine, exclusions, first events and panel outcomes against a
  plain-Python oracle that reads bronze directly, on five disjoint 1% loan-hash slices. It also
  compares gold features with the scenario state machine. It writes counts, never loan
  identifiers.
- `fingerprint` writes each table's row count and an order-independent content hash, so two
  builds can be compared.

## 6. Train and select (validation only)

```bash
uv run prepay train --data-root <data-root> --lock configs/data.lock.json --out artifacts/runs
# optional: --train-sample-fraction 0.25   (whole loans, stable hash; recorded in the manifest)
```

This fits B0 (PSA), B1 (lookup), B2 (logistic) and M1 (LightGBM) on outcomes through 2017-12,
tunes on 2018, selects by the pre-registered rule, and decides calibration on 2019 (ADR 0004).
It writes `artifacts/runs/<run_id>/` with JSON/LightGBM-text artifacts, `validation.json` and a
manifest of every digest. The manifest also records the credit-sufficiency decision of ADR 0006
§8. Test windows are refused at this stage. At full sample scale on a 16 GB machine, use
`--train-sample-fraction 0.1`, the largest pre-registered fraction that fits (ADR 0006 §5).

Before sealing, `uv run prepay diagnose-incentive --run <run> --data-root <data-root> --lock
configs/data.lock.json --out reports/real/diagnose-incentive.json` shows B1's training support per
incentive bin and every model's incentive response on Validation B rows (ADR 0007).

Then rehearse the lockbox on non-holdout months:

```bash
uv run prepay rehearse-lockbox --run artifacts/runs/<run_id> --data-root <data-root> \
  --lock configs/data.lock.json --out reports/real/lockbox-rehearsal.json
```

The lockbox writes its report only at the end, so a crash part-way through would read the holdout
and leave nothing. The rehearsal runs the same code (window scoring, segments, cohort and run-off
backtests) on Validation B and on the cohort active at the end of the training window, capped at
2019-12. It records stage times and peak RSS. Scale the projection by row count before opening.
Validation B is in-sample for calibration, so the rehearsal's metrics are not evidence.

## 7. Seal, then evaluate the holdout once

```bash
uv run prepay seal --run artifacts/runs/<run_id>
uv run prepay evaluate-lockbox --run artifacts/runs/<run_id> --data-root <data-root>   --lock configs/data.lock.json
```

The first evaluation is written read-only to `evaluations/first.json` and can't be repeated
for that run. Besides the ADR 0004 metrics, it holds the ADR 0006 secondary analyses: segment
tables, credit gating, balance run-off and informative-censoring bounds. Report it as is,
including any baseline win or degradation flag. Don't publish real-data results without the
terms review described at the top of this runbook. After the opening, the test windows can't
judge a revised model fairly; ADR 0008 describes the forward-month experiment instead.

## 8. Reliability program experiments (private, owner-run)

The program (`docs/RELIABILITY_PLAN.md`, ADR 0009/0010) runs only on your machine. Every command
prints just an output path and a status. Reports stay under the gitignored `artifacts/`. Don't
paste them into hosted AI sessions until the data-use review is complete (ADR 0009 §3). Use the
primary run's training fraction (0.1 at full sample scale).

```bash
# Development folds (ADR 0009 §4): outcomes through 2019-12 only. Every development family is
# fitted per fold; expect several hours on a laptop.
uv run prepay experiment rolling-origin --data-root <data-root> --lock configs/data.lock.json   --out artifacts/experiments --train-sample-fraction 0.1

# Forward-evaluation members (ADR 0010). Seal each run right after training.
uv run prepay experiment run --preset DEV2017 --data-root <data-root>   --lock configs/data.lock.json --out artifacts/experiments --train-sample-fraction 0.1
uv run prepay experiment run --preset REFIT2026 --data-root <data-root>   --lock configs/data.lock.json --out artifacts/experiments --train-sample-fraction 0.1   --exploratory-opened-windows        # trains on opened months; use 0.05 if 0.1 exceeds 10 GB
uv run prepay seal --run artifacts/experiments/<run_id>
```

- `rolling-origin` writes `artifacts/experiments/rolling-origin-<UTC>.json`: per fold and model,
  log loss, paired differences vs B2 and M1, A/E, regime calibration (D4) and cohort error
  attribution (D5), plus fold wins and ranks. It is development evidence (ADR 0009 §2). It ranks
  and explains candidates; it never confirms one.
- Member runs refuse the lockbox. They are judged only on forward months (ADR 0010).
