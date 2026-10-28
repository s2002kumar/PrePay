"""Render simulated blocks as SFLLD ``sflld-2026-07`` text columns (pyarrow string tables).

Formatting is vectorized with Arrow compute kernels: fixed-point amounts are built from integer
cents, so values are exact and never rendered in scientific notation.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pyarrow as pa
import pyarrow.compute as pc

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray
from prepay.contracts.sflld import ORIGINATION, PERFORMANCE
from prepay.synthetic.simulate import (
    DEFERRAL_CURRENT,
    DEFERRAL_PRIOR,
    DQ_REO,
    MOD_CURRENT,
    MOD_NONE,
    MOD_PRIOR,
    PLAN_FORBEARANCE,
    SimulatedBlock,
)

ELTV_FIRST_MONTH = periods.month(2017, 4)
CRAMDOWN_FIRST_MONTH = periods.month(2025, 10)
MSA_CODES = np.array(["12060", "16980", "19100", "26420", "31080", "33100", "35620", "38060"])


def _str(values: npt.ArrayLike) -> pa.Array:
    return pa.array(np.asarray(values), type=pa.string())


def fmt_int(values: npt.ArrayLike) -> pa.Array:
    return pc.cast(pa.array(np.asarray(values, dtype=np.int64)), pa.string())


def fmt_fixed(values: FloatArray, decimals: int) -> pa.Array:
    """Fixed-point decimal strings, e.g. ``-1234.50`` for ``decimals=2``."""
    scale = 10**decimals
    scaled = np.round(np.asarray(values, dtype=np.float64) * scale).astype(np.int64)
    magnitude = np.abs(scaled)
    whole = fmt_int(magnitude // scale)
    frac = pc.utf8_lpad(fmt_int(magnitude % scale), width=decimals, padding="0")
    number = pc.binary_join_element_wise(whole, frac, ".")
    sign = _str(np.where(scaled < 0, "-", ""))
    return pc.binary_join_element_wise(sign, number, "")


def fmt_month(months: IntArray) -> pa.Array:
    m = np.asarray(months, dtype=np.int64)
    return fmt_int((m // 12) * 100 + m % 12 + 1)


def blank_unless(mask: BoolArray, values: pa.Array) -> pa.Array:
    return pc.if_else(pa.array(np.asarray(mask, dtype=bool)), values, pa.scalar(""))


def sentinel_int(values: FloatArray, sentinel: str) -> pa.Array:
    finite = ~np.isnan(values)
    return pc.if_else(pa.array(finite), fmt_int(np.where(finite, values, 0)), pa.scalar(sentinel))


def origination_table(block: SimulatedBlock, rng: np.random.Generator) -> pa.Table:
    o = block.originations
    n = o.count
    msa = np.where(rng.random(n) < 0.85, rng.choice(MSA_CODES, n), "")
    columns = {
        "credit_score": sentinel_int(o.fico, "9999"),
        "first_payment_date": fmt_month(o.first_payment),
        "first_time_homebuyer": _str(o.first_time_buyer),
        "maturity_date": fmt_month(o.maturity),
        "msa": _str(msa),
        "mi_pct": sentinel_int(o.mi_pct, "999"),
        "number_of_units": fmt_int(o.units),
        "occupancy_status": _str(o.occupancy),
        "original_cltv": sentinel_int(o.cltv, "999"),
        "original_dti": sentinel_int(o.dti, "999"),
        "original_upb": fmt_int(o.original_upb),
        "original_ltv": sentinel_int(o.ltv, "999"),
        "original_interest_rate": fmt_fixed(o.note_rate, 3),
        "channel": _str(o.channel),
        "prepayment_penalty": _str(np.full(n, "N")),
        "amortization_type": _str(np.full(n, "FRM")),
        "property_state": _str(o.state),
        "property_type": _str(o.property_type),
        "postal_code": _str(o.postal),
        "loan_id": _str(o.loan_id),
        "loan_purpose": _str(o.purpose),
        "original_loan_term": fmt_int(o.term),
        "number_of_borrowers": fmt_int(o.borrowers),
        "seller_name": _str(o.seller),
        "super_conforming": _str(o.super_conforming),
        "pre_harp_loan_id": _str(np.full(n, "")),
        "special_eligibility_program": _str(o.special_program),
        "harp_indicator": _str(np.full(n, "N")),
        "property_valuation_method": _str(o.valuation_method),
        "interest_only": _str(np.full(n, "N")),
        "vantage_score": sentinel_int(o.vantage, "9999"),
    }
    return pa.table(
        [columns[name] for name in ORIGINATION.column_names], names=list(ORIGINATION.column_names)
    )


def performance_table(block: SimulatedBlock, rng: np.random.Generator, cutoff: int) -> pa.Table:
    o, g = block.originations, block.grid
    loan, col = np.nonzero(g.valid)  # row-major: sorted by loan, then period
    period = g.first_month + col
    rows = loan.size

    zb = g.zero_balance_code[loan, col]
    terminal = zb > 0
    mod = g.modification[loan, col]
    age = g.age[loan, col]
    upb = g.upb[loan, col]
    rounded = (age <= 6) & (upb > 500) & (mod == MOD_NONE)
    upb = np.where(rounded, np.round(upb / 1000.0) * 1000.0, upb)
    dq = g.delinquency[loan, col]

    removal = g.removal_upb[loan, col]
    credit_exit = np.isin(zb, [2, 3, 9])
    loss_row = credit_exit | (zb == 15)
    rate = g.note_rate[loan, col]
    mi_pct = np.nan_to_num(o.mi_pct[loan])
    severity_draw = rng.uniform(0.55, 0.85, rows)
    net_sales = -removal * np.where(zb == 15, rng.uniform(0.9, 0.99, rows), severity_draw)
    legal = removal * rng.uniform(0.01, 0.02, rows) * credit_exit
    maintenance = removal * rng.uniform(0.01, 0.03, rows) * credit_exit
    taxes = removal * rng.uniform(0.01, 0.02, rows) * credit_exit
    misc = removal * rng.uniform(0.0, 0.005, rows) * credit_exit
    expenses = legal + maintenance + taxes + misc
    months_dq = g.months_delinquent_at_exit[loan]
    accrued = removal * rate / 1200.0 * np.maximum(months_dq, 1) * loss_row
    mi_recovery = -removal * mi_pct / 100.0 * rng.uniform(0.5, 1.0, rows) * credit_exit
    non_mi = -removal * rng.uniform(0.0, 0.01, rows) * credit_exit
    actual_loss = removal + net_sales + accrued + expenses + mi_recovery + non_mi
    loss_known = loss_row & (period <= cutoff - 3)

    value_growth = 1.003 ** (period - o.origination_month[loan])
    home_value = (
        o.original_upb[loan] / (np.nan_to_num(o.ltv[loan], nan=80.0) / 100.0) * value_growth
    )
    eltv = np.clip(np.round(upb / home_value * 100.0), 1, 998)
    eltv_text = pc.if_else(pa.array(np.isnan(o.ltv[loan])), pa.scalar("999"), fmt_int(eltv))

    def money(values: FloatArray, mask: BoolArray) -> pa.Array:
        return blank_unless(mask, fmt_fixed(values, 2))

    deferral = g.deferral[loan, col]
    loan_ids = np.array(o.loan_id)[loan]
    columns = {
        "loan_id": _str(loan_ids),
        "period": fmt_month(period),
        "current_actual_upb": fmt_fixed(upb, 2),
        "delinquency_status": pc.if_else(
            pa.array(dq == DQ_REO),
            pa.scalar("RA"),
            pc.utf8_lpad(fmt_int(np.maximum(dq, 0)), width=2, padding="0"),
        ),
        "loan_age": fmt_int(age),
        "remaining_months": fmt_int(g.remaining[loan, col]),
        "defect_settlement_date": blank_unless(zb == 96, fmt_month(period)),
        "modification_flag": _str(
            np.select([mod == MOD_CURRENT, mod == MOD_PRIOR], ["Y", "P"], "")
        ),
        "zero_balance_code": blank_unless(
            terminal, pc.utf8_lpad(fmt_int(zb), width=2, padding="0")
        ),
        "zero_balance_effective_date": blank_unless(terminal, fmt_month(period)),
        "current_interest_rate": fmt_fixed(rate, 3),
        "current_non_interest_bearing_upb": fmt_fixed(np.zeros(rows), 2),
        "ddlpi": blank_unless(~terminal & (dq >= 0), fmt_month(period - np.maximum(dq, 0))),
        "mi_recoveries": money(mi_recovery, credit_exit),
        "net_sales_proceeds": money(net_sales, loss_row),
        "non_mi_recoveries": money(non_mi, credit_exit),
        "total_expenses": money(expenses, credit_exit),
        "legal_costs": money(legal, credit_exit),
        "maintenance_preservation_costs": money(maintenance, credit_exit),
        "taxes_insurance": money(taxes, credit_exit),
        "miscellaneous_expenses": money(misc, credit_exit),
        "actual_loss": money(actual_loss, loss_known),
        "cumulative_modification_costs": money(g.cumulative_mod_cost[loan, col], mod != MOD_NONE),
        "interest_rate_step_indicator": _str(np.where(mod != MOD_NONE, "N", "")),
        "payment_deferral_flag": _str(
            np.select([deferral == DEFERRAL_CURRENT, deferral == DEFERRAL_PRIOR], ["C", "P"], "")
        ),
        "estimated_ltv": blank_unless(period >= ELTV_FIRST_MONTH, eltv_text),
        "zero_balance_removal_upb": money(removal, terminal),
        "delinquent_accrued_interest": money(accrued, loss_row),
        "delinquency_due_to_disaster": _str(np.where(g.disaster[loan, col], "Y", "")),
        "borrower_assistance_plan": _str(np.where(g.plan[loan, col] == PLAN_FORBEARANCE, "F", "")),
        "current_period_modification_costs": money(g.period_mod_cost[loan, col], mod != MOD_NONE),
        "current_interest_bearing_upb": fmt_fixed(upb, 2),
        "mi_cancellation_indicator": _str(np.where(mi_pct > 0, "N", "7")),
        "servicer_name": _str(np.array(o.servicer)[loan]),
        "bankruptcy_cramdown_costs": money(
            np.zeros(rows), loss_row & (period >= CRAMDOWN_FIRST_MONTH)
        ),
    }
    return pa.table(
        [columns[name] for name in PERFORMANCE.column_names], names=list(PERFORMANCE.column_names)
    )


def truth_table(block: SimulatedBlock) -> pa.Table:
    t = block.truth
    loan_ids = np.array(block.originations.loan_id)[t.loan_index]
    return pa.table(
        {
            "loan_id": _str(loan_ids),
            "period": pa.array(((t.period // 12) * 100 + t.period % 12 + 1).astype(np.int32)),
            "true_prepay": pa.array(t.prepay),
            "true_credit": pa.array(t.credit),
            "true_active": pa.array(t.active),
            "outcome": pa.array(t.outcome.astype(np.int8)),
        }
    )
