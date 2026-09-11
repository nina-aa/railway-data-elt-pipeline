{#
  Delay cause category codes (the coarse level: A, E, L, T, ...).
  The detailed and third levels are carried as attributes on fct_delay_causes;
  stg_cause_codes_detailed holds their descriptions.
#}

with source as (

    select * from {{ source('raw', 'cause_codes') }}

)

select
    categoryCode              as cause_category_code,
    categoryName              as cause_category_name,
    cast(validFrom as date)   as valid_from
from source
