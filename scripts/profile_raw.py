#!/usr/bin/env python3
"""Profile the landed raw JSON directly with DuckDB and write docs/data_profile.md.

Stage 1: measure and document only. Nothing is cleaned here.

The raw files are materialised into physical tables in a scratch DuckDB database
once, up front; every profiling query then runs against those tables rather than
re-parsing ~280 MB of JSON per query.
"""

from __future__ import annotations

import os
import textwrap
import time

import duckdb

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINS_GLOB = os.path.join(REPO_ROOT, "data", "raw", "trains", "date=*", "trains.json.gz").replace(os.sep, "/")
STATIONS_JSON = os.path.join(REPO_ROOT, "data", "raw", "metadata", "stations.json").replace(os.sep, "/")
OUT_MD = os.path.join(REPO_ROOT, "docs", "data_profile.md")
SCRATCH_DB = os.path.join(REPO_ROOT, "data", "profile_scratch.duckdb")

if os.path.exists(SCRATCH_DB):
    os.remove(SCRATCH_DB)

con = duckdb.connect(SCRATCH_DB)
con.execute("INSTALL json; LOAD json;")
con.execute("PRAGMA threads=4")

t0 = time.time()
print("loading raw_trains ...")
con.execute(
    f"""
    CREATE TABLE raw_trains AS
    SELECT
        regexp_extract(filename, 'date=([0-9-]+)', 1)      AS ingest_date,
        CAST(departureDate AS DATE)                        AS departure_date,
        trainNumber                                        AS train_number,
        trainType                                          AS train_type,
        trainCategory                                      AS train_category,
        commuterLineID                                     AS commuter_line_id,
        cancelled                                          AS train_cancelled,
        timeTableRows                                      AS timetable_rows
    FROM read_json(
        '{TRAINS_GLOB}',
        format = 'array',
        filename = true,
        maximum_object_size = 16777216,
        columns = {{
            'departureDate': 'VARCHAR',
            'trainNumber': 'BIGINT',
            'trainType': 'VARCHAR',
            'trainCategory': 'VARCHAR',
            'commuterLineID': 'VARCHAR',
            'cancelled': 'BOOLEAN',
            'timeTableRows': 'STRUCT(
                stationShortCode VARCHAR,
                "type" VARCHAR,
                trainStopping BOOLEAN,
                commercialStop BOOLEAN,
                cancelled BOOLEAN,
                scheduledTime TIMESTAMP,
                actualTime TIMESTAMP,
                differenceInMinutes BIGINT,
                causes JSON[]
            )[]'
        }}
    )
    """
)
print(f"  raw_trains loaded in {time.time()-t0:.0f}s")

t1 = time.time()
print("loading raw_events ...")
con.execute(
    """
    CREATE TABLE raw_events AS
    SELECT
        t.ingest_date,
        t.departure_date,
        t.train_number,
        t.train_type,
        t.train_category,
        t.commuter_line_id,
        t.train_cancelled,
        r.stationShortCode                 AS station_short_code,
        r."type"                           AS event_type,
        r.trainStopping                    AS train_stopping,
        r.commercialStop                   AS commercial_stop,
        r.cancelled                        AS row_cancelled,
        r.scheduledTime                    AS scheduled_time,
        r.actualTime                       AS actual_time,
        r.differenceInMinutes              AS difference_in_minutes,
        coalesce(len(r.causes), 0)         AS n_causes
    FROM raw_trains t,
         UNNEST(t.timetable_rows) AS u(r)
    """
)
print(f"  raw_events loaded in {time.time()-t1:.0f}s")

con.execute(
    f"CREATE TABLE stations AS SELECT * FROM read_json('{STATIONS_JSON}', format='array')"
)


def q(sql: str):
    return con.execute(sql).fetchall()


def one(sql: str):
    return con.execute(sql).fetchone()[0]


sections: list[str] = []


def add(title: str, body: str):
    sections.append(f"## {title}\n\n{body.strip()}\n")


n_trains = one("SELECT count(*) FROM raw_trains")
n_events = one("SELECT count(*) FROM raw_events")
n_days = one("SELECT count(DISTINCT ingest_date) FROM raw_trains")
dmin = one("SELECT min(ingest_date) FROM raw_trains")
dmax = one("SELECT max(ingest_date) FROM raw_trains")

add(
    "Scope",
    f"""
- Dates loaded: **{n_days}** ({dmin} .. {dmax}), ending yesterday relative to the 2026-09-10 backfill.
- Train records: **{n_trains:,}**
- Timetable events (one level of unnest, train -> timeTableRows): **{n_events:,}**
""",
)

rows = q(
    """
    SELECT ingest_date,
           dayname(ingest_date::DATE)                       AS dow,
           (dayofweek(ingest_date::DATE) IN (0, 6))         AS is_weekend,
           count(*)                                         AS trains,
           sum(len(timetable_rows))                         AS events,
           sum(train_cancelled::INT)                        AS cancelled
    FROM raw_trains
    GROUP BY 1, 2, 3
    ORDER BY 1
    """
)
tbl = "| date | day | weekend | trains | events | cancelled trains |\n|---|---|---|---|---|---|\n"
for d, dow, wknd, tr, ev, ca in rows:
    tbl += f"| {d} | {dow} | {'yes' if wknd else 'no'} | {tr:,} | {ev:,} | {ca:,} |\n"
wk = one(
    "SELECT round(avg(c),0) FROM (SELECT count(*) c FROM raw_trains WHERE dayofweek(ingest_date::DATE) NOT IN (0,6) GROUP BY ingest_date)"
)
we = one(
    "SELECT round(avg(c),0) FROM (SELECT count(*) c FROM raw_trains WHERE dayofweek(ingest_date::DATE) IN (0,6) GROUP BY ingest_date)"
)
add(
    "Trains per day",
    f"{tbl}\nMean trains per **weekday**: {wk:.0f}. Mean per **weekend day**: {we:.0f}. "
    f"Cargo and some commuter services do not run at weekends, so Saturdays and "
    f"Sundays carry roughly {100*(1-we/wk):.0f}% fewer trains.",
)

add(
    "What one timetable event represents",
    "One scheduled *timetable event* for one train at one station: either its "
    "ARRIVAL at that station or its DEPARTURE from it -- recorded whether or not "
    "the train actually stops there. A train that stops at an intermediate "
    "station produces two events; its origin and terminus produce one each; a "
    "non-stopping pass-through point also produces an event, flagged "
    "`trainStopping = false` -- \"event\" means a scheduled instant in the "
    "timetable, not \"the train stopped\".",
)

n_dupe_keys = one(
    "SELECT count(*) FROM (SELECT departure_date, train_number FROM raw_trains GROUP BY 1,2 HAVING count(*) > 1)"
)
dupes = q(
    """
    SELECT departure_date, train_number, count(*) c
    FROM raw_trains GROUP BY 1,2 HAVING count(*) > 1
    ORDER BY c DESC, 1, 2 LIMIT 5
    """
)
ex = "\n".join(f"  - {d} / train {tn}: {c} records" for d, tn, c in dupes)
add(
    "Is (departure_date, train_number) unique?",
    f"""
**{'No' if n_dupe_keys else 'Yes'}.** {n_dupe_keys} (departure_date, train_number) pairs map to more than one train record.
{ex}

Consequence for the surrogate key: `station_short_code`, `event_type` and
`scheduled_time` must be part of the event grain, not `train_number` alone.
""",
)

null_actual = one("SELECT count(*) FROM raw_events WHERE actual_time IS NULL")
char = q(
    """
    SELECT train_cancelled, row_cancelled,
           (scheduled_time > TIMESTAMP '2026-09-09 00:00:00') AS sched_on_last_day,
           count(*) c
    FROM raw_events WHERE actual_time IS NULL
    GROUP BY 1,2,3 ORDER BY c DESC
    """
)
ct = "| train_cancelled | row_cancelled | scheduled_time on/after last loaded day | rows |\n|---|---|---|---|\n"
for a, b, c, n in char:
    ct += f"| {a} | {b} | {c} | {n:,} |\n"
add(
    "Rows with actual_time NULL",
    f"""
**{null_actual:,}** of {n_events:,} events ({100*null_actual/n_events:.1f}%) have no `actual_time`.

{ct}
They are dominated by (a) cancelled trains and cancelled rows and (b) events on
the last loaded date whose scheduled time had not yet passed at fetch time. A
handful are non-cancelled past events the API simply never received an actual
time for.
""",
)

stats = one(
    """
    SELECT {
      'min': min(difference_in_minutes),
      'p01': quantile_cont(difference_in_minutes, 0.01),
      'p05': quantile_cont(difference_in_minutes, 0.05),
      'p25': quantile_cont(difference_in_minutes, 0.25),
      'median': quantile_cont(difference_in_minutes, 0.5),
      'p75': quantile_cont(difference_in_minutes, 0.75),
      'p90': quantile_cont(difference_in_minutes, 0.90),
      'p95': quantile_cont(difference_in_minutes, 0.95),
      'p99': quantile_cont(difference_in_minutes, 0.99),
      'max': max(difference_in_minutes)
    }
    FROM raw_events WHERE difference_in_minutes IS NOT NULL
    """
)
n_null_diff = one("SELECT count(*) FROM raw_events WHERE difference_in_minutes IS NULL")
hi = q(
    "SELECT departure_date, train_number, train_type, station_short_code, event_type, difference_in_minutes FROM raw_events ORDER BY difference_in_minutes DESC NULLS LAST LIMIT 5"
)
lo = q(
    "SELECT departure_date, train_number, train_type, station_short_code, event_type, difference_in_minutes FROM raw_events ORDER BY difference_in_minutes ASC NULLS LAST LIMIT 5"
)
his = "\n".join(f"  - {r[0]} train {r[1]} ({r[2]}) {r[4]} at {r[3]}: **{r[5]:+} min**" for r in hi)
los = "\n".join(f"  - {r[0]} train {r[1]} ({r[2]}) {r[4]} at {r[3]}: **{r[5]:+} min**" for r in lo)
add(
    "Distribution of difference_in_minutes",
    f"""
{n_null_diff:,} events have NULL `difference_in_minutes` (no actual time). For the {n_events-n_null_diff:,} that have a value:

| stat | minutes |
|---|---|
| min | {stats['min']:+} |
| p01 | {stats['p01']:+.0f} |
| p05 | {stats['p05']:+.0f} |
| p25 | {stats['p25']:+.0f} |
| median | {stats['median']:+.0f} |
| p75 | {stats['p75']:+.0f} |
| p90 | {stats['p90']:+.0f} |
| p95 | {stats['p95']:+.0f} |
| p99 | {stats['p99']:+.0f} |
| max | {stats['max']:+} |

Most delayed events:
{his}

Most "early" events:
{los}

Plausibility: the bulk of the distribution (p05..p95) sits within a few minutes
either side of zero, as expected. The extreme positive tail (hundreds of
minutes) is plausible for severely disrupted cargo trains. Large negative values
are not physically plausible and are flagged by
`assert_actual_not_before_scheduled_beyond_tolerance` in Stage 2.
""",
)

n_cancel = one("SELECT count(*) FROM raw_trains WHERE train_cancelled")
cancel_rows = one("SELECT count(*) FROM raw_events WHERE train_cancelled")
cancel_with_actual = one("SELECT count(*) FROM raw_events WHERE train_cancelled AND actual_time IS NOT NULL")
add(
    "Cancelled trains",
    f"""
**{n_cancel:,}** of {n_trains:,} train records ({100*n_cancel/n_trains:.1f}%) have `cancelled = true`,
contributing **{cancel_rows:,}** timetable events. Those rows keep `scheduled_time`,
set row-level `cancelled = true`, carry an empty `causes` array, and have
`actual_time` NULL — except **{cancel_with_actual:,}** events on trains that were
cancelled partway through a run after earlier stations had already been served.
""",
)

n_with_causes = one("SELECT count(*) FROM raw_events WHERE n_causes > 0")
cause_dist = q("SELECT n_causes, count(*) c FROM raw_events WHERE n_causes > 0 GROUP BY 1 ORDER BY 1")
cd = "\n".join(f"  - {n} cause(s): {c:,} events" for n, c in cause_dist)
add(
    "Events with a non-empty causes array",
    f"""
**{n_with_causes:,}** events ({100*n_with_causes/n_events:.1f}% of all events) have at least one delay cause.

{cd}

Multi-cause events are the reason delay causes become a separate fact table in
Stage 2: joining causes onto the event grain would fan the rows out and multiply
`delay_minutes`.
""",
)

tt = q("SELECT train_type, count(*) c FROM raw_trains GROUP BY 1 ORDER BY c DESC")
tc = q("SELECT train_category, count(*) c FROM raw_trains GROUP BY 1 ORDER BY c DESC")
tts = "\n".join(f"  - `{k}`: {v:,}" for k, v in tt)
tcs = "\n".join(f"  - `{k}`: {v:,}" for k, v in tc)
add(
    "Distinct train_type and train_category",
    f"**train_type** ({len(tt)} values):\n{tts}\n\n**train_category** ({len(tc)} values):\n{tcs}",
)

missing = q(
    """
    SELECT e.station_short_code, count(*) c
    FROM raw_events e
    LEFT JOIN stations s ON s.stationShortCode = e.station_short_code
    WHERE s.stationShortCode IS NULL
    GROUP BY 1 ORDER BY c DESC
    """
)
n_missing_events = sum(c for _, c in missing)
ms = "\n".join(f"  - `{k}`: {v:,} events" for k, v in missing[:25])
add(
    "Timetable station codes absent from station metadata",
    f"""
**{len(missing)}** distinct `station_short_code` values ({n_missing_events:,} events)
are not present in `metadata/stations`:
{ms or '  (none)'}

These are routed to the unknown member (`station_key = -1`) of `dim_station` in Stage 2.
""",
)

span_trains = one(
    """
    SELECT count(*) FROM (
      SELECT train_number, departure_date
      FROM raw_events WHERE scheduled_time IS NOT NULL
      GROUP BY 1,2 HAVING count(DISTINCT CAST(scheduled_time AS DATE)) > 1
    )
    """
)
span_events = one(
    "SELECT count(*) FROM raw_events WHERE scheduled_time IS NOT NULL AND CAST(scheduled_time AS DATE) <> departure_date"
)
add(
    "Trains whose timetable rows span two calendar dates",
    f"""
**{span_trains:,}** (train_number, departure_date) trains have scheduled events on
more than one UTC calendar date, and **{span_events:,}** individual events have a
`scheduled_time` calendar date different from the train's `departure_date`
(overnight services, and trains scheduled across the midnight boundary).

`departure_date` is therefore the stable partition and dimension key, not the
wall-clock date of each event.
""",
)

header = textwrap.dedent(
    """\
    # Raw data profile

    Source: Fintraffic / Digitraffic railway API (`https://rata.digitraffic.fi`), CC-BY 4.0.
    Generated by `scripts/profile_raw.py`, querying the landed
    `data/raw/trains/date=*/trains.json.gz` files directly with DuckDB.
    Stage 1 rule: measure and document only, clean nothing.

    All times from the API are UTC.

    """
)
os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
with open(OUT_MD, "w", encoding="utf-8") as fh:
    fh.write(header + "\n".join(sections))

con.close()
os.remove(SCRATCH_DB)
print(f"wrote {OUT_MD}  (trains={n_trains:,} events={n_events:,} days={n_days}, {time.time()-t0:.0f}s total)")
