-- Counts of loans per data-quality finding (aggregate only; no identifiers).
{% set findings = [
    'orphan_performance', 'no_performance', 'duplicate_origination', 'field_domain_violation',
    'missing_required_field', 'conflicting_duplicate_period', 'exact_duplicate_period',
    'period_gap', 'rows_after_termination', 'modification_with_terminal_same_month',
    'missing_zero_balance_effective_date', 'multiple_terminal_rows', 'zero_balance_date_mismatch',
    'prior_modification_without_y', 'modified_before_entry', 'ineligible_product',
    'is_quarantined', 'is_excluded'
] %}
{% for finding in findings %}
    select
        '{{ finding }}' as finding,
        count(*) filter (where {{ finding }}) as loans
    from {{ ref('int_loan_quality') }}
    {% if not loop.last %}union all{% endif %}
{% endfor %}
