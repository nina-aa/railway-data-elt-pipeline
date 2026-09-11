-- Every station_short_code in the events must resolve to a dim_station row.
-- (The profile found zero missing codes; this keeps it that way as new dates
-- land.) If a code ever goes missing from the metadata, this returns it with a
-- count so the unknown-member fallback can be verified deliberately rather than
-- discovered later.

select
    e.station_short_code,
    count(*) as event_count
from {{ ref('stg_timetable_events') }} e
left join {{ ref('dim_station') }} d
    on d.station_short_code = e.station_short_code
where d.station_key is null
group by 1
order by event_count desc
