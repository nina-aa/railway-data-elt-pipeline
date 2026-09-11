-- Grain: one row per observed (train_type, train_category) combination.

with combos as (

    select distinct
        train_type,
        train_category
    from {{ ref('stg_timetable_events') }}

)

select
    row_number() over (order by train_category, train_type) as train_type_key,
    train_type,
    train_category,
    -- convenience flags used by the Stage 4 analysis
    (train_category = 'Long-distance')                      as is_long_distance,
    (train_category = 'Commuter')                           as is_commuter
from combos
