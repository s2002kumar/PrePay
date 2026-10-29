"""Failure-hypothesis probes (D1, D2, D6/D7) on a world with a known era confound."""

from __future__ import annotations

import numpy as np
import pytest

from prepay.features.batch import PanelBatch
from prepay.modeling.challengers import ConstrainedHazard, FactoredGbm
from prepay.modeling.design import Preprocessor
from prepay.modeling.models import GbmModel
from prepay.modeling.probes import (
    era_encoding,
    probe_models,
    set_incentive,
    shift_level,
    stability_summary,
)
from tests.unit.test_challengers import make_world


@pytest.fixture(scope="module")
def fitted() -> tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]]:
    train, valid = make_world(40_000, 11), make_world(12_000, 12)
    pre = Preprocessor.fit(train)
    models: dict[str, object] = {
        "M1": GbmModel.fit(train, valid, pre, num_leaves=15, max_rounds=200),
        "X1": FactoredGbm.fit(
            train, valid, pre, variant="X1_factored_gbm", num_leaves=15, max_rounds=200
        ),
        "H1": ConstrainedHazard.fit(train, pre, l2=1e-4),
    }
    incentive = np.asarray(train.features["incentive_bps"])
    support = {
        "incentive_bps": {
            "low": float(np.quantile(incentive, 0.005)),
            "high": float(np.quantile(incentive, 0.995)),
        }
    }
    return train, valid, models, support


def test_set_incentive_moves_the_market_rate_coherently(
    fitted: tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]],
) -> None:
    _, valid, _, _ = fitted
    probed = set_incentive(valid, -150.0)
    f, g = valid.features, probed.features
    np.testing.assert_allclose(g["incentive_bps"], -150.0)
    np.testing.assert_allclose((g["note_rate_pct"] - g["market_rate_t1"]) * 100, -150.0)
    shift = (np.asarray(f["market_rate_t1"]) - g["market_rate_t1"]) * 100
    np.testing.assert_allclose(g["new_opportunity_bps"] - f["new_opportunity_bps"], shift)
    assert np.all(g["payment_saving_pct"] < 0)  # refinancing at a higher rate costs more


def test_shift_level_keeps_incentive_and_gaps(
    fitted: tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]],
) -> None:
    _, valid, _, _ = fitted
    up = shift_level(set_incentive(valid, 100.0), 200.0)
    base = set_incentive(valid, 100.0)
    np.testing.assert_allclose(up.features["incentive_bps"], base.features["incentive_bps"])
    np.testing.assert_allclose(up.features["market_rate_t1"] - base.features["market_rate_t1"], 2)
    np.testing.assert_array_equal(
        up.features["new_opportunity_bps"], base.features["new_opportunity_bps"]
    )
    # The same 100 bp gap saves less of the payment at higher levels (rows with positive rates;
    # the toy world also draws some impossible negative note rates).
    valid_rows = np.asarray(base.features["market_rate_t1"]) > 0.5
    assert valid_rows.mean() > 0.9
    up_saving = up.features["payment_saving_pct"][valid_rows]
    assert np.all(up_saving < base.features["payment_saving_pct"][valid_rows])


def test_level_probe_flags_the_confounded_gbm_but_not_level_free_models(
    fitted: tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]],
) -> None:
    """Known answer: in this world the rate level is an era proxy (RELIABILITY_PLAN H-ERA)."""
    _, valid, models, support = fitted
    report = probe_models(models, valid.slice(0, 1500), support)  # type: ignore[arg-type]
    flags = report["flags"]
    assert flags["M1"]["level_raises_payoffs"] is True
    assert flags["M1"]["level_relative_change_plus_200bp"] > 0.10
    for name in ("X1", "H1"):
        assert flags[name]["level_relative_change_plus_200bp"] == pytest.approx(0.0, abs=1e-12)
        assert flags[name]["level_raises_payoffs"] is False
    curve = report["probes"]["rate_level_at_fixed_incentive"]["models"]["X1"]["mean_smm"]
    assert max(curve) == pytest.approx(min(curve), abs=1e-15)


def test_tail_probe_separates_flat_trees_from_the_constrained_hazard(
    fitted: tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]],
) -> None:
    _, valid, models, support = fitted
    report = probe_models(models, valid.slice(0, 1500), support)  # type: ignore[arg-type]
    assert report["flags"]["X1"]["flat_extrapolation"] is True
    assert report["flags"]["H1"]["flat_extrapolation"] is False
    assert report["flags"]["H1"]["tail_decline_per_100bp_below_support"] > 0.05
    assert report["probes"]["incentive"]["training_support"] == support["incentive_bps"]
    for name in models:
        assert report["probes"]["incentive"]["models"][name]["mean_smm"]
    assert report["probes"]["burnout"]["models"]["H1"]["ice_violation_share"] == 0.0


def test_era_encoding_flags_the_rate_level_not_the_incentive(
    fitted: tuple[PanelBatch, PanelBatch, dict[str, object], dict[str, dict[str, float]]],
) -> None:
    train, _, _, _ = fitted
    report = era_encoding(train)
    assert "market_rate_t1" in report["flagged"]
    assert report["features"]["market_rate_t1"]["auc"] == pytest.approx(1.0)
    assert report["features"]["incentive_bps"]["flag"] is False
    assert report["early_share"] == pytest.approx(0.5, abs=0.02)


def test_stability_summary_compares_spread_with_family_gaps() -> None:
    summary = stability_summary(
        {"a": [0.100, 0.101, 0.099], "b": [0.110, 0.140, 0.080]},
        {"a": [[0.01, 0.02], [0.0101, 0.0201]], "b": [[0.01, 0.02], [0.02, 0.01]]},
    )
    assert summary["smallest_between_family_gap"] == pytest.approx(0.010)
    assert summary["families"]["a"]["unstable"] is False
    assert summary["families"]["b"]["unstable"] is True
