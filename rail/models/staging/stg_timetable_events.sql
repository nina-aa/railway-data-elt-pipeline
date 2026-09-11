{#
  One row per train per station per event type (ARRIVAL / DEPARTURE) — the
  central flatten of train -> timeTableRows.

  Nothing is filtered here. Cancelled trains, cancelled rows, pass-by
  (non-stopping) rows and rows with no actual_time are all kept and flagged.
#}

with trains as (

    select * from {{ source('raw', 'trains') }}

),

events as (

    select
        cast(t.departureDate as date)                        as departure_date,
        t.trainNumber                                        as train_number,
        t.operatorShortCode                                  as operator_short_code,
        t.trainType                                          as train_type,
        t.trainCategory                                      as train_category,
        nullif(t.commuterLineID, '')                         as commuter_line_id,
        coalesce(t.cancelled, false)                         as train_cancelled,
        t.timetableType                                      as timetable_type,
        cast(regexp_extract(t.filename, 'date=([0-9-]+)', 1) as date) as source_ingest_date,
        r.stationShortCode                                   as station_short_code,
        r."type"                                             as event_type,
        cast(r.scheduledTime as timestamp)                   as scheduled_time,
        cast(r.actualTime as timestamp)                      as actual_time,
        cast(r.differenceInMinutes as bigint)                as delay_minutes,
        coalesce(r.trainStopping, false)                     as is_stopping,
        coalesce(r.commercialStop, false)                    as is_commercial_stop,
        coalesce(r.cancelled, false)                         as row_cancelled,
        nullif(r.commercialTrack, '')                        as commercial_track,
        coalesce(len(r.causes), 0)                           as cause_count
    from trains t,
         unnest(t.timeTableRows) as u(r)

)

select
    {{ event_key('departure_date', 'train_number', 'station_short_code', 'event_type', 'scheduled_time') }} as event_key,
    departure_date,
    train_number,
    operator_short_code,
    train_type,
    train_category,
    commuter_line_id,
    station_short_code,
    event_type,
    scheduled_time,
    actual_time,
    delay_minutes,
    timetable_type,
    commercial_track,
    cause_count,
    source_ingest_date,
    -- flags (Stage 1 decision: keep everything, flag it)
    (train_cancelled or row_cancelled)                        as is_cancelled,
    is_stopping,
    is_commercial_stop,
    (actual_time is not null)                                 as has_actual_time,
    (
        delay_minutes is null
        or delay_minutes between {{ var('min_plausible_delay_minutes') }}
                             and {{ var('max_plausible_delay_minutes') }}
    )                                                        as is_plausible_delay
from events
