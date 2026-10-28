# Benchmarks

Measurements on **synthetic** data from `prepay synth`. Each stage runs in its own process, so
peak RSS belongs to that stage alone. These are single-run measurements on one laptop, not
guarantees. No resource budget is enforced yet (ENGINEERING_STANDARD §3: budgets come from a
representative baseline and an ADR).

```bash
make benchmark            # = uv run prepay benchmark --preset dev --work-dir scratch/benchmark
```

The JSON report, with the query-plan sample and library versions, is written to
`reports/benchmarks/` (gitignored).

## Pipeline, `dev` preset: 2026-10-28

Host: Windows 11 (10.0.26200), Intel Core Ultra 7 155H (22 logical CPUs), 15.4 GB RAM, Python
3.12.13, DuckDB 2.0.0, pyarrow 26.0.0, dbt-core 1.12.6 / dbt-duckdb 1.11.1. Repository on a
OneDrive-synced folder, data in the local temp directory. One repetition.

Dataset: 47,000 loans (2,000 per vintage, 2003–2026, cutoff 2026-06), 3,135,701 performance
rows; raw ZIPs 58.4 MB, bronze Parquet 52.0 MB, DuckDB warehouse 331.6 MB; 3,036,177 gold
hazard-panel rows.

| Stage | Command time | Peak RSS | Throughput |
|---|---:|---:|---:|
| `synth` (generate) | 60.5 s | 258 MiB | — |
| `data-lock create` | 0.5 s | 52 MiB | — |
| `ingest` | 36.6 s | 169 MiB | 85.7k performance rows/s |
| `ingest` rerun (all vintages reused) | 0.4 s | 52 MiB | — |
| `transform` (dbt build: 15 models + 31 tests) | 51.0 s | 1,999 MiB | 61.5k performance rows/s |

## Observations

- Ingest memory stays bounded (169 MiB for 3.1M rows) because members stream in 8 MiB blocks.
  The rerun shows the fingerprint reuse path costs well under a second.
- dbt's peak RSS is DuckDB's working memory for joins and windows over the whole panel.
  DuckDB can spill to disk, so this doesn't bound full-sample memory. The full Freddie sample
  (~50k loans per vintage since 1999) is roughly 30× this dataset, and it hasn't been measured.
  The `benchmark` preset (`prepay benchmark --preset benchmark`) generates sample-scale synthetic
  volume for that measurement.
- Ingest throughput is dominated by per-field domain validation (regex/is-in over 35 columns).
  It hasn't been profiled or optimized yet.
