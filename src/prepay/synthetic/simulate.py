"""Seeded month-by-month simulation of one block of synthetic loans.

The simulation fills a dense ``(loans, months)`` grid of observed performance states. Rendering
those states into SFLLD-formatted text happens in :mod:`prepay.synthetic.render`. All draws come
from a generator seeded by ``(seed, vintage, block)``, so a block is reproducible on its own.

Synthetic simplifications (documented, deliberate): curtailments re-amortize over the remaining
term; forbearance and transient delinquency are observable states that do not alter the balance
path; credit dispositions freeze the balance over the preceding delinquency run.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prepay import periods
from prepay.arrays import BoolArray, FloatArray, IntArray
from prepay.finance.amortization import contractual_month
from prepay.synthetic import truth

# Outcome codes in the ground-truth file (at-risk months only).
OUT_ACTIVE, OUT_PREPAY, OUT_CREDIT, OUT_MATURITY = 0, 1, 2, 3
OUT_CENSOR_MODIFICATION, OUT_CENSOR_SALE, OUT_CENSOR_DEFECT = 4, 5, 6

# Loan status during simulation.
_PENDING, _AT_RISK, _MODIFIED, _GONE = 0, 1, 2, 9

# Grid code values.
MOD_NONE, MOD_CURRENT, MOD_PRIOR = 0, 1, 2
DQ_REO = -1
PLAN_NONE, PLAN_FORBEARANCE, PLAN_REPAYMENT, PLAN_TRIAL = 0, 1, 2, 3
DEFERRAL_NONE, DEFERRAL_CURRENT, DEFERRAL_PRIOR = 0, 1, 2

DISASTER_MONTHS = frozenset({periods.month(2017, 9), periods.month(2017, 10)})
DISASTER_STATES = ("TX", "FL", "LA")
STATES = (
    "CA",
    "TX",
    "FL",
    "NY",
    "IL",
    "PA",
    "OH",
    "GA",
    "NC",
    "MI",
    "NJ",
    "VA",
    "WA",
    "AZ",
    "MA",
    "TN",
    "IN",
    "MO",
    "MD",
    "WI",
    "CO",
    "MN",
    "SC",
    "AL",
    "LA",
    "OR",
    "UT",
    "NV",
)
SELLERS = (
    "Northwind Home Loans",
    "Bluefield Lending",
    "Harborline Mortgage",
    "Cedar Ridge Bank",
    "Summit Plains Credit Union",
    "OTHER",
)
SERVICERS = ("Northwind Servicing", "Harborline Mortgage", "Keystone Loan Services", "OTHER")


@dataclass(frozen=True, slots=True)
class Originations:
    """Per-loan origination attributes; missing values are NaN (rendered as sentinels)."""

    loan_id: tuple[str, ...]
    origination_month: IntArray
    first_payment: IntArray
    term: IntArray
    maturity: IntArray
    note_rate: FloatArray  # percent per year
    original_upb: FloatArray
    fico: FloatArray
    ltv: FloatArray
    cltv: FloatArray
    dti: FloatArray
    mi_pct: FloatArray
    units: IntArray
    occupancy: tuple[str, ...]
    channel: tuple[str, ...]
    purpose: tuple[str, ...]
    state: tuple[str, ...]
    property_type: tuple[str, ...]
    postal: tuple[str, ...]
    borrowers: IntArray
    first_time_buyer: tuple[str, ...]
    seller: tuple[str, ...]
    servicer: tuple[str, ...]
    valuation_method: tuple[str, ...]
    special_program: tuple[str, ...]
    super_conforming: tuple[str, ...]
    vantage: FloatArray
    observation_start: IntArray
    modified_before_entry: BoolArray

    @property
    def count(self) -> int:
        return len(self.loan_id)


@dataclass(frozen=True, slots=True)
class Grid:
    """Observed monthly states; month column ``j`` is calendar month ``first_month + j``."""

    first_month: int
    valid: BoolArray
    upb: FloatArray
    delinquency: IntArray
    modification: IntArray
    zero_balance_code: IntArray  # 0 = none
    removal_upb: FloatArray
    note_rate: FloatArray
    age: IntArray
    remaining: IntArray
    disaster: BoolArray
    plan: IntArray
    deferral: IntArray
    cumulative_mod_cost: FloatArray
    period_mod_cost: FloatArray
    months_delinquent_at_exit: IntArray  # per loan, credit exits only


@dataclass(frozen=True, slots=True)
class Truth:
    """Ground truth for every at-risk loan-month."""

    loan_index: IntArray
    period: IntArray
    prepay: FloatArray
    credit: FloatArray
    active: FloatArray
    outcome: IntArray


@dataclass(frozen=True, slots=True)
class SimulatedBlock:
    vintage: int
    block: int
    originations: Originations
    grid: Grid
    truth: Truth


def block_rng(seed: int, vintage: int, block: int) -> np.random.Generator:
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence([seed, vintage, block])))


def loan_identifiers(
    vintage: int, origination_month: IntArray, global_index: IntArray
) -> tuple[str, ...]:
    """``F`` + YY + ``Q`` + quarter + 7 digits, unique within a vintage via an affine bijection."""
    digits = (7_654_321 * (global_index + 104_729 * vintage) + 1_234_567) % 10_000_000
    quarters = (origination_month % 12) // 3 + 1
    return tuple(
        f"F{vintage % 100:02d}Q{q}{d:07d}"
        for q, d in zip(quarters.tolist(), digits.tolist(), strict=True)
    )


class RateLookup:
    """Month-end as-of synthetic market rates (percent), indexed by calendar month."""

    def __init__(self, first_month: int, rate_30y: FloatArray, rate_15y: FloatArray) -> None:
        self.first_month = first_month
        self.rate_30y = rate_30y
        self.rate_15y = rate_15y

    def asof_end_of(self, month: int | IntArray, term: IntArray) -> FloatArray:
        """Rate known at the end of ``month`` for each loan's matched term."""
        index = np.asarray(month) - self.first_month
        if np.any(index < 0) or np.any(index >= self.rate_30y.size):
            raise ValueError("rate lookup outside the generated rate history")
        return np.asarray(
            np.where(term <= 180, self.rate_15y[index], self.rate_30y[index]), dtype=np.float64
        )


def originate(
    rng: np.random.Generator,
    vintage: int,
    count: int,
    first_index: int,
    cutoff: int,
    rates: RateLookup,
) -> Originations:
    jan = periods.month(vintage, 1)
    last_origination = min(jan + 11, cutoff - 2)
    orig = rng.integers(jan, last_origination + 1, count)
    first_payment = orig + np.where(rng.random(count) < 0.85, 2, 1)
    term = rng.choice(np.array([360, 180, 240]), size=count, p=[0.8, 0.15, 0.05])
    market = rates.asof_end_of(orig - 1, term)
    note = np.clip(np.round((market + rng.normal(0.2, 0.3, count)) * 8) / 8, 1.5, 13.0)

    def with_missing(values: FloatArray, share: float) -> FloatArray:
        return np.where(rng.random(count) < share, np.nan, values)

    fico = with_missing(np.clip(np.round(rng.normal(742, 48, count)), 300, 850), 0.01)
    ltv_raw = np.clip(np.round(rng.normal(76, 14, count)), 15, 97)
    ltv = with_missing(ltv_raw, 0.003)
    cltv_raw = ltv_raw + (rng.random(count) < 0.12) * rng.integers(1, 16, count)
    cltv = np.where(np.isnan(ltv) | (rng.random(count) < 0.005), np.nan, cltv_raw)
    dti = with_missing(np.clip(np.round(rng.normal(36, 9, count)), 3, 50), 0.012)
    mi = np.where(ltv_raw > 80, rng.choice(np.array([6, 12, 25, 30, 35]), count), 0).astype(float)
    mi = with_missing(mi, 0.002)
    upb = np.clip(np.round(rng.lognormal(np.log(240_000), 0.5, count) / 1000) * 1000, 25_000, 1.5e6)
    purpose = rng.choice(np.array(["P", "C", "N"]), count, p=[0.5, 0.25, 0.25])
    first_time = np.where(
        purpose == "P", rng.choice(np.array(["Y", "N"]), count, p=[0.35, 0.65]), "N"
    )
    seasoned = rng.random(count) < 0.10
    observation_start = np.minimum(
        first_payment + np.where(seasoned, rng.integers(1, 7, count), 0), cutoff
    )
    year_of_orig = orig // 12
    return Originations(
        loan_id=loan_identifiers(vintage, orig, first_index + np.arange(count)),
        origination_month=orig,
        first_payment=first_payment,
        term=term,
        maturity=first_payment + term - 1,
        note_rate=note,
        original_upb=upb,
        fico=fico,
        ltv=ltv,
        cltv=cltv,
        dti=dti,
        mi_pct=mi,
        units=rng.choice(np.array([1, 2, 3, 4]), count, p=[0.96, 0.025, 0.01, 0.005]),
        occupancy=tuple(rng.choice(np.array(["P", "I", "S"]), count, p=[0.89, 0.07, 0.04])),
        channel=tuple(rng.choice(np.array(["R", "B", "C", "T"]), count, p=[0.45, 0.1, 0.3, 0.15])),
        purpose=tuple(purpose),
        state=tuple(rng.choice(np.array(STATES), count)),
        property_type=tuple(
            rng.choice(
                np.array(["SF", "PU", "CO", "MH", "CP"]), count, p=[0.65, 0.22, 0.1, 0.02, 0.01]
            )
        ),
        postal=tuple(f"{z:03d}" for z in rng.integers(100, 1000, count).tolist()),
        borrowers=rng.choice(np.array([1, 2]), count, p=[0.45, 0.55]),
        first_time_buyer=tuple(first_time),
        seller=tuple(rng.choice(np.array(SELLERS), count)),
        servicer=tuple(rng.choice(np.array(SERVICERS), count)),
        valuation_method=tuple(
            np.where(
                year_of_orig >= 2017,
                rng.choice(np.array(["1", "2", "3"]), count, p=[0.3, 0.65, 0.05]),
                "7",
            )
        ),
        special_program=tuple(
            np.where((orig >= periods.month(2015, 3)) & (rng.random(count) < 0.04), "H", "")
        ),
        super_conforming=tuple(np.where((upb > 700_000) & (year_of_orig >= 2009), "Y", "N")),
        vantage=np.where(
            year_of_orig >= 2025, np.clip(np.round(rng.normal(735, 50, count)), 300, 850), np.nan
        ),
        observation_start=observation_start,
        modified_before_entry=rng.random(count) < 0.0025,
    )


def simulate(
    rng: np.random.Generator,
    origination: Originations,
    cutoff: int,
    rates: RateLookup,
) -> tuple[Grid, Truth]:
    n = origination.count
    first_month = int(origination.origination_month.min())
    width = cutoff - first_month + 1
    shape = (n, width)
    valid = np.zeros(shape, dtype=bool)
    upb_grid = np.zeros(shape)
    dq_grid = np.zeros(shape, dtype=np.int64)
    mod_grid = np.zeros(shape, dtype=np.int64)
    zb_grid = np.zeros(shape, dtype=np.int64)
    removal_grid = np.zeros(shape)
    rate_grid = np.zeros(shape)
    age_grid = np.zeros(shape, dtype=np.int64)
    remaining_grid = np.zeros(shape, dtype=np.int64)
    disaster_grid = np.zeros(shape, dtype=bool)
    plan_grid = np.zeros(shape, dtype=np.int64)
    deferral_grid = np.zeros(shape, dtype=np.int64)
    cum_cost_grid = np.zeros(shape)
    period_cost_grid = np.zeros(shape)
    months_dq_at_exit = np.zeros(n, dtype=np.int64)

    status = np.full(n, _PENDING)
    balance = origination.original_upb.copy()
    rate = origination.note_rate.copy()
    maturity = origination.maturity.copy()
    age_anchor = origination.first_payment.copy()  # first payment date used for loan age
    burnout = np.zeros(n, dtype=np.int64)
    cumulative_cost = np.zeros(n)
    dq_left = np.zeros(n, dtype=np.int64)
    dq_value = np.zeros(n, dtype=np.int64)
    plan_left = np.zeros(n, dtype=np.int64)
    deferral = np.zeros(n, dtype=np.int64)
    in_disaster_state = np.isin(np.array(origination.state), DISASTER_STATES)

    truth_rows: list[tuple[IntArray, int, FloatArray, FloatArray, FloatArray, IntArray]] = []

    for j in range(width):
        m = first_month + j
        started = m >= origination.first_payment
        newly_observed = (status == _PENDING) & (m == origination.observation_start)
        status[newly_observed & ~origination.modified_before_entry] = _AT_RISK
        prior_mod = newly_observed & origination.modified_before_entry
        status[prior_mod] = _MODIFIED
        rate[prior_mod] = np.maximum(origination.note_rate[prior_mod] - 1.5, 2.0)

        at_risk = status == _AT_RISK
        modified = status == _MODIFIED
        observed = at_risk | modified

        # Incentive known at the end of m-1 (feature of month m), using the contract note rate.
        incentive = (origination.note_rate - rates.asof_end_of(m - 1, origination.term)) * 100.0
        outcome = np.full(n, -1, dtype=np.int64)

        idx = np.nonzero(at_risk)[0]
        if idx.size:
            state = truth.LoanState(
                incentive_bps=incentive[idx],
                age_months=(m - origination.first_payment[idx] + 1).astype(np.int64),
                burnout_months=burnout[idx],
                calendar_month=m,
                fico=origination.fico[idx],
                ltv=origination.ltv[idx],
                dti=origination.dti[idx],
                original_upb=origination.original_upb[idx],
            )
            p, c, a = truth.outcome_probabilities(state)
            mod_p, sale_p, defect_p = truth.censoring_probabilities(state)
            censor = truth.draw_categories(rng, mod_p, sale_p, defect_p)
            draw = truth.draw_categories(rng, p, c)
            final = m == maturity[idx]
            out = np.select(
                [censor == 0, censor == 1, censor == 2, draw == 1, final, draw == 0],
                [
                    OUT_CENSOR_MODIFICATION,
                    OUT_CENSOR_SALE,
                    OUT_CENSOR_DEFECT,
                    OUT_CREDIT,
                    OUT_MATURITY,
                    OUT_PREPAY,
                ],
                default=OUT_ACTIVE,
            )
            outcome[idx] = out
            truth_rows.append((idx, m, p, c, a, out))

        # Post-modification loans: separate, simpler exit process (never labelled).
        idx_mod = np.nonzero(modified)[0]
        if idx_mod.size:
            post = truth.draw_categories(
                rng,
                np.full(idx_mod.size, 0.012),
                np.full(idx_mod.size, 0.004),
                np.full(idx_mod.size, 0.002),
            )
            mod_out = np.select([post == 0, post == 1, post == 2], [16, 1, 9], default=0)
            mod_out = np.where(m == maturity[idx_mod], 1, mod_out)
            outcome[idx_mod] = -100 - mod_out  # encoded zero-balance code for modified loans

        # Contractual amortization for every loan past its first payment (observed or not).
        remaining_payments = maturity - m + 1
        amortizing = started & (status != _GONE)
        _, scheduled = contractual_month(
            np.where(amortizing, balance, 0.0),
            rate / 100.0,
            np.where(amortizing, remaining_payments, 1),
        )
        after_scheduled = balance - scheduled

        # --- observable states for continuing observed loans
        continuing = observed & np.isin(outcome, [OUT_ACTIVE, -100])
        start_dq = continuing & (dq_left == 0) & (plan_left == 0) & (rng.random(n) < 0.004)
        dq_left[start_dq] = rng.integers(1, 4, int(start_dq.sum()))
        dq_value[start_dq] = 0
        in_window = truth.FORBEARANCE_WINDOW[0] <= m <= truth.FORBEARANCE_WINDOW[1]
        start_plan = (
            continuing & (plan_left == 0) & (dq_left == 0) & in_window & (rng.random(n) < 0.012)
        )
        plan_left[start_plan] = rng.integers(3, 13, int(start_plan.sum()))
        dq_value[start_plan] = 0
        on_plan = continuing & (plan_left > 0)
        transient = continuing & (dq_left > 0)
        dq_value[on_plan | transient] += 1
        ending_plan = on_plan & (plan_left == 1)
        deferral = np.where(deferral == DEFERRAL_CURRENT, DEFERRAL_PRIOR, deferral)
        deferral[ending_plan] = DEFERRAL_CURRENT

        # --- record rows for observed loans
        cols = np.nonzero(observed)[0]
        valid[cols, j] = True
        age_grid[cols, j] = m - age_anchor[cols] + 1
        remaining_grid[cols, j] = maturity[cols] - m
        rate_grid[cols, j] = rate[cols]
        mod_grid[cols, j] = np.where(modified[cols], MOD_PRIOR, MOD_NONE)
        dq_grid[cols, j] = np.where(
            on_plan[cols] | transient[cols], np.minimum(dq_value[cols], 99), 0
        )
        plan_grid[cols, j] = np.where(on_plan[cols], PLAN_FORBEARANCE, PLAN_NONE)
        deferral_grid[cols, j] = deferral[cols]
        if m >= periods.month(2014, 1) and m in DISASTER_MONTHS:
            hit = cols[in_disaster_state[cols] & (rng.random(cols.size) < 0.3)]
            disaster_grid[hit, j] = True

        # Terminal events on observed loans.
        prepaid = outcome == OUT_PREPAY
        matured = (outcome == OUT_MATURITY) | (outcome == -101)
        sale = outcome == OUT_CENSOR_SALE
        defect = outcome == OUT_CENSOR_DEFECT
        credit = outcome == OUT_CREDIT
        rpl = outcome == -116
        post_mod_credit = outcome == -109

        # Payoffs are removed after this month's scheduled payment (schedule-before-exit); the
        # final contractual payment and non-payoff exits remove the whole beginning balance.
        for mask, code, removed in (
            (prepaid, 1, after_scheduled),
            (matured, 1, balance),
            (sale, 15, balance),
            (defect, 96, balance),
            (rpl, 16, balance),
        ):
            rows = np.nonzero(mask)[0]
            zb_grid[rows, j] = code
            removal_grid[rows, j] = removed[rows]
            upb_grid[rows, j] = 0.0
            status[rows] = _GONE

        credit_rows = np.nonzero(credit | post_mod_credit)[0]
        if credit_rows.size:
            codes = np.where(
                post_mod_credit[credit_rows],
                9,
                rng.choice(np.array([2, 3, 9]), credit_rows.size, p=[0.25, 0.35, 0.4]),
            )
            run = rng.integers(4, 13, credit_rows.size)
            for row, code, k in zip(
                credit_rows.tolist(), codes.tolist(), run.tolist(), strict=True
            ):
                lo = max(j - k, 0)
                frozen_at = lo - 1
                observed_cols = np.nonzero(valid[row, lo:j])[0] + lo
                frozen = (
                    upb_grid[row, frozen_at]
                    if frozen_at >= 0 and valid[row, frozen_at]
                    else balance[row]
                )
                if observed_cols.size:
                    upb_grid[row, observed_cols] = frozen
                    dq_grid[row, observed_cols] = np.minimum(observed_cols - lo + 1, 99)
                    if code == 9:
                        dq_grid[row, observed_cols[-min(3, observed_cols.size) :]] = DQ_REO
                zb_grid[row, j] = code
                removal_grid[row, j] = frozen
                upb_grid[row, j] = 0.0
                dq_grid[row, j] = DQ_REO if code == 9 else min(observed_cols.size + 1, 99)
                months_dq_at_exit[row] = observed_cols.size + 1
                status[row] = _GONE

        # Modification (current period): row flagged Y, terms change from next month.
        mods = np.nonzero(outcome == OUT_CENSOR_MODIFICATION)[0]
        if mods.size:
            mod_grid[mods, j] = MOD_CURRENT
            status[mods] = _MODIFIED
            rate[mods] = np.maximum(np.round((origination.note_rate[mods] - 1.75) * 8) / 8, 2.0)
            maturity[mods] = m + 480
            age_anchor[mods] = m + 1
            age_grid[mods, j] = 0
            remaining_grid[mods, j] = maturity[mods] - m

        # Continuing balances: curtailments on observed performing loans, then record UPB.
        still = (status == _AT_RISK) | (status == _MODIFIED)
        curtail = still & observed & (dq_grid[:, j] == 0) & (rng.random(n) < 0.012)
        extra = np.minimum(rng.uniform(200, 8000, n), 0.25 * after_scheduled) * curtail
        balance = np.where(amortizing & (status != _GONE), after_scheduled - extra, balance)
        balance = np.where(status == _GONE, 0.0, balance)
        rows_still = np.nonzero(still & observed)[0]
        upb_grid[rows_still, j] = balance[rows_still]

        # Modification cost accrues on modified loans (rate concession on interest-bearing UPB).
        modified_now = status == _MODIFIED
        cost = np.where(modified_now, balance * (origination.note_rate - rate) / 1200.0, 0.0)
        cumulative_cost += cost
        period_cost_grid[modified_now & valid[:, j], j] = cost[modified_now & valid[:, j]]
        cum_cost_grid[modified_now & valid[:, j], j] = cumulative_cost[modified_now & valid[:, j]]

        # Burnout counts months through m with incentive > 50 bps (used from month m+1 on).
        burnout += (started & (incentive > 50.0)).astype(np.int64)
        dq_left = np.maximum(dq_left - 1, 0)
        plan_left = np.maximum(plan_left - 1, 0)
        dq_value[(dq_left == 0) & (plan_left == 0)] = 0

    grid = Grid(
        first_month=first_month,
        valid=valid,
        upb=upb_grid,
        delinquency=dq_grid,
        modification=mod_grid,
        zero_balance_code=zb_grid,
        removal_upb=removal_grid,
        note_rate=rate_grid,
        age=age_grid,
        remaining=remaining_grid,
        disaster=disaster_grid,
        plan=plan_grid,
        deferral=deferral_grid,
        cumulative_mod_cost=cum_cost_grid,
        period_mod_cost=period_cost_grid,
        months_delinquent_at_exit=months_dq_at_exit,
    )
    return grid, _stack_truth(truth_rows)


def _stack_truth(
    rows: list[tuple[IntArray, int, FloatArray, FloatArray, FloatArray, IntArray]],
) -> Truth:
    if not rows:
        empty_i = np.zeros(0, dtype=np.int64)
        empty_f = np.zeros(0)
        return Truth(empty_i, empty_i, empty_f, empty_f, empty_f, empty_i)
    return Truth(
        loan_index=np.concatenate([r[0] for r in rows]),
        period=np.concatenate([np.full(r[0].size, r[1], dtype=np.int64) for r in rows]),
        prepay=np.concatenate([r[2] for r in rows]),
        credit=np.concatenate([r[3] for r in rows]),
        active=np.concatenate([r[4] for r in rows]),
        outcome=np.concatenate([r[5] for r in rows]),
    )
