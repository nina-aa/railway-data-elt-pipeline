{#
  Surrogate key for a timetable event.

  Grain: one train, at one station, for one event type (ARRIVAL / DEPARTURE),
  at one scheduled time. scheduled_time is in the hash because a train can call
  at the same station more than once (reversals, loops) and because
  (departure_date, train_number) is not guaranteed unique by the API.

  Every component is coalesced to the literal 'NULL' so that a missing value
  cannot silently collapse two distinct events into one hash (concat_ws drops
  NULL arguments).
#}
{% macro event_key(departure_date, train_number, station_short_code, event_type, scheduled_time) %}
md5(concat_ws('|',
    coalesce(cast({{ departure_date }} as varchar), 'NULL'),
    coalesce(cast({{ train_number }} as varchar), 'NULL'),
    coalesce(cast({{ station_short_code }} as varchar), 'NULL'),
    coalesce(cast({{ event_type }} as varchar), 'NULL'),
    coalesce(strftime({{ scheduled_time }}, '%Y-%m-%dT%H:%M:%S'), 'NULL')
))
{% endmacro %}
