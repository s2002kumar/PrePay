-- Observed monthly states of eligible loans: one row per (loan_id, period_month). Exact duplicate
-- rows are collapsed to the first source line (conflicting duplicates were quarantined).
-- Only loans flagged with an exact duplicate period go through the window: running it over every
-- row of the full sample (tens of millions of wide rows) forces a large sort for no change.
with eligible as (
    select
        l.loan_id,
        q.exact_duplicate_period
    from {{ ref('int_loans') }} as l
    inner join {{ ref('int_loan_quality') }} as q on l.loan_id = q.loan_id
)

select p.*
from {{ ref('stg_performance') }} as p
inner join eligible as e on p.loan_id = e.loan_id
where not e.exact_duplicate_period

union all

select p.*
from {{ ref('stg_performance') }} as p
inner join eligible as e on p.loan_id = e.loan_id
where e.exact_duplicate_period
qualify row_number() over (partition by p.loan_id, p.period_month order by p._source_row) = 1
