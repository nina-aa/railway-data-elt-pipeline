-- Grain: one row per station. Plus an unknown member (station_key = -1) for
-- timetable rows whose station code is absent from the metadata.

with stations as (

    select * from {{ ref('stg_stations') }}

),

keyed as (

    select
        row_number() over (order by station_short_code) as station_key,
        station_short_code,
        station_name,
        country_code,
        latitude,
        longitude,
        passenger_traffic,
        station_type
    from stations

)

select * from keyed

union all

select
    -1                 as station_key,
    'UNKNOWN'          as station_short_code,
    'Unknown station'  as station_name,
    null               as country_code,
    null               as latitude,
    null               as longitude,
    false              as passenger_traffic,
    null               as station_type
