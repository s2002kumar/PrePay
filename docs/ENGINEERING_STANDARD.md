# Prepay | Engineering and repository review standard

**Status:** binding acceptance standard for implementation, not evidence of implementation. The software has not passed these gates until reproducible proof exists. Applies to every PR and final release, alongside `SPEC.md`, `FINANCIAL_CONVENTIONS.md`, and `MODELING.md`.

## 0. Operating principles

- **Correctness > reproducibility > maintainability > measured speed > surface polish.** A project can be visually excellent and still fail release for financial or model errors.
- **Evidence over assertions.** A claimed capability has a repeatable command, test, benchmark, source reference, or deployed verification. Never invent a result, badge, benchmark, independent approval or live URL.
- **Use the least complex design that meets a demonstrated requirement.** Do not introduce distributed compute, microservices, message queues, Kubernetes, vector databases or observability platforms without a measured or functional necessity and an ADR comparing simpler options.
- **Autonomy is not self-certification.** Claude may implement, test, and merge nonblocking increments after required checks. Its own review is not independent review; report the limitation truthfully. Make it easy for another engineer to examine every claim.

## 1. Enforceable PR quality gate (every change)

A PR cannot merge into protected `main` until all relevant checks succeed. The exact scripts need to exist, be executable from a clean clone and fail nonzero on violation.

1. `make check` offline on **only** deterministic synthetic fixtures (no secrets, data registration or internet required once dependencies are installed): format/lint (Ruff), Python type checks (mypy), unit/property/finance/integration tests (pytest), SQL/dbt data tests, frontend lint/typecheck/build, API-contract checks, deterministic end-to-end synthetic test. Split fast PR jobs from longer protected tests if runtime necessitates it, but never claim a missing job passed.
2. The software is installable with pinned, checked-in lockfiles (`uv.lock`, frontend lockfile), declared supported Python/Node runtime versions, and reproducible clean-clone instructions. No `latest` floating app dependencies, undeclared host prerequisites or environment-specific hardcoded paths. Include a documented WSL2/Linux workflow.
3. For security-sensitive changes: verify static/code analysis, dependency vulnerability alerts and synthetic publication-boundary tests; block any **known exploitable high/critical vulnerability** unless documented, mitigated, and explicitly accepted. Supply-chain controls: GitHub Actions pinned to verified full commit SHAs, default `permissions: contents: read`, no untrusted PR token exposure, sensible concurrency and job timeouts, avoid untrusted install/postinstall execution where possible.
4. A PR description links the issue, describes **why**, files/architecture affected, the risks, commands and proof, tests added, and rollback. Do not report pass until command was run or CI output observed. Keep cohesive, reviewable commits and PRs: no giant generated all-at-once changes or artificial microcommits.
5. No dead code, dormant placeholder modules, fake endpoints, silent TODOs presented as delivered, `except: pass` around financial or data errors, disabled tests, production-facing mock scores, or test data leaked into real-evaluation reports. The app must distinguish `fictional / synthetic-trained / privately validated / published` status visibly.

**Solo-repository protection:** after CI checks first exist, configure a public-repo branch protection rule/ruleset for `main` requiring PRs, appropriate unique successful status checks, blocking force pushes and branch deletion, and disallowing casual bypass. Do **not** require a human approving reviewer if there is no independent collaborator available; doing so could deadlock solo autonomous development. No branch policy is a substitute for independent engineering inspection.

## 2. Test and verification depth

| Component | Failure cases that must be demonstrated | Evidence |
|---|---|---|
| Financial ledger | zero prepayments; immediate full payoff; rate = 0; 360-payment amortization; prepayment/credit competing; maturity boundary; recoveries after lag; zero/negative-balance prevention; invariants under large shock and rounding; rates do not change contractual fixed coupon | Independent `Decimal` reference oracle, analytical examples, property/metamorphic tests, exact stated float tolerances; no-money-from-nowhere residual |
| Source ingestion | malformed ZIP, wrong release schema, duplicate and orphan loan-months, missing/gap periods, sentinel types, field reordering, out-of-range codes, partial interrupted run | Ingestion rejects/quarantines deterministically; checksums, row counts, lineage and retry/idempotency reports |
| Features and ML | t vs t-1 leakage; disjoint cutoff; baseline sanity; sample weighting; missing rate vintages; probability sum and calibration; prevalence shifts; test once | Point-in-time perturbation tests, frozen validation choice, holdout seal, model registry with data/config/git digests, real-vs-synthetic explicit |
| Serving | malformed request, invalid portfolio/shock, out-of-bound horizon, excessive payload, open redirect / traversal / arbitrary SQL, errors, timeout, synthetic-only asset/runtime | Strict schemas and negative API/security tests; image and shipped-asset inspection; bounded responses |
| Web UI | keyboard navigation, labels, responsive/mobile, loading/error/empty, scenario comparisons, accessible chart alternatives, no false empirical claims | Browser E2E tests (Playwright), manual screen/mobile audit, screenshot from actual running build |
| Operations | fresh clone, repeat execution, restart after failure, deterministic rerun, predictable cleanup, resource pressure | Documented runbook and command output; benchmark by machine/dataset and peak RSS |

Code coverage is **diagnostic** rather than a résumé number. Track line/branch coverage on the finance/domain core (target ≥90% line coverage for isolated pure finance, but exceptions must explain uncovered lines). No blanket 100% target and no tests that merely assert mocks were called. Include mutation or deliberately fault-injected checks for the few high-consequence finance invariants; record killed/survived mutations or precise fault proof. A passing test suite written by the implementation agent is not automatically evidence of financial correctness.

## 3. Measured performance, no benchmark theater

- Early baseline: `make benchmark` creates seeded synthetic scenarios and saves dataset size (loan count, observation count, rows/sec), peak RSS, wall time, environment versions, SQL plan highlights and API p50/p95 after warm-up. State hardware and repetitions.
- Compare before/after performance **only with matching conditions**, publish actual numbers and confidence/variance where applicable. Establish resource budgets from first representative baseline and record an ADR before enforcing them, rather than inventing thresholds before any benchmark.
- Profiling is required before optimizing. Prefer partition pruning, column selection, bulk I/O and DuckDB physical plans over premature complex caches. Demonstrate a pipeline re-run on unchanged input does not silently rewrite outputs, and changed input correctly invalidates downstream artifacts.
- Web response and memory budgets should be validated under controlled concurrent synthetic requests; report p95 and error rate, not an unverified 'fast' label.

## 4. Public repo and supply-chain hygiene

- README first-screen: real problem + one-sentence solution; **accurate status**; screenshot/GIF captured from running application only; online demo once deployed; architecture diagram with real modules; reproducible setup; exact data access limitations; verified performance and model results when permitted; limitations and future work. Explain the business consequence of prediction errors. No awards, fabricated traction or unmeasured percentages.
- Small coherent project tree with conventional package boundaries. No raw data, restricted model artifacts, local `.claude/settings.local.json`, machine paths, cache, generated build outputs, source maps containing secrets, notebooks exported with actual loan records, paid hosting tokens or test secrets in Git history, releases, Docker images, PR attachments, Pages, or Actions artifacts.
- Publish checklist scans the full **tracked set**, history of the release, Docker build context and *built public image* as feasible; a `.gitignore` by itself is insufficient. Public demo must not dynamically open private artifacts. Manual high-risk data-license review precedes any change to this boundary.
- Enable public GitHub protections available to the account (Dependabot alerts/updates, secret scanning/push protection, CodeQL where supported). Do not confuse 'configured' with 'scanned and clean'. Record limitations and scan evidence.
- Public visibility is **not** an open-source license. Do not silently choose MIT/Apache/GPL or grant redistribution rights. Ask the owner to select a code license before any public open-source licensing claim; Freddie Mac data rights remain separate.
- Provide useful `CONTRIBUTING.md`, `SECURITY.md`, and PR checklist only when the project can actually support the instructions. No fake responsible disclosure address or unavailable support channels. Keep docs short and consistent.

## 5. Evidence ledger and external-review package

Maintain public `docs/STATUS.md` (only non-sensitive summaries) with rows for each gate: `NOT BUILT`, `IMPLEMENTED-SYNTHETIC`, `VALIDATED-REAL-PRIVATE`, `PUBLIC-DEPLOYED`, and `BLOCKED` as appropriate, plus commit SHA, command/CI permalink, check date, source limitations and known fails. A test pass in CI is **not** a real-data trained-model claim. Private result artifacts are never pasted into public status without legal clearance.

At M2, M4 and M5 prepare a small reviewer packet under `docs/reviews/` (only public-safe facts): architecture/change summary, `git diff` or PR links, 5 highest-risk assumptions, passing/failing commands, benchmark evidence, known limitations and candidate interview questions. **Do not label agent self-review as independent.** The project owner can invite a second reviewer to assess these packets without interrupting development; critical findings become tracked fixes before a flagship-grade release.

Final audit: a separate clean clone in a blank environment; all documented synthetic commands verified; protected `main` and current public CI verified; no restricted material in published artifacts; deployed application visually and functionally tested; real-data modeling either actually evaluated and accurately disclosed as permitted, or explicitly marked blocked. An incomplete or unverified component must not appear as 'production-ready'.

## 6. How a skeptical engineer should evaluate Prepay

Within ~60 seconds they should find: what decision Prepay informs, architecture, running demo, actual status and how to reproduce. In a 10-minute code review they should be able to locate a mortgage event label, prove it is point-in-time safe, inspect an independent financial oracle, trace one source record through lineage (with synthetic fixture), examine a PR's CI checks, and understand a meaningful trade-off documented in an ADR. This, not commit count or framework quantity, is the standard.
