"""Pure fixed-rate mortgage pool cash-flow engine (no I/O, no model calls, float64).

See ``docs/FINANCIAL_CONVENTIONS.md`` for the binding ledger definitions.
"""

from prepay.finance.errors import ConservationError, FinanceInputError, InvalidHazardError
from prepay.finance.ledger import (
    CreditAssumptions,
    HazardPaths,
    LoanLines,
    PoolLedger,
    Projection,
    conservation_residuals,
    project,
)
from prepay.finance.metrics import (
    cash_wal_years,
    cpr_model,
    credit_exit_rate,
    exposure_exit_wal_years,
    horizon_summary,
    smm_model,
)
from prepay.finance.rates import cpr_from_smm, psa_cpr, psa_smm, smm_from_cpr

__all__ = [
    "ConservationError",
    "CreditAssumptions",
    "FinanceInputError",
    "HazardPaths",
    "InvalidHazardError",
    "LoanLines",
    "PoolLedger",
    "Projection",
    "cash_wal_years",
    "conservation_residuals",
    "cpr_from_smm",
    "cpr_model",
    "credit_exit_rate",
    "exposure_exit_wal_years",
    "horizon_summary",
    "project",
    "psa_cpr",
    "psa_smm",
    "smm_from_cpr",
    "smm_model",
]
