-- First event per eligible loan, applying MODELING §2's decision table in chronological order.
--   modification Y before any terminal record   -> censor_modification (at the Y month)
--   01 within maturity_window_months of maturity -> maturity (contract, not a prepayment)
--   01 otherwise                                 -> prepay       (outcome P)
--   02 / 03 / 09                                 -> credit       (outcome C)
--   15 / 16 / 96                                 -> censored (whole-loan sale, RPL, defect)
--   no terminal record, observed at cutoff       -> censor_administrative
--   no terminal record, ends before cutoff       -> censor_unexplained_end (reported)
-- The event is dated by the reporting period of the record that carries it.
with states as (
    select * from {{ ref('int_loan_month_state') }}
),

per_loan as (
    select
        loan_id,
        min(period_month) as first_observed_month,
        max(period_month) as last_observed_month,
        count(*) as observed_months,
        min(period_month) filter (where modification_flag = 'Y') as first_modification_month,
        min(period_month) filter (where zero_balance_code is not null) as terminal_month,
        arg_min(zero_balance_code, period_month) filter (where zero_balance_code is not null)
            as terminal_code,
        arg_min(zero_balance_removal_upb, period_month)
        filter (where zero_balance_code is not null) as removal_upb
    from states
    group by loan_id
)

select
    p.*,
    l.first_payment_month,
    l.maturity_month,
    case
        when
            p.first_modification_month is not null
            and (p.terminal_month is null or p.first_modification_month < p.terminal_month)
            then 'censor_modification'
        when
            p.terminal_code = '01'
            and l.maturity_month - p.terminal_month <= {{ var('maturity_window_months') }}
            then 'maturity'
        when p.terminal_code = '01' then 'prepay'
        when p.terminal_code in ('02', '03', '09') then 'credit'
        when p.terminal_code = '15' then 'censor_whole_loan_sale'
        when p.terminal_code = '16' then 'censor_reperforming_securitization'
        when p.terminal_code = '96' then 'censor_defect'
        when p.last_observed_month = {{ cutoff_month() }} then 'censor_administrative'
        else 'censor_unexplained_end'
    end as event_type,
    case
        when
            p.first_modification_month is not null
            and (p.terminal_month is null or p.first_modification_month < p.terminal_month)
            then p.first_modification_month
        when p.terminal_month is not null then p.terminal_month
        else p.last_observed_month
    end as event_month
from per_loan as p
inner join {{ ref('int_loans') }} as l on p.loan_id = l.loan_id
