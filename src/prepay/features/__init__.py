"""Point-in-time feature contract and the scenario feature state machine (ARCHITECTURE §5)."""

from prepay.features.machine import LoanStatics, RatePath, compute_features
from prepay.features.spec import CATEGORICAL, FEATURES, NUMERIC, FeatureSpec

__all__ = [
    "CATEGORICAL",
    "FEATURES",
    "NUMERIC",
    "FeatureSpec",
    "LoanStatics",
    "RatePath",
    "compute_features",
]
