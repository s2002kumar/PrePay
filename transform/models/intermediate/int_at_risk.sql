-- At-risk loan-months with their observed month-t outcome.
-- A month t is at risk when the loan was observed active at the end of t-1 (consecutive record,
-- no terminal code, UPB > 0, first payment reached) and t is on or before its first event.
-- Months whose outcome is censored (modification, 15/16/96) or maturity are excluded. A loan
-- whose records simply end (administrative cutoff or unexplained end) was observed active in its
-- last month, so that month is labelled A.
with states as (
    select
        loan_id,
        period_month,
        current_upb,
        zero_balance_code,
        lag(period_month) over by_loan as previous_month,
        lag(current_upb) over by_loan as previous_upb,
        lag(zero_balance_code) over by_loan as previous_zero_balance_code
    from {{ ref('int_loan_month_state') }}
    window by_loan as (partition by loan_id order by period_month)
)

select
    s.loan_id,
    s.period_month as target_month,
    s.previous_upb as exposure_upb,
    case
        when s.period_month = e.event_month and e.event_type = 'prepay' then 'P'
        when s.period_month = e.event_month and e.event_type = 'credit' then 'C'
        else 'A'
    end as outcome,
    case
        when s.period_month = e.event_month and e.event_type in ('prepay', 'credit')
            then e.removal_upb
    end as exit_removal_upb
from states as s
inner join {{ ref('int_exit_events') }} as e on s.loan_id = e.loan_id
where
    s.previous_month = s.period_month - 1
    and s.previous_zero_balance_code is null
    and s.previous_upb > 0
    and s.previous_month >= e.first_payment_month
    and s.period_month <= e.event_month
    and not (
        s.period_month = e.event_month
        and e.event_type not in (
            'prepay', 'credit', 'censor_administrative', 'censor_unexplained_end'
        )
    )
