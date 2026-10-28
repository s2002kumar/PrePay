"""Seeded loan-level Monte Carlo of discrete outcomes (FINANCIAL_CONVENTIONS §6, test 10).

Each simulated path draws, per active loan and month, exactly one of {voluntary payoff, credit
disposition, remain active} from the same coherent hazards used by the expected ledger. The
across-path mean converges to :func:`prepay.finance.ledger.project`; the reported standard
errors describe **Monte Carlo sampling uncertainty only**, not model or parameter uncertainty.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay.finance.amortization import FloatArray, contractual_month
from prepay.finance.errors import FinanceInputError
from prepay.finance.ledger import CreditAssumptions, HazardPaths, LoanLines

INTERVAL_KIND = "monte_carlo_sampling"
MAX_PATHS = 100_000


@dataclass(frozen=True, slots=True)
class SimulatedLedger:
    """Across-path means and standard errors of pool monthly flows, each shaped ``(months,)``."""

    paths: int
    seed: int
    scheduled_principal_mean: FloatArray
    scheduled_principal_se: FloatArray
    voluntary_prepay_principal_mean: FloatArray
    voluntary_prepay_principal_se: FloatArray
    credit_exit_principal_mean: FloatArray
    credit_exit_principal_se: FloatArray
    ending_upb_mean: FloatArray
    ending_upb_se: FloatArray
    interval_kind: str = INTERVAL_KIND


def simulate(
    lines: LoanLines,
    hazards: HazardPaths,
    credit: CreditAssumptions,
    horizon_months: int,
    *,
    paths: int,
    seed: int,
) -> SimulatedLedger:
    """Simulate ``paths`` independent realizations of the pool with a seeded PCG64 generator."""
    lines.validate()
    credit.validate()
    hazards.validate(lines.count, horizon_months)
    if not 2 <= paths <= MAX_PATHS:
        raise FinanceInputError(f"paths must lie in [2, {MAX_PATHS}]")

    rng = np.random.Generator(np.random.PCG64(seed))
    balance = np.broadcast_to(lines.balance, (paths, lines.count)).copy()
    remaining = lines.remaining_payments.copy()
    flows = {name: np.zeros((paths, horizon_months)) for name in _FLOWS}
    for k in range(horizon_months):
        _, scheduled = contractual_month(balance, lines.annual_rate, remaining)
        after_scheduled = balance - scheduled
        draw = rng.random((paths, lines.count))
        prepaid = draw < hazards.prepay[:, k]
        disposed = ~prepaid & (draw < hazards.prepay[:, k] + hazards.credit[:, k])
        flows["scheduled_principal"][:, k] = scheduled.sum(axis=1)
        flows["voluntary_prepay_principal"][:, k] = (after_scheduled * prepaid).sum(axis=1)
        flows["credit_exit_principal"][:, k] = (after_scheduled * disposed).sum(axis=1)
        balance = np.where(prepaid | disposed, 0.0, after_scheduled)
        flows["ending_upb"][:, k] = balance.sum(axis=1)
        remaining = remaining - 1

    def mean(name: str) -> FloatArray:
        return np.asarray(flows[name].mean(axis=0), dtype=np.float64)

    def standard_error(name: str) -> FloatArray:
        return np.asarray(flows[name].std(axis=0, ddof=1) / np.sqrt(paths), dtype=np.float64)

    return SimulatedLedger(
        paths=paths,
        seed=seed,
        scheduled_principal_mean=mean("scheduled_principal"),
        scheduled_principal_se=standard_error("scheduled_principal"),
        voluntary_prepay_principal_mean=mean("voluntary_prepay_principal"),
        voluntary_prepay_principal_se=standard_error("voluntary_prepay_principal"),
        credit_exit_principal_mean=mean("credit_exit_principal"),
        credit_exit_principal_se=standard_error("credit_exit_principal"),
        ending_upb_mean=mean("ending_upb"),
        ending_upb_se=standard_error("ending_upb"),
    )


_FLOWS = (
    "scheduled_principal",
    "voluntary_prepay_principal",
    "credit_exit_principal",
    "ending_upb",
)
