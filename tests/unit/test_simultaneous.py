"""E01 uncertainty (ADR 0014 §6): one two-way bootstrap per fold, simultaneous classes."""

from __future__ import annotations

import numpy as np
import pytest

from prepay.evaluation.inference import _codes, _counts, two_way
from prepay.evaluation.simultaneous import (
    CellGroups,
    bonferroni_z,
    classify,
    fifth_masks,
    month_block_mean,
    paired,
    simultaneous,
    two_way_suite,
)

MODELS = ("A", "B", "C")


def _panel(seed: int = 7, loans: int = 300, months: int = 18) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    start = rng.integers(0, months, loans)
    end = np.minimum(start + rng.integers(1, months + 1, loans), months)
    loan = np.repeat(np.arange(loans), end - start)
    month = np.concatenate([np.arange(s, e) for s, e in zip(start, end, strict=True)])
    n = loan.shape[0]
    payoff = rng.uniform(0.002, 0.08, (n, len(MODELS)))
    observed = (rng.random(n) < payoff[:, 0]).astype(np.float64)
    log_loss = -np.log(np.where(observed[:, None] == 1.0, payoff, 1.0 - payoff))
    level = np.where(month < months // 2, 0, 1)
    level[rng.random(n) < 0.05] = -1  # rows in no cell of the dimension
    return {
        "loan": loan,
        "month": month,
        "payoff": payoff,
        "observed": observed,
        "log_loss": log_loss,
        "level": level,
    }


def _suite(p: dict[str, np.ndarray], **kwargs: object):  # type: ignore[no-untyped-def]
    cells = {"level": CellGroups(("early", "late"), p["level"])}
    return two_way_suite(
        p["loan"],
        p["month"],
        MODELS,
        p["log_loss"],
        p["payoff"],
        p["observed"],
        cells,
        **kwargs,  # type: ignore[arg-type]
    )


def test_paired_draws_equal_the_established_two_way_bootstrap() -> None:
    p = _panel()
    suite = _suite(p, replicates=60, seed=5)
    mine = suite.mean_log_loss_draws[:, 1] - suite.mean_log_loss_draws[:, 0]
    reference = two_way(
        p["loan"], p["month"], p["log_loss"][:, 1] - p["log_loss"][:, 0], replicates=60, seed=5
    )
    np.testing.assert_allclose(mine, reference, rtol=1e-10, atol=1e-13)
    out = paired(suite, "B", "A")
    assert out["estimate"] == pytest.approx(p["log_loss"][:, 1].mean() - p["log_loss"][:, 0].mean())
    assert out["relative_to_reference"] == pytest.approx(
        out["estimate"] / p["log_loss"][:, 0].mean()
    )
    assert out["se"] == pytest.approx(float(np.std(reference, ddof=1)))
    assert out["unadjusted_low"] <= out["unadjusted_high"]


def test_ratio_draws_equal_a_direct_weighted_computation() -> None:
    p = _panel(seed=3)
    suite = _suite(p, replicates=3, seed=11)
    rng = np.random.Generator(np.random.PCG64(11))
    loan_codes, n_loans = _codes(p["loan"])
    month_codes, n_months = _codes(p["month"])
    masks = fifth_masks(p["payoff"])
    for b in range(3):
        w = _counts(rng, n_loans)[loan_codes] * _counts(rng, n_months)[month_codes]
        expected = (w @ p["observed"]) / (w @ p["payoff"])
        np.testing.assert_allclose(suite.payoff_ae_draws[b], expected, rtol=1e-12)
        top = masks["top"][:, 1]
        np.testing.assert_allclose(
            suite.fifth_ae_draws["top"][b, 1],
            (w[top] @ p["observed"][top]) / (w[top] @ p["payoff"][top, 1]),
            rtol=1e-12,
        )
        late = p["level"] == 1
        np.testing.assert_allclose(
            suite.cell_ae_draws["level"][b, 1, 2],
            (w[late] @ p["observed"][late]) / (w[late] @ p["payoff"][late, 2]),
            rtol=1e-12,
        )
    # Unweighted estimates, and rows coded -1 belong to no cell.
    np.testing.assert_allclose(suite.payoff_ae, p["observed"].sum() / p["payoff"].sum(axis=0))
    early = p["level"] == 0
    np.testing.assert_allclose(
        suite.cell_ae["level"][0], p["observed"][early].sum() / p["payoff"][early].sum(axis=0)
    )


def test_chunking_changes_nothing() -> None:
    p = _panel(seed=9)
    whole = _suite(p, replicates=20, seed=2)
    chunked = _suite(p, replicates=20, seed=2, chunk_rows=97)
    np.testing.assert_allclose(chunked.mean_log_loss_draws, whole.mean_log_loss_draws, rtol=1e-12)
    np.testing.assert_allclose(chunked.payoff_ae_draws, whole.payoff_ae_draws, rtol=1e-12)
    np.testing.assert_allclose(
        chunked.cell_ae_draws["level"], whole.cell_ae_draws["level"], rtol=1e-12
    )


def test_fifths_split_each_models_rows_by_its_own_prediction() -> None:
    payoff = np.column_stack([np.arange(10.0), -np.arange(10.0)])
    masks = fifth_masks(payoff)
    assert masks["bottom"][:, 0].nonzero()[0].tolist() == [0, 1]
    assert masks["top"][:, 0].nonzero()[0].tolist() == [8, 9]
    assert masks["top"][:, 1].nonzero()[0].tolist() == [0, 1]


def test_bonferroni_z_grows_with_the_family() -> None:
    assert bonferroni_z(1) == pytest.approx(1.959964, abs=1e-5)
    assert bonferroni_z(30) == pytest.approx(3.1440, abs=1e-3)
    with pytest.raises(ValueError, match="at least one"):
        bonferroni_z(0)


@pytest.mark.parametrize(
    ("low", "high", "expected"),
    [
        (-0.003, -0.001, "lower_loss"),
        (0.001, 0.004, "higher_loss"),
        (-0.001, 0.0005, "non_inferior"),  # upper limit below the margin of 0.001
        (-0.001, 0.002, "inconclusive"),  # not significant, and not non-inferior either
        (None, None, "inconclusive"),
    ],
)
def test_classes_separate_non_inferiority_from_non_significance(
    low: float | None, high: float | None, expected: str
) -> None:
    assert classify(low, high, margin=0.001) == expected


def test_simultaneous_interval_is_a_wald_interval() -> None:
    assert simultaneous(0.01, 0.002, 3.0) == pytest.approx((0.004, 0.016))
    assert simultaneous(0.01, None, 3.0) == (None, None)


def test_month_block_mean_resamples_months() -> None:
    values = np.array([1.0, -1.0, 2.0, 0.5, -0.5, 1.5])
    out = month_block_mean(values, replicates=400, seed=1)
    assert out["estimate"] == pytest.approx(values.mean())
    assert out["low"] < out["estimate"] < out["high"]
    assert month_block_mean(values, replicates=400, seed=1) == out
    assert month_block_mean(np.array([]))["estimate"] is None


def test_inputs_must_line_up() -> None:
    p = _panel()
    with pytest.raises(ValueError, match="per model"):
        two_way_suite(
            p["loan"],
            p["month"],
            MODELS,
            p["log_loss"],
            p["payoff"][:, :2],
            p["observed"],
            {},
        )
