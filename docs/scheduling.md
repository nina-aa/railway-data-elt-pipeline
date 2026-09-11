# Ingestion & scheduling

Source material for README section 7. The daily update is **run manually**.
Nothing is scheduled; nothing is added to any crontab.

## The watermark

`ingestion_state` (a table in `warehouse.duckdb`) holds one row per successfully
ingested date: the date, the fetch timestamp, the response size (uncompressed and
gzipped), and the train count. `scripts/ingest.py` writes a row only after the
response has been landed to disk **and** validated as a non-empty JSON array. A
failed, empty, or malformed response leaves the watermark untouched and the
script exits non-zero.

The watermark is the resume point. It is not "yesterday minus one" — it is the
last date actually in the warehouse, which is what makes catch-up possible.

## Catch-up behaviour

`scripts/daily_update.sh`:

1. Activates the venv (`.venv/bin` on macOS/Linux, `.venv/Scripts` on Windows Git Bash).
2. Reads `max(date)` from `ingestion_state`.
3. Fetches **every** date from `watermark + 1` through **yesterday** — not just
   yesterday. A laptop that was off Friday to Monday fetches all three missed
   days on the next run.
4. Runs `dbt build` (models + tests, in DAG order) from the `rail/` directory.
5. Appends one line to `logs/daily.log`: UTC timestamp, dates fetched, resulting
   row counts, watermark, and `PASS` / `FAIL (step)`.
6. Exits non-zero if any step failed.

Re-fetching a date that is already present is safe: `ingest.py` writes the raw
file atomically (temp file + rename) and overwrites the `ingestion_state` row,
and every model is a full rebuild, so no duplicates reach the marts.

### Verified

| run | watermark before | action | events | delay_causes | agg rows | exit |
|---|---|---|---|---|---|---|
| 1 | 2026-09-09 | up to date, no fetch, rebuild | 932,094 | 9,024 | 3,792 | 0 (PASS) |
| 2 | 2026-09-06 (rewound 3 days) | caught up 2026-09-07..09 | 932,094 | 9,024 | 3,792 | 0 (PASS) |
| 3 | 2026-09-09 | `dbt build` deliberately broken | — | — | — | 1 (FAIL logged) |

Run 2 reproduced the exact same row counts with **0 `event_key` duplicates** —
the catch-up is idempotent.

## The cron entry — DOCUMENTED, NOT INSTALLED

This is the line that *would* schedule the update. It is **not** in any crontab.

```
0 6 * * * /full/path/to/rail-pipeline/scripts/daily_update.sh >> /full/path/to/rail-pipeline/logs/cron.log 2>&1
```

### The five fields

```
0        6        *              *              *
minute   hour     day-of-month   month          day-of-week
(0-59)   (0-23)   (1-31)         (1-12)         (0-6, 0 = Sunday)
```

`0 6 * * *` = "at minute 0 of hour 6, every day-of-month, every month, every
day-of-week" — i.e. **06:00 every day**. 06:00 is chosen so a full night of
`actualTime` values has settled for the previous service day before the fetch.

The `>> .../cron.log 2>&1` appends both stdout and stderr to `logs/cron.log`
(cron has no terminal; without a redirect the output is mailed or lost).

### Why it is not installed

The script is run by hand when the user chooses. Reasons for keeping it manual
here: this is a learning project on a laptop that is not always on; an
unattended job hammering a public agency's API on a schedule is worse etiquette
than a deliberate manual run; and the catch-up logic already removes the main
benefit of scheduling.

### The laptop-must-be-on caveat (if it *were* installed)

`cron` only fires while the machine is powered on and not asleep. It does **not**
catch up missed runs on its own (that is what `anacron` is for). A cron job set
for 06:00 on a laptop that is closed at 06:00 simply does not run that day. The
catch-up logic in `daily_update.sh` is the mitigation: whenever it next runs, it
pulls every date back to the watermark, so a missed 06:00 is recovered at the
next opportunity rather than leaving a permanent hole.

### macOS notes

- Under recent macOS, `/usr/sbin/cron` needs **Full Disk Access**
  (System Settings → Privacy & Security → Full Disk Access) or the job fails
  silently on file reads.
- `launchd` with a `LaunchAgent` plist (`StartCalendarInterval`) is the native
  alternative and is the recommended mechanism on macOS; it also does not catch
  up missed runs while asleep, so the same mitigation applies.

### Windows note

Windows has no `cron`. The equivalent is Task Scheduler (or `schtasks`) invoking
`bash.exe scripts/daily_update.sh`. The script itself is portable — it detects
`.venv/Scripts` vs `.venv/bin`.

### How to verify / test

- **Did it run?** `tail logs/daily.log` (or `logs/cron.log`). Each run appends
  exactly one line ending in `PASS` or `FAIL`.
- **Test without waiting for 06:00:** run it directly —
  `bash scripts/daily_update.sh` — then check the new log line and `echo $?`.
- **Test the catch-up:** in `warehouse.duckdb`,
  `delete from ingestion_state where date >= '<a few days ago>'`, run the
  script, and confirm it re-fetches those dates and the mart row counts are
  unchanged.
