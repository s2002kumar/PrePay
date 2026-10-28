-- Cumulative count of "in the money" months for every (note rate, rate series) in the book.
-- Month j is in the money when (note rate - matched-term rate at the end of j-1) * 100 exceeds
-- burnout_threshold_bps. A loan's burnout at month t is then
--   cumulative_in_money(t - 1) - cumulative_in_money(first_payment_month - 1),
-- i.e. the in-the-money months j in [first_payment_month, t-1], using only rates known by t-1.
-- Months whose prior-month rate is unknown do not count.
with notes as (
    select distinct
        note_rate_pct,
        case when original_loan_term <= 180 then '15y' else '30y' end as rate_series
    from {{ ref('int_loans') }}
),

rates as (
    select
        month,
        lag(rate_30y) over (order by month) as prior_rate_30y,
        lag(rate_15y) over (order by month) as prior_rate_15y
    from {{ ref('int_monthly_rates') }}
)

select
    notes.note_rate_pct,
    notes.rate_series,
    rates.month,
    sum(
        case
            when (
                notes.note_rate_pct
                - case
                    when notes.rate_series = '15y' then rates.prior_rate_15y
                    else rates.prior_rate_30y
                end
            ) * 100 > {{ var('burnout_threshold_bps') }} then 1
            else 0
        end
    ) over (
        partition by notes.note_rate_pct, notes.rate_series
        order by rates.month
        rows between unbounded preceding and current row
    ) as cumulative_in_money_months
from notes
cross join rates
