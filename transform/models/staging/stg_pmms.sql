-- Weekly PMMS observations (percent per year). Missing observations stay NULL here and are
-- skipped by the as-of monthly rate logic.
select
    series,
    observation_date,
    rate_pct,
    _source_file,
    _source_row
from {{ source('bronze_pmms', 'observations') }}
