-- Typed origination records. Documented "not available" sentinels become NULL (never zero);
-- one row per bronze row (duplicate loan IDs are resolved by quarantine, not here).
with source as (
    select * from {{ source('bronze', 'origination') }}
)

select
    loan_id,
    release,
    vintage,
    {{ sentinel_int('credit_score', ['9999']) }} as credit_score,
    {{ yyyymm_to_month('first_payment_date') }} as first_payment_month,
    {{ yyyymm_to_month('maturity_date') }} as maturity_month,
    {{ sentinel_text('first_time_homebuyer', ['9']) }} as first_time_homebuyer,
    {{ sentinel_text('msa') }} as msa,
    {{ sentinel_int('mi_pct', ['999']) }} as mi_pct,
    {{ sentinel_int('number_of_units', ['99']) }} as number_of_units,
    {{ sentinel_text('occupancy_status', ['9']) }} as occupancy_status,
    {{ sentinel_int('original_cltv', ['999']) }} as original_cltv,
    {{ sentinel_int('original_dti', ['999']) }} as original_dti,
    try_cast(nullif(original_upb, '') as double) as original_upb,
    {{ sentinel_int('original_ltv', ['999']) }} as original_ltv,
    try_cast(nullif(original_interest_rate, '') as double) as note_rate_pct,
    {{ sentinel_text('channel', ['9']) }} as channel,
    {{ sentinel_text('prepayment_penalty') }} as prepayment_penalty,
    {{ sentinel_text('amortization_type') }} as amortization_type,
    {{ sentinel_text('property_state') }} as property_state,
    {{ sentinel_text('property_type', ['99']) }} as property_type,
    {{ sentinel_text('postal_code', ['000']) }} as postal_code3,
    {{ sentinel_text('loan_purpose', ['9']) }} as loan_purpose,
    try_cast(nullif(original_loan_term, '') as integer) as original_loan_term,
    {{ sentinel_int('number_of_borrowers', ['99']) }} as number_of_borrowers,
    {{ sentinel_text('seller_name') }} as seller_name,
    {{ sentinel_text('super_conforming') }} as super_conforming,
    {{ sentinel_text('pre_harp_loan_id') }} as pre_harp_loan_id,
    {{ sentinel_text('special_eligibility_program') }} as special_eligibility_program,
    {{ sentinel_text('harp_indicator') }} as harp_indicator,
    {{ sentinel_text('property_valuation_method', ['7']) }} as property_valuation_method,
    {{ sentinel_text('interest_only') }} as interest_only,
    {{ sentinel_int('vantage_score', ['9999']) }} as vantage_score,
    _violations,
    _source_file,
    _source_row
from source
