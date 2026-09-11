-- The most valuable test in the project. fct_timetable_events must have exactly
-- the same number of rows as stg_timetable_events: no silent filtering, and no
-- fan-out from a mis-grained join (e.g. accidentally joining delay causes).
-- Fails (returns a row) on any discrepancy.

with staging as (
    select count(*) as n from {{ ref('stg_timetable_events') }}
),

fact as (
    select count(*) as n from {{ ref('fct_timetable_events') }}
)

select
    staging.n as staging_rows,
    fact.n    as fact_rows,
    fact.n - staging.n as difference
from staging, fact
where staging.n <> fact.n
