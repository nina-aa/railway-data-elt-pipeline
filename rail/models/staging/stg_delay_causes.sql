{#
  One row per timetable event per delay cause — the second flatten,
  timeTableRows -> causes.

  This is a DIFFERENT grain from stg_timetable_events. It must not be joined
  back onto the event grain without aggregating first: an event with N causes
  would otherwise multiply that event's delay_minutes by N. That is why
  fct_delay_causes is its own fact table.

  In the 14-day sample every populated causes array has exactly one element,
  but the API permits more and this model does not assume otherwise.
#}

with trains as (

    select * from {{ source('raw', 'trains') }}

),

events as (

    select
        {{ event_key(
            'cast(t.departureDate as date)',
            't.trainNumber',
            'r.stationShortCode',
            'r."type"',
            'r.scheduledTime'
        ) }} as event_key,
        r.causes as causes
    from trains t,
         unnest(t.timeTableRows) as u(r)
    where coalesce(len(r.causes), 0) > 0

)

select
    e.event_key,
    row_number() over (partition by e.event_key order by cause_ord) as cause_seq,
    c.categoryCode                                              as cause_category_code,
    c.detailedCategoryCode                                      as detailed_cause_category_code,
    c.thirdCategoryCode                                         as third_cause_category_code
from events e,
     unnest(e.causes) with ordinality as u(c, cause_ord)
