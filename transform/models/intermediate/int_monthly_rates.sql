-- Month-end as-of mortgage rates: for each calendar month, the last non-missing weekly PMMS
-- observation dated on or before the month's last day (percent per year). A feature for month t
-- uses month t-1 from this table, i.e. only rates published by the end of t-1.
with observations as (
    select
        series,
        observation_date,
        rate_pct
    from {{ ref('stg_pmms') }}
    where rate_pct is not null
),

observations_30y as (
    select * from observations
    where series = 'MORTGAGE30US'
),

observations_15y as (
    select * from observations
    where series = 'MORTGAGE15US'
),

bounds as (
    select
        {{ date_to_month('min(observation_date)') }} as first_month,
        {{ date_to_month('max(observation_date)') }} as last_month
    from observations
),

months as (
    select
        spine.month,
        {{ month_end_date('spine.month') }} as month_end
    from bounds, unnest(range(bounds.first_month, bounds.last_month + 1)) as spine (month)
),

rate_30y as (
    select
        months.month,
        obs.rate_pct as rate_30y,
        obs.observation_date as observed_30y
    from months
    asof left join observations_30y as obs
        on months.month_end >= obs.observation_date
),

rate_15y as (
    select
        months.month,
        obs.rate_pct as rate_15y,
        obs.observation_date as observed_15y
    from months
    asof left join observations_15y as obs
        on months.month_end >= obs.observation_date
)

select
    months.month,
    months.month_end,
    rate_30y.rate_30y,
    rate_30y.observed_30y,
    rate_15y.rate_15y,
    rate_15y.observed_15y,
    months.month_end - rate_30y.observed_30y as staleness_days_30y,
    -- Freddie Mac moved PMMS to application-based estimates on 2022-11-17 (FRED note).
    coalesce(rate_30y.observed_30y >= date '2022-11-17', false) as pmms_application_based
from months
left join rate_30y on months.month = rate_30y.month
left join rate_15y on months.month = rate_15y.month
