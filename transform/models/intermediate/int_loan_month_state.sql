-- Observed monthly states of eligible loans: one row per (loan_id, period_month). Exact duplicate
-- rows are collapsed to the first source line (conflicting duplicates were quarantined).
select p.*
from {{ ref('stg_performance') }} as p
inner join {{ ref('int_loans') }} as l on p.loan_id = l.loan_id
qualify row_number() over (partition by p.loan_id, p.period_month order by p._source_row) = 1
