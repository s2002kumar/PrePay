-- Chronology guards on the gold panel:
--  * no at-risk month after the loan's first event;
--  * at most one terminal outcome (P or C) per loan, and only in its event month;
--  * no at-risk month at or after a modification;
--  * every P/C row matches the loan's event type.
with panel as (
    select
        p.*,
        e.event_type,
        e.event_month,
        e.first_modification_month
    from {{ ref('fct_hazard_panel') }} as p
    inner join {{ ref('int_exit_events') }} as e on p.loan_id = e.loan_id
)

select
    loan_id,
    target_month,
    'after_event' as violation
from panel
where target_month > event_month
union all
select
    loan_id,
    null as target_month,
    'multiple_terminal_outcomes' as violation
from panel
where outcome in ('P', 'C')
group by loan_id
having count(*) > 1
union all
select
    loan_id,
    target_month,
    'terminal_outcome_off_event_month' as violation
from panel
where outcome in ('P', 'C') and target_month <> event_month
union all
select
    loan_id,
    target_month,
    'at_or_after_modification' as violation
from panel
where first_modification_month is not null and target_month >= first_modification_month
union all
select
    loan_id,
    target_month,
    'outcome_event_mismatch' as violation
from panel
where (outcome = 'P' and event_type <> 'prepay') or (outcome = 'C' and event_type <> 'credit')
