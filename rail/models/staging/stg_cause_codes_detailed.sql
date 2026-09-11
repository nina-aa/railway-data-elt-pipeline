{#
  Detailed delay cause category codes (E1, E2, T1, ...). Descriptions only;
  fct_delay_causes references these codes as attributes, not via a dimension.
#}

with source as (

    select * from {{ source('raw', 'detailed_cause_codes') }}

)

select
    detailedCategoryCode        as detailed_cause_category_code,
    detailedCategoryName        as detailed_cause_category_name,
    cast(validFrom as date)     as valid_from
from source
