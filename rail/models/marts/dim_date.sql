-- Grain: one row per calendar date actually present in the loaded data
-- (train departure_date). The range is derived from stg_timetable_events, NOT
-- from a hardcoded var: a hardcoded range silently produces NULL date_key on
-- every fact row for any date ingested after the range was last bumped (this
-- broke on the first catch-up run past the initial 14-day window -- see
-- docs/data_profile.md). Deriving it from the data means dim_date grows on its
-- own every time daily_update.sh lands a new day and runs `dbt build`.

with bounds as (

    select
        min(departure_date) as min_date,
        max(departure_date) as max_date
    from {{ ref('stg_timetable_events') }}

),

spine as (

    select cast(unnest(generate_series(
        (select min_date from bounds),
        (select max_date from bounds),
        interval 1 day
    )) as date) as date

)

select
    cast(strftime(date, '%Y%m%d') as integer) as date_key,
    date,
    dayofweek(date)                           as day_of_week,   -- 0 = Sunday
    dayname(date)                             as day_name,
    dayofweek(date) in (0, 6)                 as is_weekend,
    month(date)                              as month,
    year(date)                               as year,
    week(date)                              as week_of_year
from spine
