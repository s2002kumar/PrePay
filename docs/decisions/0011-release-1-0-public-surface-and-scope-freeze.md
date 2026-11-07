# ADR 0011: Prepay 1.0: static public site, live container, and a research freeze

- Status: accepted
- Date: 2026-11-02
- Scope: deployment, `src/prepay/api/static.py`, `web/`, project scope after R2

## Context

On 2026-11-02 the owner set the finish line for Prepay 1.0:
- a polished, publicly accessible, synthetic-only product;
- complete scenario workflows, verified against the audited engine;
- deployment with no paid resources unless the owner authorizes them;
- no new model families, external datasets, experiments or infrastructure, unless they fix a
  concrete release-blocking defect;
- no research milestones after R2 without a separate owner decision.

ADR 0005 built the demo as one container: API plus UI, from a synthetic-trained bundle. Every
host that runs that container unchanged needs an owner account: Hugging Face Spaces, Render,
Fly.io or Cloud Run. Most of their free tiers are also below the container's measured footprint
(DEPLOYMENT). Creating accounts and accepting terms is the owner's action, not the agent's.

## Decisions

1. **The public 1.0 surface is a static site on GitHub Pages**, built from the same synthetic
   bundle. GitHub Pages is free for this public repository and needs no new account. Turning
   it on publishes a website, so the owner does it once, in the repository settings.
   - `prepay demo static-site` asks the API (a test client on the bundle) for every response
     on a fixed grid:
     - the 4 fictional pools;
     - 13 scenarios: flat, and parallel shifts of ±50 to ±300 bp in 50 bp steps;
     - every comparison among them, plus none;
     - 6 horizons;
     - the default credit assumptions.
   - Each scenario's monthly ledger is stored once.
   - Every covered response is rebuilt from the written files, and the build fails unless it
     equals the API's response exactly.
   - The UI's static adapter mirrors that assembly. A browser test requires the static site to
     show exactly what the live app shows for the same inputs.
2. **The live container remains the full product.** It is the only place to enter custom rate
   paths and to change the credit assumptions. The static site says so where those controls
   would be. The container is built and health-checked in CI and runs locally with one
   command. Hosting it publicly waits for the owner's choice of provider and account.
3. **Release-blocking performance and memory defects are fixed, not deferred** (#30):
   - duplicate projections removed;
   - categorical encoding vectorized, with output identical by test;
   - bounded per-result cache memory.

   These change no model, feature or financial formula.
4. **Research is frozen after R2.**
   - The prospective forward evaluation (ADR 0010) and the private development runs continue
     separately, on the owner's machine.
   - Nothing about them changes the public product, which shows a synthetic-trained model
     only.
   - New model families, external economic data (including the equity proxy of
     `docs/research/HPI_EQUITY_PROXY.md`) and new experiments need a separate owner decision.
5. **1.0 acceptance** is judged against the criteria in
   `docs/reviews/RELEASE_1.0_ACCEPTANCE.md`. That report states which criteria passed, with
   evidence, and which defects remain.

## Consequences

- The public site can't run arbitrary scenarios. In exchange it is fast, free, needs no server,
  and has no rate limits or cold starts.
- Grid, horizons and credit defaults are fixed in code (`STATIC_SCENARIOS`, `HORIZONS`) and in
  the UI (`web/src/static.ts`). Tests pin both.
- Rebuilding the site means rerunning the pipeline on the `dev` preset. `pages.yml` does this
  on every push to `main`.

## Amendment 1 (2026-11-07): a separate Prepay 2.0 research phase

The owner made the separate decision that §4 requires (ADR 0013, decision record). §4 is
amended **only** as follows:

1. **A Prepay 2.0 real-data modeling research phase is authorized.** Its objective: compare
   the existing statistical and ML models rigorously, investigate the documented rate-regime
   failures, and change the payoff model only where evidence supports a specific change.
2. **It proceeds in gates, each approved by the owner.** Gate A: repair the failed development
   queue and specify the first experiment. Each experiment runs only after its
   pre-registration is accepted. The first is E01, economic generalization (ADR 0014).
3. **It reuses existing families and data.** It adds no new external economic data. The equity
   proxy of `docs/research/HPI_EQUITY_PROXY.md` still needs decision O3. A new model family
   needs its own ADR and owner approval.
4. **Preserved without change:**
   - the sealed primary run, its seal and its first evaluation;
   - the forward registration of 2026-11-02 and its members;
   - the released B+ product, including its synthetic-only boundary.
5. **The public product is unchanged by this amendment.** No real-trained model is served or
   published (ADR 0013, decision D3). A historical research view needs the terms decision and
   a later owner approval (decision D2).

§1–§3 and §5 are unchanged.
