# Synthetic source data

`prepay synth` writes a **fictional** dataset in the exact SFLLD Release 47/48 file layout
(`src/prepay/contracts/sflld.py`), with a known ground truth. Public CI, the benchmark and the
public demo run on it. Results on synthetic data show that the software works. They are **not**
evidence of predictive accuracy on real mortgages.

```bash
uv run prepay synth --preset ci --out data/synthetic/ci     # ~6k loans, ~0.4M loan-months, ~10 s
uv run prepay synth --preset dev --out data/synthetic/dev   # 2k loans/vintage, no anomalies
uv run prepay synth --preset benchmark --out data/synthetic/benchmark  # 50k loans/vintage, 1999+
```

## Output

| Path | Content |
|---|---|
| `raw/sflld/sample_YYYY.zip` | `sample_orig_YYYY.txt` (31 fields) + `sample_perf_YYYY.txt` (35 fields), pipe-delimited, headerless |
| `raw/pmms/MORTGAGE{30,15}US.csv` | Weekly Thursday rates in FRED `fredgraph.csv` format, percent per year (synthetic values) |
| `truth/truth_YYYY.parquet` | For every at-risk loan-month: true P(prepay), P(credit), P(active), and the drawn outcome |
| `manifest.json` | Config, generator version, layout fingerprints, per-file SHA-256 and row counts, injected anomalies |

The same config and code version always produce the same output. Archive *member* contents are
byte-identical on every platform. Compressed ZIP bytes can differ between zlib builds, so the
manifest records both hashes. Each `(seed, vintage, block)` has its own random stream.

## Ground-truth process (`src/prepay/synthetic/truth.py`)

Each at-risk loan-month draws one of {voluntary payoff, credit disposition, remain active} from a
softmax over two logits; the active logit is 0. Every input is known at the end of month `t-1`:

- **Prepay:** turnover intercept (~7% CPR seasoned at the money); refinance S-curve in
  note-minus-market incentive (midpoint 75 bp, ~50% CPR deep in the money); lock-in drag when
  out of the money; seasoning ramp to 30 months; burnout (months with incentive > 50 bp);
  June/July seasonality; FICO and loan-size effects.
- **Credit disposition:** age hump peaking near 40 months; FICO, LTV and DTI effects; a fictional
  2008–2011 stress window; relief during a fictional 2020-04..2021-09 forbearance window.
- **Censoring, drawn first:** modification (code `Y` then `P` rows), whole-loan sale (`15`) and
  defect (`96`). These are **informative**: more likely for weaker credit and under stress.
  Modified loans continue with `P` rows and later exits (`16`, `01`, `09`) that must never be
  labeled.
- **Observable-only states:** transient delinquency (including 90+ days that cures), forbearance
  plans with payment-deferral flags, disaster flags (2014+), and `RA` before REO dispositions.
- **Rates:** fictional weekly path loosely shaped like the post-1999 rate cycle, with seeded
  AR(1) noise. The 15-year series is the 30-year series minus about 62 bp.

The synthetic market reproduces the broad shape of real behavior: refi waves around 2009–2012 and
2020–2021, lock-in after 2022, crisis-era credit stress. This keeps scenarios interpretable. It is
not calibrated to Freddie Mac data.

### Deliberate simplifications

Curtailments re-amortize over the remaining term (US mortgages usually don't recast).
Forbearance and transient delinquency leave the balance path unchanged. Credit dispositions
freeze the UPB over the delinquency run before them. Loss components follow the Release 47
sign convention (recoveries negative) and the guide's Actual Loss formula, with fictional
severities. The cutoff-year vintage is pro-rated by elapsed months, with a floor of 20 loans.

## Injected anomalies (`src/prepay/synthetic/anomalies.py`)

With anomalies on (the `ci` preset), each kind below is applied to at most one distinct loan in
the first block of each vintage. Every one is recorded in `manifest.json`, so data-quality tests
can assert exact detection.

| Kind | What is written |
|---|---|
| `orphan_performance` | 3 performance rows for a loan ID absent from the origination file |
| `duplicate_exact_period` | an identical second row for one loan-month |
| `duplicate_conflicting_period` | a second row for one loan-month with a different UPB |
| `missing_period_gap` | one interior month removed |
| `invalid_zero_balance_code` | terminal code `06` (not in the official enumeration) |
| `rows_after_termination` | an activity row one month after a terminal record |
| `modification_with_terminal_same_month` | `Y` modification flag on a payoff record |
| `missing_zero_balance_effective_date` | terminal code without an effective date |
| `duplicate_origination` | a second origination row for the same loan ID with a different FICO |

Sentinels (`9999` FICO, `999` LTV/DTI/MI, `000` postal code, and so on) are **valid** missing
values, not anomalies.
