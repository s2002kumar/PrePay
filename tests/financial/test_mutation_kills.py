"""Targeted mutation testing of high-consequence finance invariants (ENGINEERING_STANDARD §2).

Each mutant copies ``src/prepay`` to a temporary directory, applies one deliberate fault and runs
the finance suite against the mutated copy in a subprocess. A mutant is *killed* when that suite
fails. The unmodified copy must pass, proving the harness itself works. Survivors are not hidden:
a mutant listed here that survives fails this test.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SUITE = [
    "tests/financial/test_ledger_oracle.py",
    "tests/financial/test_rates_metrics.py",
]

# (id, module path relative to src/prepay, original snippet, faulty replacement)
MUTANTS = [
    (
        "payoff-on-pre-scheduled-balance",
        "finance/ledger.py",
        "prepaid = hazards.prepay[:, k] * after_scheduled",
        "prepaid = hazards.prepay[:, k] * balance",
    ),
    (
        "annuity-off-by-one-term",
        "finance/amortization.py",
        "-np.expm1(-n_safe * np.log1p(i_safe))",
        "-np.expm1(-(n_safe - 1.0) * np.log1p(i_safe))",
    ),
    (
        "interest-wrong-periodicity",
        "finance/amortization.py",
        "interest = b * (c / 12.0)",
        "interest = b * (c / 12.5)",
    ),
    (
        "credit-exit-recovered-in-full",
        "finance/ledger.py",
        'pool["recoveries_received"][k + lag] += recovery',
        'pool["recoveries_received"][k + lag] += disposed_total',
    ),
    (
        "exits-ignored-for-next-month",
        "finance/ledger.py",
        "balance = ending\n",
        "balance = after_scheduled\n",
    ),
    (
        "negative-hazards-accepted",
        "finance/ledger.py",
        "if np.any(arr < 0.0):",
        "if np.any(arr < -1.0):",
    ),
    (
        "final-payment-not-forced",
        "finance/amortization.py",
        "scheduled = np.where(n == 1, b, scheduled)",
        "scheduled = scheduled",
    ),
    (
        "smm-uses-beginning-balance",
        "finance/metrics.py",
        "_safe_ratio(ledger.voluntary_prepay_principal, ledger.balance_after_scheduled)",
        "_safe_ratio(ledger.voluntary_prepay_principal, ledger.beginning_upb)",
    ),
]


def run_suite_against(package_root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(package_root), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *SUITE,
            "-x",
            "-q",
            "-p",
            "no:cacheprovider",
            "--no-header",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )


def copy_package(tmp_path: Path) -> Path:
    target = tmp_path / "src"
    shutil.copytree(
        ROOT / "src" / "prepay", target / "prepay", ignore=shutil.ignore_patterns("__pycache__")
    )
    return target


@pytest.mark.slow
def test_unmutated_copy_passes(tmp_path: Path) -> None:
    result = run_suite_against(copy_package(tmp_path))
    assert result.returncode == 0, result.stdout[-2000:]


@pytest.mark.slow
@pytest.mark.parametrize(
    ("mutant", "module", "original", "replacement"), MUTANTS, ids=[m[0] for m in MUTANTS]
)
def test_mutant_is_killed(
    tmp_path: Path, mutant: str, module: str, original: str, replacement: str
) -> None:
    root = copy_package(tmp_path)
    path = root / "prepay" / module
    source = path.read_text(encoding="utf-8")
    assert source.count(original) == 1, f"{mutant}: snippet must occur exactly once"
    path.write_text(source.replace(original, replacement), encoding="utf-8")
    result = run_suite_against(root)
    assert result.returncode != 0, f"mutant {mutant} SURVIVED:\n{result.stdout[-2000:]}"
