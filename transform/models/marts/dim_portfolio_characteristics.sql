-- Eligible-loan attributes for cohort selection and portfolio summaries.
select
    loan_id,
    vintage,
    first_payment_month,
    maturity_month,
    original_upb,
    note_rate_pct,
    floor(note_rate_pct * 4) / 4 as note_rate_bucket_pct,
    original_loan_term,
    {{ term_bucket('original_loan_term') }} as term_bucket,
    credit_score,
    original_ltv,
    original_dti,
    loan_purpose,
    occupancy_status,
    {{ census_region('property_state') }} as census_region
from {{ ref('int_loans') }}
