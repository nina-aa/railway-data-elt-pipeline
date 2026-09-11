-- ============================================================================
-- GRAIN: one row per station per calendar date (train departure_date).
--
-- Population: ARRIVAL events at commercial stops. The on-time rate is computed
-- over arrivals that actually happened (has_actual_time) with a plausible delay;
-- cancellations are excluded from that rate and reported separately as
-- cancelled_arrivals so the denominator is transparent.
--
-- On-time threshold: arrival delay < on_time_threshold_minutes (5), the Finnish
-- long-distance convention, applied uniformly. Justified in the README.
-- ============================================================================

with arrivals as (

    select
        station_key,
        date_key,
        delay_minutes,
        is_cancelled,
        (has_actual_time and is_plausible_delay and not is_cancelled) as counts_for_rate
    from {{ ref('fct_timetable_events') }}
    where event_type = 'ARRIVAL'
      and is_commercial_stop

)

select
    station_key,
    date_key,
    count(*)                                                          as scheduled_arrivals,
    count(*) filter (where is_cancelled)                              as cancelled_arrivals,
    count(*) filter (where counts_for_rate)                           as measured_arrivals,
    count(*) filter (where counts_for_rate
                       and delay_minutes < {{ var('on_time_threshold_minutes') }}) as on_time_events,
    round(
        count(*) filter (where counts_for_rate
                           and delay_minutes < {{ var('on_time_threshold_minutes') }})
        / nullif(count(*) filter (where counts_for_rate), 0)
    , 4)                                                              as on_time_rate,
    round(avg(delay_minutes) filter (where counts_for_rate), 2)       as avg_delay_minutes,
    median(delay_minutes) filter (where counts_for_rate)              as median_delay_minutes,
    max(delay_minutes) filter (where counts_for_rate)                 as worst_delay_minutes
from arrivals
group by 1, 2
