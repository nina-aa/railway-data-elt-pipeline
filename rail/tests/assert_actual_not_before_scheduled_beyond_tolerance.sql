-- Actual time far before scheduled time is not physically plausible and points
-- to a data problem (a stale schedule version, a bad actualTime, clock issues).
--
-- Restricted to commercial stops: at non-stopping pass-by points the scheduled
-- time is a nominal interpolation and trains legitimately pass many minutes
-- early, so those are not anomalies. Tolerance is early_departure_tolerance_
-- minutes (60) — see the var comment and docs/data_profile.md for why 60 and
-- not 5.
--
-- Severity 'warn': this genuinely occurs in the source data (mostly freight
-- with a revised path). It is a data-quality signal, not a pipeline bug. The
-- rows are kept and flagged is_plausible_delay = false.

{{ config(severity = 'warn') }}

select
    event_key,
    train_number,
    station_key,
    event_type,
    scheduled_time,
    actual_time,
    delay_minutes
from {{ ref('fct_timetable_events') }}
where has_actual_time
  and not is_cancelled
  and is_commercial_stop
  and delay_minutes < -1 * {{ var('early_departure_tolerance_minutes') }}
order by delay_minutes
