-- Stage-to-stage reconciliation: every bronze performance row is accounted for exactly once as
-- either (a) belonging to a quarantined/excluded/orphan loan, (b) a collapsed exact duplicate, or
-- (c) a row of int_loan_month_state. Returns a row only when the books do not balance.
with bronze as (
    select count(*) as n from {{ ref('stg_performance') }}
),

blocked as (
    select count(*) as n
    from {{ ref('stg_performance') }} as p
    left join {{ ref('int_loan_quality') }} as q on p.loan_id = q.loan_id
    where q.is_quarantined or q.is_excluded
),

collapsed as (
    select coalesce(sum(n - 1), 0) as n
    from (
        select
            p.loan_id,
            p.period_month,
            count(*) as n
        from {{ ref('stg_performance') }} as p
        inner join {{ ref('int_loans') }} as l on p.loan_id = l.loan_id
        group by p.loan_id, p.period_month
    )
),

kept as (
    select count(*) as n from {{ ref('int_loan_month_state') }}
)

select
    bronze.n as bronze_rows,
    blocked.n as blocked_rows,
    collapsed.n as collapsed_rows,
    kept.n as kept_rows
from bronze, blocked, collapsed, kept
where bronze.n <> blocked.n + collapsed.n + kept.n
