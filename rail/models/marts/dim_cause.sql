-- Grain: one row per delay cause category code, from the metadata.
-- Plus an unknown member (cause_key = -1) for cause codes seen in the data
-- but absent from the metadata.

with codes as (

    select * from {{ ref('stg_cause_codes') }}

),

keyed as (

    select
        row_number() over (order by cause_category_code) as cause_key,
        cause_category_code,
        cause_category_name,
        valid_from
    from codes

)

select * from keyed

union all

select
    -1                          as cause_key,
    'UNKNOWN'                   as cause_category_code,
    'Unknown / unmapped cause'  as cause_category_name,
    null                        as valid_from
