#!/usr/bin/env bash
# ============================================================================
# Daily incremental update for the Finnish railway punctuality pipeline.
#
# WHAT IT DOES
#   1. Activates the project venv.
#   2. Reads the ingestion watermark (max date in ingestion_state).
#   3. Fetches EVERY date from (watermark + 1) through yesterday -- not just
#      yesterday. If the machine was off for four days, this catches up all four.
#   4. Runs `dbt build` (seed -> run -> test, in DAG order).
#   5. Runs scripts/make_charts.py to refresh docs/findings.md and
#      docs/charts/*.png off whatever dbt just built -- not in the original
#      Stage 3 spec, but new data landing without the write-up catching up
#      isn't the behaviour anyone actually wants.
#   6. Appends one line to logs/daily.log: timestamp, dates fetched, row counts,
#      whether the charts refreshed, PASS/FAIL.
#   7. Exits non-zero if any step failed, so the failure is visible in the log
#      and in cron.log.
#
# It is run MANUALLY. Nothing schedules it. See the README for the cron entry
# that *would* schedule it (deliberately not installed) and why the catch-up
# logic above is the mitigation for cron only firing while the machine is awake.
#
# Cron runs with a minimal environment and no shell profile, so every path here
# is absolute: REPO is derived from this script's own location at runtime. To
# hard-code it instead, replace the REPO= line with e.g.
#   REPO="/c/Users/Ni/Documents/trains"
# ============================================================================

set -u
set -o pipefail

# --- absolute paths ---------------------------------------------------------
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$REPO/logs/daily.log"
DUCKDB="$REPO/warehouse.duckdb"
INGEST="$REPO/scripts/ingest.py"
MAKE_CHARTS="$REPO/scripts/make_charts.py"
DBT_DIR="$REPO/rail"

mkdir -p "$REPO/logs"

# --- refuse to run under WSL against a native-Windows venv ------------------
# WSL bash is genuine Linux: it does not translate POSIX paths ("/mnt/c/...")
# into Windows paths the way Git Bash (MSYS) does when calling a native .exe.
# Handed a path like that, a Windows python.exe reads the leading "/" as "root
# of the current drive" and silently looks in the wrong place. Fail loudly
# here instead of producing a wall of confusing tracebacks.
if [ -d "$REPO/.venv/Scripts" ] && grep -qi microsoft /proc/version 2>/dev/null; then
    echo "$(date -u +%FT%TZ) | FAIL | running under WSL against a native-Windows venv (.venv/Scripts). Use Git Bash instead, e.g.: & \"C:\\Program Files\\Git\\bin\\bash.exe\" scripts/daily_update.sh" >> "$LOG"
    echo "Refusing to run under WSL: this venv is Windows-native (.venv/Scripts)." >&2
    echo "Use Git Bash instead: & \"C:\\Program Files\\Git\\bin\\bash.exe\" scripts/daily_update.sh" >&2
    exit 1
fi

# --- venv (Windows venvs use Scripts/*.exe, macOS/Linux use bin/*) ---------
# Explicit paths need the real filename -- unlike a PATH lookup, bash does not
# auto-append .exe, and that matters here: this same venv gets invoked from
# Git Bash (which happens to paper over the missing .exe) AND from WSL bash
# (which does not, and fails with "No such file or directory" otherwise).
if [ -f "$REPO/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$REPO/.venv/bin/activate"
    PYTHON="$REPO/.venv/bin/python"
    DBT="$REPO/.venv/bin/dbt"
elif [ -f "$REPO/.venv/Scripts/activate" ]; then
    # shellcheck disable=SC1091
    source "$REPO/.venv/Scripts/activate"
    PYTHON="$REPO/.venv/Scripts/python.exe"
    DBT="$REPO/.venv/Scripts/dbt.exe"
else
    echo "$(date -u +%FT%TZ) | FAIL | no venv found at $REPO/.venv" >> "$LOG"
    exit 1
fi

TS="$(date -u +%FT%TZ)"
FAIL=0
STEP_ERR=""

fail() {
    FAIL=1
    STEP_ERR="$1"
    echo "$TS | ERROR | $1" >&2
}

# --- 2. read the watermark -------------------------------------------------
WATERMARK="$("$PYTHON" - "$DUCKDB" <<'PY'
import sys, duckdb
try:
    con = duckdb.connect(sys.argv[1], read_only=True)
    row = con.execute("select max(date) from ingestion_state").fetchone()
    print(row[0].isoformat() if row and row[0] else "")
except Exception as exc:
    print(f"__ERROR__ {exc}", file=sys.stderr)
    print("")
PY
)"

if [ -z "$WATERMARK" ]; then
    echo "$TS | FAIL | no watermark in ingestion_state -- run the backfill first (scripts/ingest.py)" >> "$LOG"
    exit 1
fi

# --- 3. compute the catch-up window ------------------------------------
# Date arithmetic in Python, not `date -d` (which is GNU-only; macOS `date` differs).
WINDOW="$("$PYTHON" - "$WATERMARK" <<'PY'
import sys, datetime as dt
watermark = dt.date.fromisoformat(sys.argv[1])
start = watermark + dt.timedelta(days=1)
end = dt.date.today() - dt.timedelta(days=1)   # yesterday
n = (end - start).days + 1
print(start.isoformat(), end.isoformat(), max(n, 0))
PY
)"
START="$(echo "$WINDOW" | awk '{print $1}')"
END="$(echo "$WINDOW" | awk '{print $2}')"
N_DATES="$(echo "$WINDOW" | awk '{print $3}')"

FETCHED_DESC="none"

if [ "$N_DATES" -eq 0 ]; then
    echo "$TS | up to date (watermark $WATERMARK, yesterday $END) -- no fetch" >&2
else
    FETCHED_DESC="$START..$END"
    echo "$TS | catching up $FETCHED_DESC ($N_DATES dates)" >&2
    if ! "$PYTHON" "$INGEST" --start "$START" --end "$END"; then
        fail "ingest.py failed for $FETCHED_DESC"
    fi
fi

# --- 4. dbt build --------------------------------------------------------
if [ "$FAIL" -eq 0 ]; then
    if ! ( cd "$DBT_DIR" && "$DBT" build --profiles-dir . ); then
        fail "dbt build failed"
    fi
fi

# --- 4b. refresh the analysis: docs/findings.md + docs/charts/*.png --------
# Not part of the original Stage 3 scope (fetch + build only), but new data
# landing silently without the write-up catching up is worse than the extra
# ~30s this costs. Runs off whatever dbt just built, so it always reflects
# the current warehouse, even on a day with nothing new to fetch.
CHARTS_STATUS="skipped (earlier step failed)"
if [ "$FAIL" -eq 0 ]; then
    if "$PYTHON" "$MAKE_CHARTS"; then
        CHARTS_STATUS="refreshed"
    else
        fail "make_charts.py failed"
        CHARTS_STATUS="FAILED"
    fi
fi

# --- 5. row counts + watermark after -----------------------------------
COUNTS="$("$PYTHON" - "$DUCKDB" <<'PY'
import sys, duckdb
con = duckdb.connect(sys.argv[1], read_only=True)
wm = con.execute("select max(date) from ingestion_state").fetchone()[0]
def count(t):
    try:
        return con.execute(f"select count(*) from {t}").fetchone()[0]
    except Exception:
        return "NA"
print(wm.isoformat() if wm else "NA", count("fct_timetable_events"), count("fct_delay_causes"))
PY
)"
NEW_WATERMARK="$(echo "$COUNTS" | awk '{print $1}')"
EVENT_ROWS="$(echo "$COUNTS" | awk '{print $2}')"
CAUSE_ROWS="$(echo "$COUNTS" | awk '{print $3}')"

# --- 5/6. log line + exit code ---------------------------------------------
if [ "$FAIL" -eq 0 ]; then
    STATUS="PASS"
else
    STATUS="FAIL ($STEP_ERR)"
fi

echo "$TS | fetched $FETCHED_DESC ($N_DATES dates) | watermark=$NEW_WATERMARK events=$EVENT_ROWS delay_causes=$CAUSE_ROWS | charts=$CHARTS_STATUS | $STATUS" >> "$LOG"

exit "$FAIL"
