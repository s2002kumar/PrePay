-- One row per loan ID seen in either file, with every data-quality and eligibility finding.
-- Quarantine = a data problem the decision table forbids guessing around (MODELING §2).
-- Exclusion = a valid loan outside the modeled population (e.g. modified before entry).
with originations as (
    select * from {{ ref('stg_originations') }}
),

performance as (
    select * from {{ ref('stg_performance') }}
),

orig_loans as (
    select
        loan_id,
        count(*) as origination_rows,
        bool_or(_violations <> 0) as origination_violation,
        bool_or(
            first_payment_month is null or maturity_month is null or note_rate_pct is null
            or original_upb is null or original_loan_term is null
        ) as missing_required_field,
        bool_or(amortization_type is distinct from 'FRM' or interest_only = 'Y')
            as ineligible_product
    from originations
    group by loan_id
),

perf_loans as (
    select
        loan_id,
        count(*) as performance_rows,
        bool_or(_violations <> 0) as performance_violation,
        bool_or(period_month is null) as missing_period,
        bool_or(modification_flag = 'Y' and zero_balance_code is not null)
            as modification_with_terminal_same_month,
        bool_or(zero_balance_code is not null and zero_balance_effective_month is null)
            as missing_zero_balance_effective_date,
        count(*) filter (where zero_balance_code is not null) as terminal_rows,
        min(period_month) filter (where zero_balance_code is not null) as first_terminal_month,
        bool_or(
            zero_balance_code is not null
            and zero_balance_effective_month is distinct from period_month
        ) as zero_balance_date_mismatch,
        -- arg_min_null: the flag on the first observed row even when it is blank (arg_min would
        -- skip blank flags and return the first non-blank one from a later month).
        arg_min_null(modification_flag, period_month) as first_row_modification_flag,
        min(period_month) as first_observed_month,
        min(period_month) filter (where modification_flag = 'Y') as first_y_month,
        min(period_month) filter (where modification_flag = 'P') as first_p_month
    from performance
    group by loan_id
),

period_counts as (
    select
        loan_id,
        period_month,
        count(*) as rows_in_period,
        count(distinct row_hash) as distinct_rows_in_period
    from performance
    group by loan_id, period_month
),

duplicates as (
    select
        loan_id,
        bool_or(distinct_rows_in_period > 1) as conflicting_duplicate_period,
        bool_or(rows_in_period > 1 and distinct_rows_in_period = 1) as exact_duplicate_period
    from period_counts
    group by loan_id
),

sequenced as (
    select
        loan_id,
        period_month,
        lag(period_month) over (partition by loan_id order by period_month) as previous_month
    from period_counts
),

gaps as (
    select
        loan_id,
        bool_or(period_month - previous_month > 1) as period_gap
    from sequenced
    group by loan_id
),

after_termination as (
    select
        performance.loan_id,
        bool_or(performance.period_month > perf_loans.first_terminal_month)
            as rows_after_termination
    from performance
    inner join perf_loans on performance.loan_id = perf_loans.loan_id
    group by performance.loan_id
),

combined as (
    select
        coalesce(o.loan_id, p.loan_id) as loan_id,
        o.loan_id is null as orphan_performance,
        p.loan_id is null as no_performance,
        coalesce(o.origination_rows, 0) > 1 as duplicate_origination,
        coalesce(o.origination_violation, false)
        or coalesce(p.performance_violation, false) as field_domain_violation,
        coalesce(o.missing_required_field, false)
        or coalesce(p.missing_period, false) as missing_required_field,
        coalesce(d.conflicting_duplicate_period, false) as conflicting_duplicate_period,
        coalesce(d.exact_duplicate_period, false) as exact_duplicate_period,
        coalesce(g.period_gap, false) as period_gap,
        coalesce(a.rows_after_termination, false) as rows_after_termination,
        coalesce(p.modification_with_terminal_same_month, false)
            as modification_with_terminal_same_month,
        coalesce(p.missing_zero_balance_effective_date, false)
            as missing_zero_balance_effective_date,
        coalesce(p.terminal_rows, 0) > 1 as multiple_terminal_rows,
        coalesce(p.zero_balance_date_mismatch, false) as zero_balance_date_mismatch,
        coalesce(p.first_row_modification_flag = 'P', false) as modified_before_entry,
        -- 'P' (prior modification) after entry with no earlier 'Y': the modification month is
        -- unknown, so the loan's censoring time can't be placed.
        coalesce(
            p.first_p_month > p.first_observed_month
            and (p.first_y_month is null or p.first_p_month < p.first_y_month),
            false
        ) as prior_modification_without_y,
        coalesce(o.ineligible_product, false) as ineligible_product
    from orig_loans as o
    full outer join perf_loans as p on o.loan_id = p.loan_id
    left join duplicates as d on coalesce(o.loan_id, p.loan_id) = d.loan_id
    left join gaps as g on coalesce(o.loan_id, p.loan_id) = g.loan_id
    left join after_termination as a on coalesce(o.loan_id, p.loan_id) = a.loan_id
)

select
    *,
    orphan_performance or no_performance or duplicate_origination or field_domain_violation
    or missing_required_field or conflicting_duplicate_period or period_gap
    or rows_after_termination or modification_with_terminal_same_month
    or missing_zero_balance_effective_date or multiple_terminal_rows
    or prior_modification_without_y as is_quarantined,
    modified_before_entry or ineligible_product as is_excluded
from combined
