-- ============================================================================
-- GRAIN: one row per train per station per event type (ARRIVAL or DEPARTURE).
-- One booked stop produces two rows (an arrival and a departure); an origin or
-- terminus produces one; a non-stopping pass-by also produces one (flagged
-- is_stopping = false).
--
-- Nothing is filtered. Cancelled trains, cancelled rows, pass-by rows and rows
-- with no actual_time are all present and flagged.
-- ============================================================================

with events as (

    select * from {{ ref('stg_timetable_events') }}

),

station as (
    select station_key, station_short_code from {{ ref('dim_station') }}
),

train_type as (
    select train_type_key, train_type, train_category from {{ ref('dim_train_type') }}
),

date_dim as (
    select date_key, date from {{ ref('dim_date') }}
)

select
    e.event_key,

    -- foreign keys
    coalesce(station.station_key, -1)               as station_key,
    date_dim.date_key,
    train_type.train_type_key,

    -- degenerate dimensions
    e.train_number,
    e.event_type,
    e.station_short_code,
    e.operator_short_code,
    e.commuter_line_id,

    -- timestamps
    e.scheduled_time,
    e.actual_time,

    -- measures
    e.delay_minutes,
    e.cause_count,

    -- flags
    e.is_cancelled,
    e.is_stopping,
    e.is_commercial_stop,
    e.has_actual_time,
    e.is_plausible_delay,

    e.source_ingest_date

from events e
left join station    on station.station_short_code = e.station_short_code
left join train_type on train_type.train_type = e.train_type
                    and train_type.train_category is not distinct from e.train_category
left join date_dim   on date_dim.date = e.departure_date
