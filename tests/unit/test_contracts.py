"""SFLLD source contract: structure, value domains and release gating."""

from __future__ import annotations

import pytest

from prepay.contracts import Field, Kind, Layout
from prepay.contracts.sflld import (
    LAYOUT_ID,
    ORIGINATION,
    PERFORMANCE,
    RELEASES,
    SAMPLE_ARCHIVE,
    ZERO_BALANCE_CODES,
    UnsupportedReleaseError,
    layouts_for_release,
    sample_members,
)

# Pinned so that any change to positions, names, types or domains is a deliberate, reviewed edit.
# The header text of both layouts was compared byte-for-byte with Freddie Mac's official
# file_headers_july_2026.zip (sha256 db139053...) on 2026-10-28: identical.
ORIGINATION_FINGERPRINT = "e6d868e66b515ce95f2cb7455171d45c208791629ee0cd2f77bb372a6d8927dc"
PERFORMANCE_FINGERPRINT = "8910adb95d9a96dd21ece164b832557e0c7d5c567460b6d0c71d2c1bda224969"


def test_layout_widths_and_fingerprints_are_pinned() -> None:
    assert ORIGINATION.width == 31
    assert PERFORMANCE.width == 35
    assert ORIGINATION.fingerprint() == ORIGINATION_FINGERPRINT
    assert PERFORMANCE.fingerprint() == PERFORMANCE_FINGERPRINT


@pytest.mark.parametrize(
    ("layout", "name", "position"),
    [
        (ORIGINATION, "credit_score", 1),
        (ORIGINATION, "original_interest_rate", 13),
        (ORIGINATION, "loan_id", 20),
        (ORIGINATION, "original_loan_term", 22),
        (ORIGINATION, "vantage_score", 31),
        (PERFORMANCE, "loan_id", 1),
        (PERFORMANCE, "period", 2),
        (PERFORMANCE, "modification_flag", 8),
        (PERFORMANCE, "zero_balance_code", 9),
        (PERFORMANCE, "zero_balance_effective_date", 10),
        (PERFORMANCE, "delinquency_due_to_disaster", 29),
        (PERFORMANCE, "servicer_name", 34),
    ],
)
def test_key_field_positions(layout: Layout, name: str, position: int) -> None:
    assert layout.field(name).position == position


def test_zero_balance_codes_match_user_guide() -> None:
    assert tuple(ZERO_BALANCE_CODES) == ("01", "02", "03", "09", "15", "16", "96")
    assert PERFORMANCE.field("zero_balance_code").codes == tuple(ZERO_BALANCE_CODES)


@pytest.mark.parametrize(
    ("layout", "name", "raw", "ok"),
    [
        (ORIGINATION, "credit_score", "742", True),
        (ORIGINATION, "credit_score", "9999", True),  # documented "Not Available" sentinel
        (ORIGINATION, "credit_score", "299", False),
        (ORIGINATION, "loan_id", "F21Q1000123", False),  # 11 characters
        (ORIGINATION, "loan_id", "F21Q10001234", True),
        (ORIGINATION, "loan_id", "F21Q50001234", False),  # quarter 5
        (ORIGINATION, "first_payment_date", "202113", False),
        (ORIGINATION, "first_payment_date", "202112", True),
        (ORIGINATION, "mi_pct", "0", True),  # 0 = No MI is a value, not missing
        (ORIGINATION, "mi_pct", "56", False),
        (ORIGINATION, "occupancy_status", "X", False),
        (ORIGINATION, "postal_code", "000", True),
        (ORIGINATION, "postal_code", "90210", False),  # R47+ discloses 3 digits only
        (ORIGINATION, "original_interest_rate", "6.875", True),
        (ORIGINATION, "original_interest_rate", "abc", False),
        (ORIGINATION, "msa", "", True),  # null = not in an MSA or unknown
        (ORIGINATION, "msa", "12345", True),
        (PERFORMANCE, "delinquency_status", "00", True),
        (PERFORMANCE, "delinquency_status", "0", False),  # pre-R47 single-digit coding
        (PERFORMANCE, "delinquency_status", "RA", True),
        (PERFORMANCE, "delinquency_status", "XX", True),
        (PERFORMANCE, "zero_balance_code", "06", False),
        (PERFORMANCE, "payment_deferral_flag", "Y", False),  # pre-R47 coding; R47+ uses C/P
        (PERFORMANCE, "net_sales_proceeds", "-123456.78", True),
        (PERFORMANCE, "net_sales_proceeds", "C", False),
        (PERFORMANCE, "current_actual_upb", "123456.78", True),
        (PERFORMANCE, "loan_age", "-1", True),
    ],
)
def test_field_domains(layout: Layout, name: str, raw: str, ok: bool) -> None:
    assert (layout.field(name).violation(raw) is None) is ok


def test_supported_releases_share_the_verified_layout() -> None:
    assert set(RELEASES) == {47, 48}
    assert all(r.layout_id == LAYOUT_ID for r in RELEASES.values())
    assert RELEASES[48].performance_cutoff == "2026-06-30"
    assert layouts_for_release(48) == (ORIGINATION, PERFORMANCE)


@pytest.mark.parametrize("release", [1, 30, 46, 49])
def test_unverified_releases_are_refused(release: int) -> None:
    with pytest.raises(UnsupportedReleaseError, match="not supported"):
        layouts_for_release(release)


def test_sample_naming_convention() -> None:
    match = SAMPLE_ARCHIVE.fullmatch("sample_2021.zip")
    assert match is not None
    assert match["vintage"] == "2021"
    assert SAMPLE_ARCHIVE.fullmatch("historical_data_2021Q1.zip") is None
    assert sample_members(2021) == ("sample_orig_2021.txt", "sample_perf_2021.txt")


def test_layout_rejects_misordered_or_duplicate_fields() -> None:
    a = Field(1, "a", "A", Kind.TEXT, 1)
    with pytest.raises(ValueError, match="positions"):
        Layout("x", "y", "|", (Field(2, "a", "A", Kind.TEXT, 1),))
    with pytest.raises(ValueError, match="duplicate"):
        Layout("x", "y", "|", (a, Field(2, "a", "B", Kind.TEXT, 1)))


def test_fingerprint_ignores_source_citations() -> None:
    bare = Layout(ORIGINATION.layout_id, ORIGINATION.file_kind, "|", ORIGINATION.fields)
    assert bare.fingerprint() == ORIGINATION.fingerprint()
