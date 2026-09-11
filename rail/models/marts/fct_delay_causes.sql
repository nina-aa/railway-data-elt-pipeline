-- ============================================================================
-- GRAIN: one row per timetable event per delay cause.
--
-- Kept separate from fct_timetable_events because the grain differs. If these
-- rows were columns on the event fact, an event with N causes would either
-- need N cause columns (sparse, capped) or would fan the event fact out by N
-- and multiply every additive measure. A conformed sub-fact at the event-cause
-- grain is the standard resolution.
--
-- To attribute delay minutes to a cause, join to fct_timetable_events on
-- event_key and divide that event's delay_minutes across its cause rows (see
-- the Stage 4 queries / findings.md for the equal-split convention).
-- ============================================================================

with causes as (

    select * from {{ ref('stg_delay_causes') }}

),

cause_dim as (
    select cause_key, cause_category_code from {{ ref('dim_cause') }}
),

events as (
    select event_key from {{ ref('fct_timetable_events') }}
)

select
    causes.event_key,
    causes.cause_seq,
    coalesce(cause_dim.cause_key, -1)          as cause_key,
    causes.cause_category_code,
    causes.detailed_cause_category_code,
    causes.third_cause_category_code
from causes
join events using (event_key)
left join cause_dim on cause_dim.cause_category_code = causes.cause_category_code
