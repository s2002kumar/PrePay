-- Balance-weighted monthly exposure and observed exits for the at-risk panel, used for the
-- full_payoff_only_CPR_proxy (FINANCIAL_CONVENTIONS §4). Scheduled principal is computed by the
-- finance engine, not here.
-- Money sums use DECIMAL so the result doesn't depend on parallel summation order.
select
    r.target_month,
    count(*) as loans_at_risk,
    sum(r.exposure_upb::decimal(38, 6))::double as exposure_upb,
    count(*) filter (where r.outcome = 'P') as payoff_count,
    count(*) filter (where r.outcome = 'C') as credit_exit_count,
    sum(r.exit_removal_upb::decimal(38, 6)) filter (where r.outcome = 'P')::double
        as payoff_removal_upb,
    sum(r.exit_removal_upb::decimal(38, 6)) filter (where r.outcome = 'C')::double
        as credit_exit_removal_upb
from {{ ref('int_at_risk') }} as r
group by r.target_month
