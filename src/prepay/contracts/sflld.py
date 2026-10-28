"""Freddie Mac Single-Family Loan-Level Dataset (SFLLD) Standard file layout, Release 47+.

Transcribed from the official file layout, header files and General User Guide listed in
:data:`SOURCES` (fetched 2026-10-28, pinned by SHA-256). Release 47 (July 2026) introduced this
layout; Release 48 (October 2026) states only data additions and corrections, and its guide,
layout workbook and header files match it field for field. See ``docs/decisions/0002``.

Releases 46 and earlier use a different 32/32-field layout. Two of its positions are only implied
by the disclosure-changes summary, so it is deliberately **not** implemented. Ingest refuses those
releases instead of guessing column positions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from prepay.contracts.layout import Field, Kind, Layout, SourceDocument

LAYOUT_ID = "sflld-2026-07"

SOURCES = (
    SourceDocument(
        title="SFLLD General User Guide, Release 48, October 2026",
        url="https://www.freddiemac.com/fmac-resources/research/pdf/user_guide.pdf",
        sha256="0884a958ebfd58afe18bb2f856bb43e886685cad6b554f04dc5f18a53faebfd0",
        retrieved="2026-10-28",
    ),
    SourceDocument(
        title="SFLLD File Layout (July 2026)",
        url="https://www.freddiemac.com/fmac-resources/research/pdf/file_layout_july_2026.xlsx",
        sha256="e4ee4ba00b5b1a8d18e2debe3acafdd019b48bafafdeb907cf5b19b49c989f23",
        retrieved="2026-10-28",
    ),
    SourceDocument(
        title="SFLLD File Headers (July 2026)",
        url="https://www.freddiemac.com/fmac-resources/research/docs/file_headers_july_2026.zip",
        sha256="db1390531ca9ea9ce11de2b2e1f42114dba5461d7e10a0eb508a4f464ff9e25a",
        retrieved="2026-10-28",
    ),
    SourceDocument(
        title="SFLLD Disclosure Changes Effective July 2026, v1.2",
        url="https://www.freddiemac.com/fmac-resources/research/pdf/disclosure-changes-summary.pdf",
        sha256="e513ccc06fca13880a541442b393a655e1b5904fd1a97e79cf7f56808f1fa2f0",
        retrieved="2026-10-28",
    ),
    SourceDocument(
        title="SFLLD Release Notes, Release 48, October 2026",
        url="https://www.freddiemac.com/fmac-resources/research/pdf/release_notes.pdf",
        sha256="8c5382463d67e36be17221c35697942c75a9457742eb6790117583e7fbbf019b",
        retrieved="2026-10-28",
    ),
)

LOAN_ID_PATTERN = r"[FA]\d{2}Q[1-4]\d{7}"
MONTH_PATTERN = r"(19|20)\d{2}(0[1-9]|1[0-2])"
YES_NO = ("Y", "N")


def _month(position: int, name: str, header: str) -> Field:
    return Field(position, name, header, Kind.MONTH, 6, pattern=MONTH_PATTERN)


def _amount(position: int, name: str, header: str, max_length: int = 12) -> Field:
    return Field(position, name, header, Kind.DECIMAL, max_length, pattern=r"-?\d+(\.\d+)?")


ORIGINATION = Layout(
    layout_id=LAYOUT_ID,
    file_kind="origination",
    delimiter="|",
    sources=SOURCES,
    fields=(
        Field(
            1,
            "credit_score",
            "CLASSIC FICO",
            Kind.INTEGER,
            4,
            missing=("9999",),
            value_range=(300, 850),
        ),
        _month(2, "first_payment_date", "FIRST PAYMENT DATE"),
        Field(
            3,
            "first_time_homebuyer",
            "FIRST TIME HOMEBUYER INDICATOR",
            Kind.CODE,
            1,
            codes=YES_NO,
            missing=("9",),
        ),
        _month(4, "maturity_date", "MATURITY DATE"),
        Field(
            5,
            "msa",
            "METROPOLITAN STATISTICAL AREA (MSA) OR METROPOLITAN DIVISION",
            Kind.TEXT,
            5,
            pattern=r"\d{5}",
        ),
        Field(
            6,
            "mi_pct",
            "MORTGAGE INSURANCE PERCENTAGE (MI %)",
            Kind.INTEGER,
            3,
            missing=("999",),
            value_range=(0, 55),
        ),
        Field(
            7,
            "number_of_units",
            "NUMBER OF UNITS",
            Kind.INTEGER,
            2,
            missing=("99",),
            value_range=(1, 4),
        ),
        Field(
            8,
            "occupancy_status",
            "OCCUPANCY STATUS",
            Kind.CODE,
            1,
            codes=("P", "I", "S"),
            missing=("9",),
        ),
        Field(
            9,
            "original_cltv",
            "ORIGINAL COMBINED LOAN-TO-VALUE (CLTV)",
            Kind.INTEGER,
            3,
            missing=("999",),
            value_range=(1, 998),
        ),
        Field(
            10,
            "original_dti",
            "ORIGINAL DEBT-TO-INCOME (DTI) RATIO",
            Kind.INTEGER,
            3,
            missing=("999",),
            value_range=(0, 65),
        ),
        Field(11, "original_upb", "ORIGINAL UPB", Kind.INTEGER, 12, value_range=(1, 1e11)),
        Field(
            12,
            "original_ltv",
            "ORIGINAL LOAN-TO-VALUE (LTV)",
            Kind.INTEGER,
            3,
            missing=("999",),
            value_range=(1, 998),
        ),
        Field(
            13,
            "original_interest_rate",
            "ORIGINAL INTEREST RATE",
            Kind.DECIMAL,
            6,
            pattern=r"\d+(\.\d+)?",
            value_range=(0, 100),
        ),
        Field(14, "channel", "CHANNEL", Kind.CODE, 1, codes=("R", "B", "C", "T"), missing=("9",)),
        Field(15, "prepayment_penalty", "PREPAYMENT PENALTY INDICATOR", Kind.CODE, 1, codes=YES_NO),
        Field(16, "amortization_type", "AMORTIZATION TYPE", Kind.CODE, 5, codes=("FRM", "ARM")),
        Field(17, "property_state", "PROPERTY STATE", Kind.TEXT, 2, pattern=r"[A-Z]{2}"),
        Field(
            18,
            "property_type",
            "PROPERTY TYPE",
            Kind.CODE,
            2,
            codes=("CP", "CO", "PU", "SF", "MH"),
            missing=("99",),
        ),
        Field(19, "postal_code", "POSTAL CODE", Kind.TEXT, 3, pattern=r"\d{3}", missing=("000",)),
        Field(20, "loan_id", "LOAN IDENTIFIER", Kind.IDENTIFIER, 12, pattern=LOAN_ID_PATTERN),
        Field(
            21,
            "loan_purpose",
            "LOAN PURPOSE",
            Kind.CODE,
            1,
            codes=("P", "C", "N", "R"),
            missing=("9",),
        ),
        Field(
            22, "original_loan_term", "ORIGINAL LOAN TERM", Kind.INTEGER, 3, value_range=(1, 999)
        ),
        Field(
            23,
            "number_of_borrowers",
            "NUMBER OF BORROWERS",
            Kind.INTEGER,
            2,
            missing=("99",),
            value_range=(1, 10),
        ),
        Field(24, "seller_name", "SELLER NAME", Kind.TEXT, 60),
        Field(25, "super_conforming", "SUPER CONFORMING FLAG", Kind.CODE, 1, codes=YES_NO),
        Field(
            26,
            "pre_harp_loan_id",
            "PRE-HARP LOAN SEQUENCE NUMBER",
            Kind.IDENTIFIER,
            12,
            pattern=LOAN_ID_PATTERN,
        ),
        Field(
            27,
            "special_eligibility_program",
            "SPECIAL ELIGIBILITY PROGRAM",
            Kind.CODE,
            1,
            codes=("H", "F", "R"),
        ),
        Field(28, "harp_indicator", "HARP INDICATOR", Kind.CODE, 1, codes=YES_NO),
        Field(
            29,
            "property_valuation_method",
            "PROPERTY VALUATION METHOD",
            Kind.CODE,
            1,
            codes=("1", "2", "3", "4"),
            missing=("7",),
        ),
        Field(30, "interest_only", "INTEREST ONLY (I/O) INDICATOR", Kind.CODE, 1, codes=YES_NO),
        Field(
            31,
            "vantage_score",
            "VANTAGESCORE 4.0",
            Kind.INTEGER,
            4,
            missing=("9999",),
            value_range=(300, 850),
        ),
    ),
)

#: Zero-balance codes and their official meaning (General User Guide, Release 48, p.11).
ZERO_BALANCE_CODES = {
    "01": "Prepaid or Matured (Voluntary Payoff)",
    "02": "Third Party Sale",
    "03": "Short Sale or Charge Off",
    "09": "REO Disposition",
    "15": "Whole Loan Sales",
    "16": "Reperforming Loan Securitizations",
    "96": "Confirmed Underwriting Defect or Major Servicing Defect prior to credit event",
}

DELINQUENCY_CODES = (*(f"{n:02d}" for n in range(100)), "RA")

PERFORMANCE = Layout(
    layout_id=LAYOUT_ID,
    file_kind="performance",
    delimiter="|",
    sources=SOURCES,
    fields=(
        Field(1, "loan_id", "LOAN IDENTIFIER", Kind.IDENTIFIER, 12, pattern=LOAN_ID_PATTERN),
        _month(2, "period", "PERIOD"),
        _amount(3, "current_actual_upb", "CURRENT ACTUAL UPB"),
        Field(
            4,
            "delinquency_status",
            "CURRENT LOAN DELINQUENCY STATUS",
            Kind.CODE,
            3,
            codes=DELINQUENCY_CODES,
            missing=("XX",),
        ),
        Field(5, "loan_age", "LOAN AGE", Kind.INTEGER, 3, pattern=r"-?\d+"),
        Field(
            6,
            "remaining_months",
            "REMAINING MONTHS TO LEGAL MATURITY",
            Kind.INTEGER,
            3,
            pattern=r"-?\d+",
        ),
        _month(
            7,
            "defect_settlement_date",
            "UNDERWRITING DEFECT AND MAJOR SERVICING DEFECT SETTLEMENT DATE",
        ),
        Field(8, "modification_flag", "MODIFICATION FLAG", Kind.CODE, 1, codes=("Y", "P")),
        Field(
            9,
            "zero_balance_code",
            "ZERO BALANCE CODE",
            Kind.CODE,
            2,
            codes=tuple(ZERO_BALANCE_CODES),
        ),
        _month(10, "zero_balance_effective_date", "ZERO BALANCE EFFECTIVE DATE"),
        Field(
            11,
            "current_interest_rate",
            "CURRENT INTEREST RATE",
            Kind.DECIMAL,
            8,
            pattern=r"\d+(\.\d+)?",
            value_range=(0, 100),
        ),
        _amount(12, "current_non_interest_bearing_upb", "CURRENT NON-INTEREST BEARING UPB"),
        _month(13, "ddlpi", "DUE DATE OF LAST PAID INSTALLMENT (DDLPI)"),
        _amount(14, "mi_recoveries", "MI RECOVERIES"),
        _amount(15, "net_sales_proceeds", "NET SALES PROCEEDS", max_length=14),
        _amount(16, "non_mi_recoveries", "NON MI RECOVERIES"),
        _amount(17, "total_expenses", "TOTAL EXPENSES"),
        _amount(18, "legal_costs", "LEGAL COSTS"),
        _amount(19, "maintenance_preservation_costs", "MAINTENANCE AND PRESERVATION COSTS"),
        _amount(20, "taxes_insurance", "TAXES AND INSURANCE"),
        _amount(21, "miscellaneous_expenses", "MISCELLANEOUS EXPENSES"),
        _amount(22, "actual_loss", "ACTUAL LOSS"),
        _amount(23, "cumulative_modification_costs", "CUMULATIVE MODIFICATION COSTS"),
        Field(
            24,
            "interest_rate_step_indicator",
            "INTEREST RATE STEP INDICATOR",
            Kind.CODE,
            1,
            codes=YES_NO,
        ),
        Field(25, "payment_deferral_flag", "PAYMENT DEFERRAL FLAG", Kind.CODE, 1, codes=("C", "P")),
        Field(
            26,
            "estimated_ltv",
            "ESTIMATED LOAN-TO-VALUE (ELTV)",
            Kind.INTEGER,
            4,
            missing=("999",),
            value_range=(1, 998),
        ),
        _amount(27, "zero_balance_removal_upb", "ZERO BALANCE REMOVAL UPB"),
        _amount(28, "delinquent_accrued_interest", "DELINQUENT ACCRUED INTEREST"),
        Field(
            29,
            "delinquency_due_to_disaster",
            "DELINQUENCY DUE TO DISASTER",
            Kind.CODE,
            1,
            codes=("Y",),
        ),
        Field(
            30,
            "borrower_assistance_plan",
            "BORROWER ASSISTANCE PLAN",
            Kind.CODE,
            1,
            codes=("F", "R", "T"),
        ),
        _amount(31, "current_period_modification_costs", "CURRENT PERIOD MODIFICATION COSTS"),
        _amount(32, "current_interest_bearing_upb", "CURRENT INTEREST BEARING UPB"),
        Field(
            33,
            "mi_cancellation_indicator",
            "MORTGAGE INSURANCE CANCELLATION INDICATOR",
            Kind.CODE,
            1,
            codes=YES_NO,
            missing=("7",),
        ),
        Field(34, "servicer_name", "SERVICER NAME", Kind.TEXT, 60),
        _amount(35, "bankruptcy_cramdown_costs", "BANKRUPTCY CRAMDOWN COSTS"),
    ),
)


@dataclass(frozen=True, slots=True)
class Release:
    """An SFLLD release and the layout its files use (Release Notes, Release 48)."""

    number: int
    published: str
    origination_cutoff: str
    performance_cutoff: str
    layout_id: str


RELEASES = {
    47: Release(47, "2026-07-29", "2026-03-31", "2026-03-31", LAYOUT_ID),
    48: Release(48, "2026-10-28", "2026-06-30", "2026-06-30", LAYOUT_ID),
}


class UnsupportedReleaseError(ValueError):
    """The requested release has no verified layout in this codebase."""


def layouts_for_release(release: int) -> tuple[Layout, Layout]:
    """Return ``(origination, performance)`` layouts for a supported release."""
    if release not in RELEASES:
        raise UnsupportedReleaseError(
            f"SFLLD release {release} is not supported. Releases 47-48 use the verified "
            f"{LAYOUT_ID} layout; releases <= 46 use an older layout whose positions are not "
            "fully proven by an official artifact in hand, so they are refused rather than "
            "guessed. Add a new layout with its official source documents to support it."
        )
    return ORIGINATION, PERFORMANCE


SAMPLE_ARCHIVE = re.compile(r"sample_(?P<vintage>(19|20)\d{2})\.zip")


def sample_members(vintage: int) -> tuple[str, str]:
    """Member names inside ``sample_YYYY.zip`` (General User Guide, 'Dataset Naming Convention')."""
    return f"sample_orig_{vintage}.txt", f"sample_perf_{vintage}.txt"
