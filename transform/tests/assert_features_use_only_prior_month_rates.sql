-- Point-in-time guard: every rate behind a month-t feature was observed on or before the last
-- day of month t-1. Any returned row is look-ahead leakage.
select
    loan_id,
    target_month,
    rate_observed_t1
from {{ ref('fct_hazard_panel') }}
where rate_observed_t1 > {{ month_end_date('target_month - 1') }}
