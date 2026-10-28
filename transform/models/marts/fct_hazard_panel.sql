-- Gold modeling panel: one row per at-risk loan-month t with its observed outcome (P/C/A) and
-- features computed only from information available at the end of month t-1:
-- origination attributes, the contract schedule, and month-end PMMS rates through t-1.
-- No delinquency, current balance, modification or later-month data is used as a feature.
with loans as (
    select * from {{ ref('int_loans') }}
),

rates as (
    select * from {{ ref('int_monthly_rates') }}
),

burnout as (
    select * from {{ ref('int_burnout_index') }}
)

select
    r.loan_id,
    r.target_month,
    r.outcome,
    case r.outcome when 'A' then 0 when 'P' then 1 when 'C' then 2 end as outcome_class,
    r.exposure_upb,
    r.exit_removal_upb,
    l.vintage,
    l.first_payment_month,

    -- static origination attributes (NULL = documented "not available"; flags keep the signal)
    l.credit_score,
    l.credit_score is null as credit_score_missing,
    l.original_ltv,
    l.original_ltv is null as ltv_missing,
    l.original_cltv,
    l.original_dti,
    l.original_dti is null as dti_missing,
    l.mi_pct,
    ln(l.original_upb) as log_original_upb,
    l.note_rate_pct,
    {{ term_bucket('l.original_loan_term') }} as term_bucket,
    l.loan_purpose,
    l.occupancy_status,
    l.number_of_units,
    l.channel,
    l.first_time_homebuyer,
    l.property_type,
    {{ census_region('l.property_state') }} as census_region,
    -- Freddie coded 2 as ">1 borrowers" through 2018Q1 and as "2 borrowers" after; >1 is
    -- the era-consistent feature.
    l.number_of_borrowers > 1 as multiple_borrowers,

    -- path features as of t-1
    r.target_month % 12 + 1 as month_of_year,
    r.target_month - l.first_payment_month + 1 as loan_age,
    l.maturity_month - r.target_month + 1 as remaining_payments,
    {{ matched_rate('l.original_loan_term', 'rate_t1') }} as market_rate_t1,
    {{ matched_rate('l.original_loan_term', 'rate_t2') }} as market_rate_t2,
    rate_t1.observed_30y as rate_observed_t1,
    (l.note_rate_pct - {{ matched_rate('l.original_loan_term', 'rate_t1') }}) * 100
        as incentive_bps,
    (
        {{ matched_rate('l.original_loan_term', 'rate_t1') }}
        - {{ matched_rate('l.original_loan_term', 'rate_t7') }}
    ) * 100 as rate_change_6m_bps,
    coalesce(burn_t1.cumulative_in_money_months, 0)
    - coalesce(burn_fp.cumulative_in_money_months, 0) as burnout_months,
    (l.note_rate_pct - {{ matched_rate('l.original_loan_term', 'rate_fp') }}) * 100 as sato_bps,

    -- regime flags (reported, not silently dropped)
    rate_t1.pmms_application_based,
    r.target_month in (
        {%- for m in var('accounting_transition_months') %}
            {{ iso_to_month(m) }}{{ "," if not loop.last }}
        {%- endfor %}
    ) as accounting_transition_month
from {{ ref('int_at_risk') }} as r
inner join loans as l on r.loan_id = l.loan_id
left join rates as rate_t1 on rate_t1.month = r.target_month - 1
left join rates as rate_t2 on rate_t2.month = r.target_month - 2
left join rates as rate_t7 on rate_t7.month = r.target_month - 7
left join rates as rate_fp on rate_fp.month = l.first_payment_month - 1
left join burnout as burn_t1
    on
        l.note_rate_pct = burn_t1.note_rate_pct
        and burn_t1.rate_series = case when l.original_loan_term <= 180 then '15y' else '30y' end
        and burn_t1.month = r.target_month - 1
left join burnout as burn_fp
    on
        l.note_rate_pct = burn_fp.note_rate_pct
        and burn_fp.rate_series = case when l.original_loan_term <= 180 then '15y' else '30y' end
        and burn_fp.month = l.first_payment_month - 1
