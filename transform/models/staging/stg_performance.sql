-- Typed monthly performance records, one row per bronze row. row_hash covers every raw field so
-- exact duplicates (same hash) can be told apart from conflicting ones downstream.
with source as (
    select * from {{ source('bronze', 'performance') }}
)

select
    loan_id,
    release,
    vintage,
    {{ yyyymm_to_month('period') }} as period_month,
    try_cast(nullif(current_actual_upb, '') as double) as current_upb,
    {{ sentinel_text('delinquency_status', ['XX']) }} as delinquency_status,
    case
        when regexp_full_match(delinquency_status, '[0-9]{2}')
            then cast(delinquency_status as integer)
    end as delinquency_months,
    delinquency_status = 'RA' as is_reo_acquisition,
    try_cast(nullif(loan_age, '') as integer) as loan_age,
    try_cast(nullif(remaining_months, '') as integer) as remaining_months,
    {{ yyyymm_to_month('defect_settlement_date') }} as defect_settlement_month,
    {{ sentinel_text('modification_flag') }} as modification_flag,
    {{ sentinel_text('zero_balance_code') }} as zero_balance_code,
    {{ yyyymm_to_month('zero_balance_effective_date') }} as zero_balance_effective_month,
    try_cast(nullif(current_interest_rate, '') as double) as current_rate_pct,
    try_cast(nullif(current_non_interest_bearing_upb, '') as double)
        as non_interest_bearing_upb,
    try_cast(nullif(zero_balance_removal_upb, '') as double) as zero_balance_removal_upb,
    try_cast(nullif(actual_loss, '') as double) as actual_loss,
    delinquency_due_to_disaster = 'Y' as disaster_delinquency,
    {{ sentinel_text('borrower_assistance_plan') }} as borrower_assistance_plan,
    {{ sentinel_text('payment_deferral_flag') }} as payment_deferral_flag,
    md5(concat_ws(
        '|',
        {%- for column in sflld_performance_columns() %}
            {{ column }}{{ "," if not loop.last }}
        {%- endfor %}
    )) as row_hash,
    _violations,
    _source_file,
    _source_row
from source
