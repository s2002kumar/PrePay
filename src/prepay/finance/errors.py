"""Typed failures raised by the finance engine. Invalid inputs are rejected, never repaired."""


class FinanceInputError(ValueError):
    """Loan terms, assumptions or horizon violate the engine's input contract."""


class InvalidHazardError(FinanceInputError):
    """Monthly outcome probabilities are not a valid (prepay, credit, active) simplex."""


class ConservationError(ArithmeticError):
    """A projected ledger failed a principal-conservation identity beyond tolerance."""
