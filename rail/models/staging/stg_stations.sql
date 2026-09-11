with source as (

    select * from {{ source('raw', 'stations') }}

)

select
    stationShortCode        as station_short_code,
    stationName             as station_name,
    stationUICCode          as station_uic_code,
    countryCode             as country_code,
    cast(latitude as double) as latitude,
    cast(longitude as double) as longitude,
    coalesce(passengerTraffic, false) as passenger_traffic,
    "type"                  as station_type
from source
