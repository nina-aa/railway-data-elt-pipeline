#!/usr/bin/env python3
r"""Ad-hoc SQL against the raw landed JSON (data/raw/trains/date=*/trains.json.gz).

No new dependency: uses only duckdb (already in the project's stack), not pandas.

Exposes two views:
  trains  - one row per train (as landed, no flattening)
  events  - one row per timetable event (train -> timeTableRows, flattened)

Usage (PowerShell):
  .\.venv\Scripts\python.exe scripts\query_raw.py "select * from trains limit 3"
  .\.venv\Scripts\python.exe scripts\query_raw.py "select * from events limit 1" --full

Usage (bash):
  ./.venv/Scripts/python.exe scripts/query_raw.py "select * from trains limit 3"

With no argument, prints the top 3 trains (table form) and one full record
(every column, one per line, including the nested timeTableRows array).
"""
import os
import sys

import duckdb

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLOB = os.path.join(REPO, "data", "raw", "trains", "date=*", "trains.json.gz").replace(os.sep, "/")

con = duckdb.connect()
con.execute("INSTALL json; LOAD json;")
con.execute(f"""
    CREATE VIEW trains AS
    SELECT *, regexp_extract(filename, 'date=([0-9-]+)', 1) AS ingest_date
    FROM read_json_auto('{GLOB}', format='array', filename=true, maximum_object_size=16777216)
""")
con.execute("""
    CREATE VIEW events AS
    SELECT
        ingest_date, departureDate, trainNumber, trainType, trainCategory,
        commuterLineID, cancelled AS train_cancelled,
        r.stationShortCode, r."type" AS event_type, r.scheduledTime, r.actualTime,
        r.differenceInMinutes, r.trainStopping, r.commercialStop,
        r.cancelled AS row_cancelled, r.causes
    FROM trains, unnest(timeTableRows) AS u(r)
""")


def print_table(cur):
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    widths = [max(len(c), *(len(str(r[i])) for r in rows)) if rows else len(c)
              for i, c in enumerate(cols)]
    widths = [min(w, 40) for w in widths]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(v)[:40].ljust(w) for v, w in zip(r, widths)))


def print_full(cur):
    cols = [d[0] for d in cur.description]
    for i, row in enumerate(cur.fetchall()):
        print(f"--- row {i} ---")
        for c, v in zip(cols, row):
            print(f"  {c}: {v}")


args = sys.argv[1:]
full = "--full" in args
args = [a for a in args if a != "--full"]
sql = args[0] if args else None

if sql:
    cur = con.execute(sql)
    print_full(cur) if full else print_table(cur)
else:
    print("=== top 3 trains, table form ===")
    print_table(con.execute("select * exclude (timeTableRows) from trains order by ingest_date, trainNumber limit 3"))
    print("\n=== top 1 train, EVERY column incl. nested timeTableRows ===")
    print_full(con.execute("select * from trains order by ingest_date, trainNumber limit 1"))
