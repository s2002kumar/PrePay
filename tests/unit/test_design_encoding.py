"""The vectorized categorical encoding equals the per-row reference it replaced, exactly."""

from __future__ import annotations

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st

from prepay.features.batch import PanelBatch
from prepay.modeling.design import MISSING, Preprocessor, _as_text, _text_codes

VALUES = st.one_of(
    st.none(),
    st.sampled_from(["P", "C", "N", "Y", "15y", "30y", "west", "__other__", "", "nan"]),
    st.integers(min_value=-3, max_value=13),
    st.booleans(),
    st.floats(allow_nan=True, allow_infinity=False, width=32),
)


def _reference_one_hot(pre: Preprocessor, values: np.ndarray, name: str) -> np.ndarray:
    """The row-by-row implementation before the vectorized one (kept as the oracle)."""
    text = np.asarray(_as_text(values), dtype=object)
    known = pre.levels[name]
    columns = [text == level for level in known]
    columns.append(text == MISSING)
    columns.append((text != MISSING) & ~np.isin(text, known))
    return np.column_stack(columns).astype(np.float64)


def _reference_tree_codes(pre: Preprocessor, values: np.ndarray, name: str) -> np.ndarray:
    code = {level: float(i) for i, level in enumerate(pre.levels[name])}
    return np.array([code.get(t, np.nan) for t in _as_text(values)])


def _preprocessor(levels: list[str]) -> Preprocessor:
    return Preprocessor((), ("c",), {}, {}, {}, {"c": levels}, {})


def _batch(values: np.ndarray) -> PanelBatch:
    n = values.shape[0]
    return PanelBatch(
        loan_id=np.arange(n).astype(object),
        target_month=np.zeros(n, dtype=np.int64),
        outcome_class=np.zeros(n, dtype=np.int64),
        exposure_upb=np.zeros(n),
        features={"c": values},
    )


@settings(max_examples=300, deadline=None)
@given(
    rows=st.lists(VALUES, min_size=0, max_size=60),
    levels=st.lists(
        st.sampled_from(["P", "C", "Y", "1", "12", "True", "nan", "west"]), unique=True
    ),
)
def test_text_codes_and_encodings_match_the_row_loop(rows: list[object], levels: list[str]) -> None:
    values = np.empty(len(rows), dtype=object)
    values[:] = rows
    texts, codes = _text_codes(values)
    assert [texts[c] for c in codes] == _as_text(values)

    pre = _preprocessor(sorted(levels))
    expected = _reference_one_hot(pre, values, "c") if rows else np.zeros((0, len(levels) + 2))
    assert np.array_equal(pre.one_hot(_batch(values), "c"), expected)
    tree = pre.tree_matrix(_batch(values))
    assert tree.shape == (len(rows), 1)
    np.testing.assert_array_equal(tree[:, 0], _reference_tree_codes(pre, values, "c"))


def test_month_of_year_integers_encode_as_their_text() -> None:
    values = np.array([1, 12, 7, None, 12], dtype=object)
    pre = _preprocessor(["1", "12"])
    np.testing.assert_array_equal(
        pre.one_hot(_batch(values), "c"),
        [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0], [0, 1, 0, 0]],
    )
