"""Expected monthly principal-exposure and illustrative cash ledger for fixed-rate loan lines.

Implements ``docs/FINANCIAL_CONVENTIONS.md`` §2 exactly. Per line and month ``t``:

- ``B_t`` beginning exposure, ``I_t = B_t * c / 12`` accrued contractual interest;
- ``SP_t`` scheduled principal (schedule-before-exit convention), ``R_t = B_t - SP_t``;
- ``PP_t = p_t * R_t`` full voluntary payoff, ``DC_t = d_t * R_t`` credit-disposition exposure exit;
- ``B_{t+1} = R_t - PP_t - DC_t``.

``DC_t`` terminates exposure but is **not** a cash receipt. It resolves ``L`` months later into
an illustrative recovery ``(1 - severity) * DC_t`` and an illustrative loss ``severity * DC_t``;
resolutions due after the horizon are carried in an explicit tail. The engine is pure: no model
calls, no I/O, no rounding (monetary values are rounded only when formatted for output).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay.arrays import FloatArray, IntArray
from prepay.finance.amortization import contractual_month
from prepay.finance.errors import ConservationError, FinanceInputError, InvalidHazardError

#: Absolute tolerance on ``p + d + s = 1`` for each line-month.
SIMPLEX_ATOL = 1e-9
#: Conservation residuals must be below this fraction of initial pool exposure (plus 1e-9 USD).
CONSERVATION_RTOL = 1e-9
#: Maximum supported annual note rate (decimal). Rates above this are rejected as implausible.
MAX_ANNUAL_RATE = 1.0
#: Maximum projection length in months: 40 years of exposure plus recovery lags.
MAX_HORIZON_MONTHS = 600


@dataclass(frozen=True, slots=True)
class LoanLines:
    """Fixed-rate loan lines at the start of projection month 1.

    Attributes:
        balance: outstanding principal ``B_1`` per line, currency units, ``>= 0``.
        annual_rate: contractual note rate per line, decimal per year, in ``[0, 1]``.
            Market-rate scenarios never change this value.
        remaining_payments: contractual payments remaining including month 1, ``>= 1`` for any
            line with positive balance.
    """

    balance: FloatArray
    annual_rate: FloatArray
    remaining_payments: IntArray

    @classmethod
    def from_values(
        cls,
        balance: FloatArray | list[float],
        annual_rate: FloatArray | list[float],
        remaining_payments: IntArray | list[int],
    ) -> LoanLines:
        lines = cls(
            balance=np.asarray(balance, dtype=np.float64),
            annual_rate=np.asarray(annual_rate, dtype=np.float64),
            remaining_payments=np.asarray(remaining_payments, dtype=np.int64),
        )
        lines.validate()
        return lines

    @property
    def count(self) -> int:
        return int(self.balance.shape[0])

    def validate(self) -> None:
        arrays = (self.balance, self.annual_rate, self.remaining_payments)
        if any(a.ndim != 1 for a in arrays):
            raise FinanceInputError("loan line arrays must be one-dimensional")
        if len({a.shape[0] for a in arrays}) != 1:
            raise FinanceInputError("loan line arrays must have equal length")
        if not (np.all(np.isfinite(self.balance)) and np.all(np.isfinite(self.annual_rate))):
            raise FinanceInputError("balances and rates must be finite")
        if np.any(self.balance < 0.0):
            raise FinanceInputError("balances must be non-negative")
        if np.any((self.annual_rate < 0.0) | (self.annual_rate > MAX_ANNUAL_RATE)):
            raise FinanceInputError(f"annual_rate must lie in [0, {MAX_ANNUAL_RATE}]")
        if np.any((self.balance > 0.0) & (self.remaining_payments < 1)):
            raise FinanceInputError("a line with positive balance needs remaining_payments >= 1")


@dataclass(frozen=True, slots=True)
class HazardPaths:
    """Coherent month-``t`` outcome probabilities per line, each shaped ``(lines, months)``.

    ``prepay`` is P(full voluntary early payoff), ``credit`` is P(terminal credit-related
    disposition) and ``active`` is P(remain active), all conditional on being active at the start
    of month ``t``. They must be non-negative and sum to one within :data:`SIMPLEX_ATOL`.
    """

    prepay: FloatArray
    credit: FloatArray
    active: FloatArray

    @classmethod
    def from_prepay_credit(cls, prepay: FloatArray, credit: FloatArray) -> HazardPaths:
        """Build a simplex from (prepay, credit), deriving ``active = 1 - prepay - credit``.

        No clipping: if ``prepay + credit > 1`` the derived ``active`` is negative and
        :meth:`validate` rejects it.
        """
        p = np.asarray(prepay, dtype=np.float64)
        d = np.asarray(credit, dtype=np.float64)
        return cls(prepay=p, credit=d, active=1.0 - p - d)

    @classmethod
    def constant(cls, lines: int, months: int, prepay: float, credit: float) -> HazardPaths:
        shape = (lines, months)
        return cls.from_prepay_credit(np.full(shape, prepay), np.full(shape, credit))

    @property
    def shape(self) -> tuple[int, int]:
        return (int(self.prepay.shape[0]), int(self.prepay.shape[1]))

    def validate(self, lines: int, months: int) -> None:
        for name, arr in (
            ("prepay", self.prepay),
            ("credit", self.credit),
            ("active", self.active),
        ):
            if arr.shape != (lines, months):
                raise InvalidHazardError(
                    f"{name} hazards have shape {arr.shape}, expected {(lines, months)}"
                )
            if not np.all(np.isfinite(arr)):
                raise InvalidHazardError(f"{name} hazards contain non-finite values")
            if np.any(arr < 0.0):
                worst = float(arr.min())
                raise InvalidHazardError(f"{name} hazards are negative (min {worst:.3g})")
        total = self.prepay + self.credit + self.active
        deviation = float(np.max(np.abs(total - 1.0))) if total.size else 0.0
        if deviation > SIMPLEX_ATOL:
            raise InvalidHazardError(
                f"hazards do not sum to 1 (max deviation {deviation:.3g} > {SIMPLEX_ATOL})"
            )


@dataclass(frozen=True, slots=True)
class CreditAssumptions:
    """Illustrative credit-resolution assumptions (not calibrated loss estimates).

    Attributes:
        severity: fraction of credit-disposition principal not recovered, in ``[0, 1]``.
        recovery_lag_months: months between exposure exit and resolution, ``>= 0``.
    """

    severity: float
    recovery_lag_months: int

    def validate(self) -> None:
        if not (np.isfinite(self.severity) and 0.0 <= self.severity <= 1.0):
            raise FinanceInputError("severity must lie in [0, 1]")
        if self.recovery_lag_months < 0:
            raise FinanceInputError("recovery_lag_months must be >= 0")


@dataclass(frozen=True, slots=True)
class PoolLedger:
    """Pool-level monthly ledger (sums over lines). Every array has shape ``(months,)``.

    Month ``k`` of the arrays is projection month ``t = k + 1``. Monetary units follow the input
    balances. ``pending_*_after_horizon`` hold credit resolutions scheduled beyond the horizon.
    """

    beginning_upb: FloatArray
    contractual_interest_accrued: FloatArray
    scheduled_principal: FloatArray
    balance_after_scheduled: FloatArray
    voluntary_prepay_principal: FloatArray
    credit_exit_principal: FloatArray
    recoveries_received: FloatArray
    illustrative_credit_loss: FloatArray
    ending_upb: FloatArray
    pending_recoveries_after_horizon: float
    pending_losses_after_horizon: float

    @property
    def months(self) -> int:
        return int(self.beginning_upb.shape[0])

    @property
    def initial_upb(self) -> float:
        return float(self.beginning_upb[0]) if self.months else 0.0

    @property
    def principal_cash(self) -> FloatArray:
        """Principal cash received per month: scheduled + voluntary payoff + recoveries."""
        return self.scheduled_principal + self.voluntary_prepay_principal + self.recoveries_received

    @property
    def exposure_resolved(self) -> bool:
        """True when all exposure has exited and every credit resolution falls in the horizon."""
        tail = self.pending_recoveries_after_horizon + self.pending_losses_after_horizon
        scale = max(self.initial_upb, 1.0)
        return bool(self.ending_upb[-1] <= CONSERVATION_RTOL * scale and tail <= 0.0)


@dataclass(frozen=True, slots=True)
class LineLedger:
    """Optional per-line detail, each array shaped ``(lines, months)``; used by audits/tests."""

    beginning_upb: FloatArray
    contractual_interest_accrued: FloatArray
    scheduled_principal: FloatArray
    voluntary_prepay_principal: FloatArray
    credit_exit_principal: FloatArray
    ending_upb: FloatArray


@dataclass(frozen=True, slots=True)
class Projection:
    pool: PoolLedger
    lines: LineLedger | None


def project(
    lines: LoanLines,
    hazards: HazardPaths,
    credit: CreditAssumptions,
    horizon_months: int,
    *,
    keep_lines: bool = False,
) -> Projection:
    """Project the expected monthly ledger for ``horizon_months`` months.

    Raises:
        FinanceInputError: invalid loan terms, assumptions or horizon.
        InvalidHazardError: hazards are not a valid simplex of the right shape.
        ConservationError: the resulting ledger violates a conservation identity (a bug).
    """
    lines.validate()
    credit.validate()
    if not 1 <= horizon_months <= MAX_HORIZON_MONTHS:
        raise FinanceInputError(f"horizon_months must lie in [1, {MAX_HORIZON_MONTHS}]")
    hazards.validate(lines.count, horizon_months)

    h = horizon_months
    pool = {name: np.zeros(h) for name in _POOL_FIELDS}
    detail = {name: np.zeros((lines.count, h)) for name in _LINE_FIELDS} if keep_lines else None
    pending_recoveries = 0.0
    pending_losses = 0.0

    balance = lines.balance.copy()
    remaining = lines.remaining_payments.copy()
    lag = credit.recovery_lag_months
    for k in range(h):
        interest, scheduled = contractual_month(balance, lines.annual_rate, remaining)
        after_scheduled = balance - scheduled
        prepaid = hazards.prepay[:, k] * after_scheduled
        disposed = hazards.credit[:, k] * after_scheduled
        ending = _non_negative(after_scheduled - prepaid - disposed, after_scheduled)

        pool["beginning_upb"][k] = balance.sum()
        pool["contractual_interest_accrued"][k] = interest.sum()
        pool["scheduled_principal"][k] = scheduled.sum()
        pool["balance_after_scheduled"][k] = after_scheduled.sum()
        pool["voluntary_prepay_principal"][k] = prepaid.sum()
        pool["credit_exit_principal"][k] = disposed.sum()
        pool["ending_upb"][k] = ending.sum()

        disposed_total = float(disposed.sum())
        recovery = (1.0 - credit.severity) * disposed_total
        loss = credit.severity * disposed_total
        if k + lag < h:
            pool["recoveries_received"][k + lag] += recovery
            pool["illustrative_credit_loss"][k + lag] += loss
        else:
            pending_recoveries += recovery
            pending_losses += loss

        if detail is not None:
            detail["beginning_upb"][:, k] = balance
            detail["contractual_interest_accrued"][:, k] = interest
            detail["scheduled_principal"][:, k] = scheduled
            detail["voluntary_prepay_principal"][:, k] = prepaid
            detail["credit_exit_principal"][:, k] = disposed
            detail["ending_upb"][:, k] = ending

        balance = ending
        remaining = remaining - 1

    ledger = PoolLedger(
        **pool,
        pending_recoveries_after_horizon=pending_recoveries,
        pending_losses_after_horizon=pending_losses,
    )
    assert_conserved(ledger)
    line_ledger = LineLedger(**detail) if detail is not None else None
    return Projection(pool=ledger, lines=line_ledger)


_POOL_FIELDS = (
    "beginning_upb",
    "contractual_interest_accrued",
    "scheduled_principal",
    "balance_after_scheduled",
    "voluntary_prepay_principal",
    "credit_exit_principal",
    "recoveries_received",
    "illustrative_credit_loss",
    "ending_upb",
)
_LINE_FIELDS = (
    "beginning_upb",
    "contractual_interest_accrued",
    "scheduled_principal",
    "voluntary_prepay_principal",
    "credit_exit_principal",
    "ending_upb",
)


def _non_negative(ending: FloatArray, after_scheduled: FloatArray) -> FloatArray:
    """Flush float rounding residue below zero to exactly zero; reject anything larger.

    When ``p + d = 1`` the closing balance is ``R - pR - dR``, which can round to ``-1e-17 * R``.
    A genuinely negative balance would mean invalid hazards and is never silently repaired.
    """
    tolerance = SIMPLEX_ATOL * after_scheduled + 1e-12
    if np.any(ending < -tolerance):
        raise ConservationError("projected closing balance is negative beyond rounding tolerance")
    return np.asarray(np.maximum(ending, 0.0), dtype=np.float64)


@dataclass(frozen=True, slots=True)
class ConservationResiduals:
    """Largest absolute residual (currency units) of each ledger identity."""

    exposure_identity: float  # max_t |B_t - SP_t - PP_t - DC_t - B_{t+1}|
    continuity: float  # max_t |ending_t - beginning_{t+1}|
    resolution: float  # |sum DC - sum RC - sum loss - pending tail|
    total_principal: float  # |B_1 - cash - losses - ending UPB - pending tail|
    tolerance: float

    @property
    def worst(self) -> float:
        return max(self.exposure_identity, self.continuity, self.resolution, self.total_principal)

    @property
    def ok(self) -> bool:
        return self.worst <= self.tolerance


def conservation_residuals(ledger: PoolLedger) -> ConservationResiduals:
    """Evaluate every principal-conservation identity of a pool ledger."""
    exposure = ledger.beginning_upb - (
        ledger.scheduled_principal
        + ledger.voluntary_prepay_principal
        + ledger.credit_exit_principal
        + ledger.ending_upb
    )
    continuity = ledger.ending_upb[:-1] - ledger.beginning_upb[1:]
    tail = ledger.pending_recoveries_after_horizon + ledger.pending_losses_after_horizon
    resolution = (
        ledger.credit_exit_principal.sum()
        - ledger.recoveries_received.sum()
        - ledger.illustrative_credit_loss.sum()
        - tail
    )
    total = (
        ledger.initial_upb
        - ledger.principal_cash.sum()
        - ledger.illustrative_credit_loss.sum()
        - (ledger.ending_upb[-1] if ledger.months else 0.0)
        - tail
    )
    return ConservationResiduals(
        exposure_identity=float(np.max(np.abs(exposure))) if exposure.size else 0.0,
        continuity=float(np.max(np.abs(continuity))) if continuity.size else 0.0,
        resolution=abs(float(resolution)),
        total_principal=abs(float(total)),
        tolerance=CONSERVATION_RTOL * max(ledger.initial_upb, 1.0) + 1e-9,
    )


def assert_conserved(ledger: PoolLedger) -> None:
    residuals = conservation_residuals(ledger)
    if not residuals.ok:
        raise ConservationError(f"ledger violates principal conservation: {residuals}")
