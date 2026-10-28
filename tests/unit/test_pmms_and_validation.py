"""FRED CSV parsing, local fetch (no network), and vectorized/scalar validator parity."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from hypothesis import given
from hypothesis import strategies as st

from prepay.contracts.sflld import ORIGINATION, PERFORMANCE
from prepay.contracts.validate import violation_mask
from prepay.ingest import pmms

GOOD = "observation_date,MORTGAGE30US\n2026-10-08,7.40\n2026-10-15,.\n2026-10-22,7.32\n"


def test_parse_valid_csv_with_missing_marker() -> None:
    obs = pmms.parse_fred_csv(GOOD, "MORTGAGE30US")
    assert [d.isoformat() for d in obs.dates] == ["2026-10-08", "2026-10-15", "2026-10-22"]
    assert obs.rate_pct == (7.40, None, 7.32)
    assert obs.missing == 1
    assert obs.source_rows == (2, 3, 4)


def test_legacy_date_header_is_accepted() -> None:
    assert pmms.parse_fred_csv("DATE,MORTGAGE15US\n2001-01-04,6.5\n", "MORTGAGE15US").dates


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "empty"),
        ("observation_date,MORTGAGE15US\n2026-10-08,7.4\n", "header"),
        ("observation_date,MORTGAGE30US\n2026-10-15,7.4\n2026-10-08,7.3\n", "increasing"),
        ("observation_date,MORTGAGE30US\n2026-13-01,7.4\n", "invalid date"),
        ("observation_date,MORTGAGE30US\n2026-10-08,seven\n", "non-numeric"),
        ("observation_date,MORTGAGE30US\n2026-10-08,740\n", "outside"),
        ("observation_date,MORTGAGE30US\n2026-10-08,7.4,x\n", "2 fields"),
        ("observation_date,MORTGAGE30US\n", "no observations"),
    ],
)
def test_format_violations_are_rejected(text: str, message: str) -> None:
    with pytest.raises(pmms.PmmsFormatError, match=message):
        pmms.parse_fred_csv(text, "MORTGAGE30US")


class _Response(io.BytesIO):
    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_fetch_validates_and_records_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested: list[str] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        requested.append(request.full_url)
        return _Response(GOOD.encode())

    monkeypatch.setattr(pmms.urllib.request, "urlopen", fake_urlopen)
    sidecar = pmms.fetch_series("MORTGAGE30US", tmp_path)
    assert requested == ["https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US"]
    assert (tmp_path / "MORTGAGE30US.csv").read_text() == GOOD
    recorded = json.loads((tmp_path / "MORTGAGE30US.retrieval.json").read_text())
    assert recorded == sidecar
    assert recorded["bytes"] == len(GOOD.encode())

    monkeypatch.setattr(
        pmms.urllib.request, "urlopen", lambda request, timeout: _Response(b"<html>error</html>")
    )
    with pytest.raises(pmms.PmmsFormatError):
        pmms.fetch_series("MORTGAGE15US", tmp_path)
    assert not (tmp_path / "MORTGAGE15US.csv").exists()
    with pytest.raises(ValueError, match="unsupported"):
        pmms.fetch_series("DGS10", tmp_path)


FIELDS = [*ORIGINATION.fields, *PERFORMANCE.fields]
interesting = st.one_of(
    st.text(alphabet="0123456789.-+eERAXYNPFC| ", max_size=14),
    st.sampled_from(
        [
            "",
            "9999",
            "999",
            "XX",
            "RA",
            "00",
            "01",
            "1e5",
            " 12",
            "٣",
            "F21Q10001234",
            "202112",
            "202113",
            "6.875",
            "-12.50",
            "000",
            "12345",
        ]
    ),
)


@given(st.sampled_from(FIELDS), st.lists(interesting, min_size=1, max_size=40))
def test_vectorized_validator_matches_scalar(field: Any, values: list[str]) -> None:
    mask = violation_mask(field, pa.array(values, pa.string())).to_pylist()
    assert mask == [field.violation(v) is not None for v in values]
