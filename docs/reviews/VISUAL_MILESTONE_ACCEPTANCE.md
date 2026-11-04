# Visual milestone (B+) acceptance report

Prepared 2026-11-04 by the implementing agent, for the owner's final review before merge.
**Self-review, not independent review.** Synthetic data only: nothing here measures real-world
forecasting accuracy.

## What was decided

The owner chose direction **B (Modern Investment Analytics Platform)** from the two interactive
prototypes on the private design canvas, plus two parts of **A**:
- the cursor-linked formula/value inspector;
- the full A / B / B − A comparison table.

[ADR 0012](../decisions/0012-scenario-lab-visual-system.md) records the hierarchy, the derivation
rules, the visual system and the two served-label corrections.

Before building, the four canvas pages were rendered and inspected in both themes. That review
changed four things:
- The outcome column had a dead gap; it now holds the support status and the financial
  consequence.
- Scenarios A and B overflowed at 390 px; they now stack on mobile.
- The chart tooltip covered the B line; it now opens on the side away from the cursor.
- The page surface moved from warm to cool neutral.

Separately, A's desktop prototype has a broken macro in its "drivers" row. A was not built, so
that was not fixed.

## Verdict

**Pending the owner's review.** Every criterion below has passing local evidence. CI on the PR is
the reproducible record. Not merged.

## Criteria and evidence

| # | Criterion (owner's brief) | Evidence | Result |
|---|---|---|---|
| V1 | Every displayed value derives from served data | `web/src/derive.ts` holds every derivation step and `derive.test.ts` unit-tests it. `e2e/reconcile.spec.ts` requests the same projection from the API, then checks each raw value on a `data-*` attribute and each formatted string: headline, dots, full table, composition, inspector, tooltip, ledger totals | PASS |
| V2 | B − A sign conventions | The served A − B is flipped. The test checks each flip against the difference of the two summaries, and checks that the sign matches | PASS |
| V3 | Cash WAL full life; totals use the horizon | Basis tags (full life, months 1–24, months 1–H, at month H). The test changes the horizon to 24 and 360 months: horizon metrics follow the served summary, and WAL stays fixed | PASS |
| V4 | Scheduled, payoffs, credit exits, recoveries, losses, remaining UPB kept distinct | Composition table. The test checks B0 = SP + PP + DC + still owed (relative error < 1e-9), principal cash = served fraction × B0, and pending × (1 − severity) = served pending recoveries. Ledger totals are in whole dollars; the identity residual is $0.00 | PASS |
| V5 | Composition y-axis scaling | A and B share one y-maximum: `sharedPeriodMax` (unit test) and equal `data-ymax` (browser test). Periods are equal-length projection years | PASS (fixed) |
| V6 | Model disagreement distinct from a confidence interval | Hatched brackets, labelled "model-family spread", and "not a confidence interval" wherever ranges appear | PASS |
| V7 | B2_logistic named once | `test_model_range_names_each_family_once_and_keeps_the_spread` checks unique names, and checks the spread equals the min/max over every projected member | PASS |
| V8 | Served applicability rule matches the code | The rule text is generated from `decide()`'s constants. `test_served_verdict_rule_states_the_implemented_thresholds` checks the text and `decide()` at each threshold. Browser tests check the methodology table and the trust panel | PASS |
| V9 | Extrapolating and unsupported impossible to miss; unsupported is range-first | Support banner above the headline; verdict chips. Unsupported switches to a range headline, hollow dots, dashed lines and no consequence paragraph. Two browser tests, both themes | PASS |
| V10 | Controls stay on the static grid; no implied online simulation | The steppers walk the 13 grid scenarios and stop at the ends. The static site offers no ramp, its credit inputs are disabled, and it says it holds precomputed results only | PASS |
| V11 | Accessibility | axe (WCAG 2.1 AA, no serious or critical issues) on every route in light and dark: the lab with tables and a definition open, the unsupported state, and the static site. Charts are keyboard-readable and drive the shared cursor | PASS |
| V12 | Mobile and desktop | No horizontal page scroll at 375 and 390 px, with the analytical tables expanded. Screenshots below | PASS |
| V13 | Static vs API parity; production builds | Five cases match text-for-text across the outcome, tables, inspector, drivers, trust panel and identities. `vite build` and `vite build --mode static`; `prepay demo static-site` checks every response against the API | PASS |
| V14 | Fonts self-hosted; CSP unchanged | Geist and Geist Mono (OFL-1.1) come from pinned packages; licenses are served at `/licenses/`. Browser tests on both builds show no third-party requests. `npm audit --omit=dev`: 0 vulnerabilities | PASS |
| V15 | Python, finance and type gates | See "Commands and results" | PASS |

## Commands and results (local, Windows 11, 2026-11-04)

| Command | Result |
|---|---|
| `ruff check src tests`, `ruff format --check src tests`, `sqlfluff lint`, `mypy` | clean |
| `npm run lint`, `npm run typecheck`, `npm test` | clean; 24 unit tests pass |
| `npx playwright test --project desktop` (live app) | 28 / 28 pass |
| `PREPAY_STATIC_SITE=../build/pages-site npx playwright test --project static` | 10 / 10 pass |
| `pytest` (the whole Python suite, as `make test`) | 422 passed, 1 skipped (the POSIX file-permission test, skipped on Windows by design) |
| `pytest tests/financial --cov=prepay.finance --cov-branch --cov-fail-under=90` (`make test-finance`) | 97 passed; finance coverage 95.60% |
| `npm audit --omit=dev --audit-level=high` | 0 vulnerabilities |

**Local bundle.** Local evidence used a fresh `ci`-preset bundle built from this branch's code
(content digest `86e0b72d…`). The `dev`-preset rebuild ran out of memory on this machine. CI's
`e2e` job also uses the `ci` preset, and `pages.yml` rebuilds the `dev` bundle for deployment.
So the numbers in the screenshots below differ from the live site's. The before and after
screenshots use the same bundle.

## Screenshots

The default comparison is the fictional 2023 pool, flat vs −100 bp, at 120 months. Before is
`main` at `5a3ebb2`; after is this branch. Both use the same local bundle. The images are
full-page JPEGs in [`visual-milestone/`](visual-milestone/).

| | Before | After |
|---|---|---|
| Desktop 1440 px, light | [before-desktop-light](visual-milestone/before-desktop-light.jpg) | [after-desktop-light](visual-milestone/after-desktop-light.jpg) |
| Desktop 1440 px, dark | [before-desktop-dark](visual-milestone/before-desktop-dark.jpg) | [after-desktop-dark](visual-milestone/after-desktop-dark.jpg) |
| Mobile 390 px, light | [before-mobile-light](visual-milestone/before-mobile-light.jpg) | [after-mobile-light](visual-milestone/after-mobile-light.jpg) |
| Mobile 390 px, dark | [before-mobile-dark](visual-milestone/before-mobile-dark.jpg) | [after-mobile-dark](visual-milestone/after-mobile-dark.jpg) |
| Unsupported B (+300 bp), range-first | n/a | [after-range-first-desktop-light](visual-milestone/after-range-first-desktop-light.jpg) |
| Full table, ledger and a definition open | n/a | [after-analysis-open-desktop-dark](visual-milestone/after-analysis-open-desktop-dark.jpg) |

Regenerate the after set with `PREPAY_REVIEW_SHOTS=1 npx playwright test --project screenshots`
(in `web/`). The same run refreshes the README images.

## Remaining limitations

- The live container (custom ramps, credit inputs) is still not hosted (ADR 0011, L1).
- On a 390 px screen, the first viewport shows the scenario inputs. The outcome starts on the
  second screen.
- The monthly ledger shows whole dollars. Cents appear only in the reconciliation residuals.
- The served model and the model-family ranges come from a synthetic-trained bundle. The
  interface shows how to read a projection; it says nothing about real-mortgage accuracy.
