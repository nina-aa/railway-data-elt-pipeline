-- delay_minutes should sit within the plausible band
-- [min_plausible_delay_minutes, max_plausible_delay_minutes] = [-60, 1440].
-- Outside it, the value is treated as bad data and is_plausible_delay is false.
--
-- Severity 'warn': real source rows breach the lower bound (down to -286 min),
-- almost all freight with a revised schedule version. The rows are kept,
-- flagged, and excluded from delay aggregates via is_plausible_delay. This test
-- surfaces the count on every run. See docs/data_profile.md.

{{ config(severity = 'warn') }}

select
    event_key,
    train_number,
    station_key,
    event_type,
    delay_minutes
from {{ ref('fct_timetable_events') }}
where delay_minutes is not null
  and (
        delay_minutes < {{ var('min_plausible_delay_minutes') }}
     or delay_minutes > {{ var('max_plausible_delay_minutes') }}
  )
order by delay_minutes
