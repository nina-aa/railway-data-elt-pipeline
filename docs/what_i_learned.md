# What I learned building this

A running log of the concepts and debugging skills this project actually
exercised, tied to the specific moment each one came up — not a generic list.
Dated to when the project was built (2026-09-10/11).

## Dimensional modeling

**Grain, and why it has to be explicit.** Every table has a grain (what one
  row means). `fct_timetable_events` is one row per train × station × event
  type; `fct_delay_causes` is one row per event × cause — a strictly finer
  grain, because one event can have zero, one, or several causes.
- **Fact vs. dimension table.** A fact table holds one row per real-world
  event with measurable numbers (`fct_timetable_events`, `fct_delay_causes`); a
  dimension table holds descriptive lookups you join against (`dim_station`,
  `dim_date`). A "star schema" is a small number of facts surrounded by
  dimensions.  

- **Is it OK to have two fact tables? Yes — this is the normal pattern, not a
  workaround.** Forcing everything into one fact table would mean either a
  fixed number of `cause_1`, `cause_2`, `cause_3`... columns (breaks the moment
  an event has more causes than you provisioned for), or repeating every other
  column on the event once per cause. Kimball calls a schema with more than one
  fact table at different grains a "fact constellation" — it's standard, not
  an exception, whenever a real relationship is naturally one-to-many.

  This is *why* causes live in a separate fact table instead of a
  column on the event: it keeps the fan-out-prone join explicit and optional
  (you reach for it only when you actually want per-cause detail) rather than
  baked into every query against `fct_timetable_events`. And it's exactly what
  `assert_event_count_matches_staging` exists to catch: it compares row counts
  before and after the marts are built, so an accidental fan-out anywhere in
  the DAG would show up as `fct_timetable_events` having *more* rows than
  `stg_timetable_events` (932,094 = 932,094 here — it never happened).

- **Double
  counting in a chart.** The first "busiest stations" chart ranked Helsinki
  and Pasila by raw timetable-event count and showed Pasila at roughly 2× the
  traffic. The cause: a through-station
  like Pasila gets *two* events per train visit (an arrival and a departure),
  while Helsinki is a terminus, where that same train's number only produces
  *one* of the two (the return trip out is issued as a different train
  number). Same underlying idea as the fan-out above — one real thing counted
  more than once, distorting an aggregate — just arrived at by noticing a
  suspicious number instead of tracing a join. Fixed by re-counting as
  distinct `(train_number, date_key, station_key)` **visits** instead of raw
  events; Helsinki and Pasila came out at 14,769 vs 14,628 — essentially tied,
  which is what "genuinely comparable traffic" should look like.

- **Surrogate keys via hashing.** `event_key` is an md5 hash (a fixed-length
  fingerprint of some input text — same input always produces the same output)
  of five columns concatenated together. That's what makes re-ingesting the
  same date twice idempotent instead of producing duplicates.
- **Model-layer completeness vs. analysis-layer filtering are different
  things.** "Don't drop anything" governs the warehouse (every station stays in
  `fct_timetable_events` and `agg_station_punctuality`, however small). A
  chart excluding stations with under 200 arrivals from a *ranking* is a
  presentation choice about what's statistically meaningful to compare over 14
  days — nothing was deleted, and the excluded stations are still fully
  queryable. 

## Data quality, for real

- "Clean" is relative. This dataset has 0 nulls in every structural column
  (keys, timestamps, IDs) but real nulls and real anomalies where they're
  expected (`actual_time` null on 6.7% of events; delays down to −286 min on a
  small number of freight movements with a revised schedule). Compared to
  something like NYC taxi data (negative fares, (0,0) coordinates, impossible
  timestamps), this is well-behaved but not spotless — and the difference
  between "not yet happened" nulls (events on the last loaded day) and
  "genuinely missing" nulls (completed days with no logged actual) turned out
  to matter for how you'd explain the gap.
- **`warn`-severity tests as a design choice, not a failure.** Two dbt tests in
  this project (`assert_actual_not_before_scheduled_beyond_tolerance`,
  `assert_delay_within_plausible_range`) are *expected* to return rows. They
  exist to keep the anomaly count visible on every run, not to block the build.
- **A real bug this project caught, in itself.** `dim_date`'s range was
  originally a hardcoded var in `dbt_project.yml`. The first time the catch-up
  script pulled in a genuinely new day, every event from it got a **silent
  NULL `date_key`** — 71,918 rows — because nothing had told `dim_date` to
  grow, and no test caught it (the existing test was `relationships`, not
  `not_null`, and NULLs pass a relationships check by default). Fixed by
  deriving `dim_date`'s range from `min/max(departure_date)` in the data
  itself. Lesson: anything that has to grow as data grows should be derived
  from the data, not from a number a person has to remember to update.

## Terminology that isn't obvious from the outside

- **Database vs. data warehouse.** Same technology, different job description.
  A database is the general mechanism; "warehouse" means "this database, used
  for analytics" as opposed to running a live application. One DuckDB file on
  this laptop is both — there's no "many databases" hiding behind the word.
- **DuckDB catalog/schema confusion in the UI.** Opening the DuckDB web UI, a
  fresh query tab defaults to a scratch `memory` database, not the attached
  `warehouse` one — tables have to be addressed as `warehouse.main.table_name`
  or the tab's catalog switched explicitly. An easy trap the first time.

## Real environment debugging

On Windows, `bash` can resolve to three different binaries — Git Bash (MSYS) or
WSL (real Linux) — and only Git Bash auto-translates POSIX paths and appends
`.exe` to bare executable names, so running the same script under WSL sent
malformed paths and a stray `\r` (from a Windows-native `python.exe`'s
newline translation) into simple tools and produced a wall of unrelated-looking
tracebacks. 

Also: a single-file embedded database like DuckDB allows only one
writer, so leaving its browser UI open locks `warehouse.duckdb` against
`dbt build` until that process ends.
