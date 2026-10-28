# Prepay | Autonomous build and acceptance runbook

## 1. First run: don't ask for a new strategy

Read `CLAUDE.md` and all seven foundational documents, including `docs/ENGINEERING_STANDARD.md`. Build the product exactly as specified. Verify `git status`, existing files, configured identity and `gh` authorization. Initialize repository if needed using current user Git settings. The owner authorized a **public GitHub repo** on 2026-10-27. Create `prepay` PUBLIC after a mandatory initial-file/secret/license scan; leave already existing repos unchanged unless explicitly instructed. Work autonomously; no stop-for-approval after each milestone.

### Investigate constraints once

- Identify machine OS/CPU/RAM/disk, Python/uv/Docker availability, and whether official Freddie Mac archives are locally present.
- Verify dataset account/terms before any download automation; source may require owner registration. No credential requests except if absolutely necessary and handle via private normal auth, not pasted chat secrets.
- If data absent: implement every synthetic-data deliverable and *do not manufacture empirical results*. Show real-data blocker once and resume elsewhere.
- Obtain authoritative Release 47 file layout or actual equivalent matching downloaded source; treat mismatch as hard fail. Preserve a schema fingerprint.

## 2. Work order (each PR produces runnable proof)

| PR group | Deliverable | Proof |
|---|---|---|
| 0A | env, tooling, CI, Makefile, lint/types | clean install green |
| 0B | synthetic origination/performance/rates generator | deterministic events and files, seed checks |
| 1A | streaming source-contract ingest | checksum, row count, duplicate, missing, corruption tests |
| 1B | versioned rates and data quality | snapshot parity, time units, missing dates tests |
| 2A | dbt silver with sentinel/version policy | `dbt build` + data tests |
| 2B | labels and feature state machine | event-table unit tests, t-1 perturbation/parity |
| 3A | reproducible B0/B1/B2 | dataset split assertions, logs and metrics |
| 3B | boosted model + calibration + registry | simplex, no test leakage, preserved artifacts |
| 4A | pure ledger and independent oracle | financial property suite across rates/hazards |
| 4B | cohort backtesting, uncertainty and seal | scenario parity, no censor lookahead, immutable first test run |
| 5A | typed API, synthetic portfolio API | authorization isolation + contract tests |
| 5B | responsive product UI and deployment | E2E, accessibility, security and health |
| 5C | documented measured results, benchmarking, source report | clean-clone reproduction and release scan |

The repository QA gates in `docs/ENGINEERING_STANDARD.md` are binding on every PR. Record exact checked commands and CI links; do not fake a human approval. Groups can be split or reordered if a dependency justifies it; key rule is always a working vertical slice and full acceptance proof. Avoid big “all files generated” commits. CI on every PR; test performance regressions using seeded local benchmark fixtures, not data in GitHub Actions. Use standard public GitHub-hosted runners to avoid private-runner minute quotas, minimal token permissions, and synthetic-only tests. Large, sensitive, or real-data training runs occur locally, never in CI. No `pull_request_target` workflows that check out or execute external PR code.

## 3. Data validation

Check per-file and per-vintage hashes, row counts, orphan keys, `loan_id + period` uniqueness, period continuity/reasoned gap markers, codes, impossible dates, maturity ordering, original/current balance constraints, hard-coded unknown sentinel conversions, rate series units and reliable point-in-time joins. Keep a rejected-record summary; never silently impute outcomes, fabricate month records, or silently truncate bad fields.

## 4. Metrics + evidence gates

Every trained run has readable configuration, data snapshot SHA, Git SHA, split ranges, artifacts, fitted transforms and real-vs-synthetic marker. Store complete metrics privately but publish only legally permissible approved aggregates. Run one-step probability evaluation, calibration, 12/24m cohort outcomes with censor assumptions, segments, bootstrap/uncertainty, drift and feature sensitivities. Register and seal before holdout. Do not retry a test window under the same run ID to produce better output.

Finance output must separately reconcile exposure exits and realized-assumption cash receipts. Verify baseline actual-vs-predicted curves and that **market rate shocks do not affect fixed contractual coupon**. Include at least one highly visible uncertainty/limitations view.

## 5. Scalable ingestion requirement

Implement sample real-data processing incrementally and profile memory. Benchmarks should state file count/vintages, rows, wall clock, peak RSS, disk throughput and reproducible host specs. Avoid irrelevant “processing billions” claims. If RAM-bound, choose an explicit whole-loan sampling strategy for fitting, not arbitrary row truncation; still validate on untouched evaluation data when feasible.

## 6. Public deployment and publication checklist

- Public docker/web image contains **only synthetic-independent portfolio data and code**. Explicitly inspect packaged files, source maps, logs, prompts and API model loads.
- No real Freddie loan IDs, private raw files, modified extracts, representative loan lines, real-trained model weights, private coefficients or real-derived assets by default.
- An optional research-results release must be reviewed against current Freddie terms (noncommercial and non-reidentifiable research outputs); don't assume minimum segment size is a license.
- Clear copyright/data attribution and scope caveats; no direct link from restricted source IDs to identifiable mortgages or securities.
- No unrestricted input filters that enable reconstruction of source records.
- Key secrets absent from git and browser; rate-limited APIs, bounds, tests, keyboard access, mobile checks, no XSS, deployment health/restart, logs with no user private info.

## 7. Final README/report facts and honest claims

Show (a) exact data source vintage window/cutoff, (b) real training input counts, (c) model families and why winner chosen, (d) time-based holdout scores **even if baseline wins**, (e) independently verified money conservation, (f) one graph of hypothetical rate-scenario cash-timing change and one honest holdout chart where publication is permitted, (g) what product does *not* do.

Three levels of milestone status: **implemented on synthetic**, **validated on protected real data privately**, **published/deployed**. Never collapse levels into one green badge. Provide exact run steps with no hidden local-only dependency.

## 8. Allowed questions to owner

1. Freddie Mac login/data access if blocked.
2. Permission to pay for hosting or request credentials.
3. Changing GitHub repo visibility / publishing real-data results under licensing review.
4. Materially changing label, financial accounting, public exposure or frozen test criteria.

Otherwise, solve engineering decisions yourself, write a concise ADR, implement and test. Owner should not need to repeatedly manage Claude.

## 9. Reviewer-grade completion policy

Implement `docs/ENGINEERING_STANDARD.md` incrementally, enable `main` protection when CI checks exist, and maintain truthful public `docs/STATUS.md` with reproducible evidence and known blockers. Prepare public-safe M2/M4/M5 review packets. Never block implementation simply because a human independent reviewer has not yet been invited; do not claim one reviewed the project. At release, flag the absence of independent technical review as an explicit limitation until resolved.
