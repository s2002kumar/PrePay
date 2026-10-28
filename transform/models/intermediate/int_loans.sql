-- Eligible loans: present in both files, not quarantined, not excluded. One row per loan.
select o.*
from {{ ref('stg_originations') }} as o
inner join {{ ref('int_loan_quality') }} as q on o.loan_id = q.loan_id
where not q.is_quarantined and not q.is_excluded
