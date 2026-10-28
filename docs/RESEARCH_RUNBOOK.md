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
- `<data-root>/bronze/_ingest_summary.json` reports row counts, malformed rows and per-field
  domain violations (counts only).

## 5. Transform to silver/gold (dbt)

```bash
uv run prepay transform --data-root <data-root> --lock configs/data.lock.json
```

This runs every dbt model and data test in `transform/` into
`<data-root>/warehouse/prepay.duckdb`, using the lock's performance cutoff. It builds typed
staging with sentinels mapped to NULL, per-loan quarantine and exclusion findings
(`agg_data_quality`, counts only), first events (MODELING §2 decision table), and the gold
`fct_hazard_panel` with point-in-time features. Any failed test stops the run. Definitions are in
ADR 0003.

## 6. Train and select (validation only)

```bash
uv run prepay train --data-root <data-root> --lock configs/data.lock.json --out artifacts/runs
# optional: --train-sample-fraction 0.25   (whole loans, stable hash; recorded in the manifest)
```

This fits B0 (PSA), B1 (lookup), B2 (logistic) and M1 (LightGBM) on outcomes through 2017-12,
tunes on 2018, selects by the pre-registered rule, and decides calibration on 2019 (ADR 0004).
It writes `artifacts/runs/<run_id>/` with JSON/LightGBM-text artifacts, `validation.json` and a
manifest of every digest. Test windows are refused at this stage.

## 7. Seal, then evaluate the holdout once

```bash
uv run prepay seal --run artifacts/runs/<run_id>
uv run prepay evaluate-lockbox --run artifacts/runs/<run_id> --data-root <data-root>   --lock configs/data.lock.json
```

The first evaluation is written read-only to `evaluations/first.json` and can't be repeated
for that run. Report it as is, including any baseline win or degradation flag. Don't publish
real-data results without the terms review described at the top of this runbook.
