-- One row per eligible loan: its first event and the data needed for cohort run-off studies
-- (Aalen-Johansen cumulative incidence with explicit censoring).
select
    e.loan_id,
    l.vintage,
    l.first_payment_month,
    l.maturity_month,
    l.original_upb,
    l.note_rate_pct,
    l.original_loan_term,
    e.first_observed_month,
    e.last_observed_month,
    e.event_type,
    e.event_month,
    e.event_type like 'censor_%' as is_censored,
    e.removal_upb
from {{ ref('int_exit_events') }} as e
inner join {{ ref('int_loans') }} as l on e.loan_id = l.loan_id
