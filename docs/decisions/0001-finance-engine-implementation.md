# ADR 0001: Finance engine implementation choices

- Status: accepted
- Date: 2026-10-28
- Scope: `src/prepay/finance/` (implements `docs/FINANCIAL_CONVENTIONS.md` v2.0; no convention changed)

## Context

FINANCIAL_CONVENTIONS §2 fixes the ledger identities but leaves several numerical and bookkeeping
details to the implementation. Each choice below is nonblocking and does not change a locked
economic definition.

## Decisions

1. **Coherent hazards are validated, never repaired.** The engine takes `(prepay, credit, active)`
   per line-month. Each must be finite and non-negative, and their sum must be within `1e-9` of 1.
   Anything else raises `InvalidHazardError`. `HazardPaths.from_prepay_credit` derives
   `active = 1 - p - d` without clipping, so `p + d > 1` is rejected rather than hidden.
2. **Credit resolution timing.** Credit-disposition exposure `DC_t` exits in month `t`. Its
   illustrative recovery `(1 - severity) * DC_t` *and* its illustrative loss `severity * DC_t` are
   both recognized in the resolution month `t + L`. Resolutions after the horizon are carried as
   `pending_recoveries_after_horizon` / `pending_losses_after_horizon`. This keeps the cash ledger
   (`SP + PP + RC`) separate from exposure exits, as §2 requires.
3. **Final contractual payment is exact.** At `n_t = 1` scheduled principal is set to exactly
   `B_t`. Without this, float rounding leaves up to ~1e-9 of residual balance in about a quarter of
   cases (measured over 1M random balances and rates). A mutation test checks this.
4. **Rounding residue on closing balances.** When `p + d = 1`, `R - pR - dR` can round to a tiny
   negative number. Values within `1e-9 * R + 1e-12` below zero are set to exactly zero; anything
   more negative raises `ConservationError`.
5. **Self-checking conservation.** Every `project()` call evaluates four identities (monthly
   exposure, month-to-month continuity, credit resolution, total principal) and raises
   `ConservationError` if any residual exceeds `1e-9 x initial pool UPB + 1e-9`.
6. **Undefined is not zero.** SMM/CPR/credit-exit rates with a zero denominator are NaN (the API
   will serialise them as `null`). Cash WAL is `None` unless all exposure and all recoveries fall
   inside the horizon. Exposure-exit WAL is `None` unless all exposure has exited.
7. **Bounds.** Annual note rate in `[0, 1]`; horizon in `[1, 600]` months (360 months of exposure
   plus long recovery lags). The public API applies its own tighter bounds.
8. **Market rates are not an engine input.** The engine's signature has no market-rate argument,
   so a rate scenario can only affect projections through hazards. FINANCIAL_CONVENTIONS §6.7 is
   tested at the scenario layer, where rate paths exist.

## Verification

- Independent oracle `tests/financial/oracle.py` (60-digit `Decimal`, direct annuity power, scalar
  loops) is compared month by month at a relative tolerance of `1e-9` of initial balance.
- Hypothesis property tests over random pools, simplex hazards and assumptions (derandomized in CI).
- Targeted mutation testing (`tests/financial/test_mutation_kills.py`): eight deliberate faults in
  amortization, payoff, recovery, continuity, hazard validation and SMM; all must be killed.

## Consequences

Numerical edge cases fail loudly instead of drifting. The engine stays pure (no I/O, no model
calls), so the API and research pipeline share one audited implementation.
