#!/usr/bin/env python3
"""Historical ingestion for the Finnish railway punctuality pipeline.

Fetches /api/v1/trains/{date} from the Digitraffic railway API for a date range,
lands the raw JSON response gzipped on disk, and records a per-date watermark in
a DuckDB table so a later incremental run knows where to resume.

Land raw, parse later: the raw response is written to disk before any parsing.
If the downstream parser is wrong, re-parse the landed files rather than
re-calling a public API.

Usage:
    python scripts/ingest.py --start 2026-08-27 --end 2026-09-09
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import sys
import time

import duckdb
import requests

# --- Paths ------------------------------------------------------------------
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_TRAINS_DIR = os.path.join(REPO_ROOT, "data", "raw", "trains")
RAW_METADATA_DIR = os.path.join(REPO_ROOT, "data", "raw", "metadata")
DUCKDB_PATH = os.path.join(REPO_ROOT, "warehouse.duckdb")

# --- API config -----------------------------------------------------------
BASE_URL = "https://rata.digitraffic.fi"
HEADERS = {
    "Digitraffic-User": "personal-learning-project",
    "Accept-Encoding": "gzip",
}
REQUEST_TIMEOUT = 60          # seconds
SLEEP_BETWEEN_DATES = 1.5     # seconds, >= 1s as required by request etiquette
MAX_RETRIES = 5
METADATA_MAX_AGE_DAYS = 7


class IngestError(RuntimeError):
    """Raised when a date could not be ingested. The watermark is not advanced."""


# --- HTTP with retry / backoff ------------------------------------------------
def get_with_retry(path: str) -> requests.Response:
    """GET BASE_URL+path, retrying on 5xx and timeouts with exponential backoff."""
    url = BASE_URL + path
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_err = exc
        else:
            if resp.status_code < 500:
                return resp
            last_err = IngestError(f"{resp.status_code} for {url}")
        backoff = 2 ** attempt
        print(f"  attempt {attempt}/{MAX_RETRIES} failed ({last_err}); "
              f"sleeping {backoff}s", file=sys.stderr)
        time.sleep(backoff)
    raise IngestError(f"giving up on {url} after {MAX_RETRIES} attempts: {last_err}")


# --- Atomic write ----------------------------------------------------------
def write_atomic(dest_path: str, data: bytes) -> None:
    """Write bytes to dest_path atomically: temp file in the same dir, then rename."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    tmp_path = f"{dest_path}.tmp.{os.getpid()}"
    with open(tmp_path, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, dest_path)  # atomic on the same filesystem, overwrites


# --- Watermark table -------------------------------------------------------
def ensure_state_table(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ingestion_state (
            date          DATE PRIMARY KEY,
            fetched_at    TIMESTAMP NOT NULL,
            response_bytes BIGINT NOT NULL,   -- uncompressed JSON body size
            gz_bytes      BIGINT NOT NULL,    -- size of the stored .json.gz
            num_trains    INTEGER NOT NULL
        )
        """
    )


def record_watermark(con: duckdb.DuckDBPyConnection, date_str: str,
                     response_bytes: int, gz_bytes: int, num_trains: int) -> None:
    con.execute("DELETE FROM ingestion_state WHERE date = ?", [date_str])
    con.execute(
        "INSERT INTO ingestion_state VALUES (?, ?, ?, ?, ?)",
        [date_str, dt.datetime.now(), response_bytes, gz_bytes, num_trains],
    )


# --- Metadata ------------------------------------------------------------------
def fetch_metadata_if_stale() -> None:
    """Refresh station and cause-code metadata only when missing or > 7 days old."""
    targets = {
        "stations.json": "/api/v1/metadata/stations",
        "cause_codes.json": "/api/v1/metadata/cause-category-codes",
        "detailed_cause_codes.json": "/api/v1/metadata/detailed-cause-category-codes",
    }
    os.makedirs(RAW_METADATA_DIR, exist_ok=True)
    cutoff = time.time() - METADATA_MAX_AGE_DAYS * 86400
    for filename, path in targets.items():
        dest = os.path.join(RAW_METADATA_DIR, filename)
        if os.path.exists(dest) and os.path.getmtime(dest) > cutoff:
            print(f"metadata {filename}: fresh, skipping")
            continue
        print(f"metadata {filename}: fetching {path}")
        resp = get_with_retry(path)
        if resp.status_code != 200:
            raise IngestError(f"metadata {path} returned {resp.status_code}")
        payload = resp.json()  # validate it parses
        if not isinstance(payload, list) or not payload:
            raise IngestError(f"metadata {path} returned an empty/invalid body")
        write_atomic(dest, resp.content)
        time.sleep(SLEEP_BETWEEN_DATES)


# --- One date ----------------------------------------------------------------
def ingest_date(con: duckdb.DuckDBPyConnection, date_str: str) -> int:
    """Fetch one date, land it, validate, record the watermark. Returns train count."""
    print(f"date {date_str}: fetching /api/v1/trains/{date_str}")
    resp = get_with_retry(f"/api/v1/trains/{date_str}")
    if resp.status_code == 404:
        raise IngestError(f"{date_str}: 404 (no data for this date)")
    if resp.status_code != 200:
        raise IngestError(f"{date_str}: unexpected status {resp.status_code}")

    body = resp.content  # decoded JSON bytes = the raw response body

    # Land raw BEFORE parsing.
    gz_bytes = gzip.compress(body, compresslevel=6)
    dest = os.path.join(RAW_TRAINS_DIR, f"date={date_str}", "trains.json.gz")
    write_atomic(dest, gz_bytes)

    # Validate. Do not advance the watermark on an empty or malformed body.
    try:
        trains = json.loads(body)
    except json.JSONDecodeError as exc:
        raise IngestError(f"{date_str}: response is not valid JSON: {exc}") from exc
    if not isinstance(trains, list):
        raise IngestError(f"{date_str}: expected a JSON array, got {type(trains).__name__}")
    if len(trains) == 0:
        raise IngestError(f"{date_str}: response is an empty array")

    record_watermark(con, date_str, len(body), len(gz_bytes), len(trains))
    print(f"date {date_str}: {len(trains)} trains, "
          f"{len(body)/1e6:.1f} MB body, {len(gz_bytes)/1e6:.2f} MB gz")
    return len(trains)


# --- Driver ------------------------------------------------------------------
def daterange(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--start", required=True, help="first date, inclusive (YYYY-MM-DD)")
    p.add_argument("--end", required=True, help="last date, inclusive (YYYY-MM-DD)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)
    if start > end:
        print(f"--start {start} is after --end {end}", file=sys.stderr)
        return 2

    os.makedirs(os.path.dirname(DUCKDB_PATH), exist_ok=True)
    con = duckdb.connect(DUCKDB_PATH)
    try:
        ensure_state_table(con)
        fetch_metadata_if_stale()

        dates = list(daterange(start, end))
        failed: list[tuple[str, str]] = []
        t0 = time.time()
        for i, day in enumerate(dates):
            date_str = day.isoformat()
            try:
                ingest_date(con, date_str)
            except IngestError as exc:
                print(f"FAILED {date_str}: {exc}", file=sys.stderr)
                failed.append((date_str, str(exc)))
            if i < len(dates) - 1:
                time.sleep(SLEEP_BETWEEN_DATES)

        elapsed = time.time() - t0
        ok = len(dates) - len(failed)
        print(f"\ndone: {ok}/{len(dates)} dates in {elapsed:.0f}s")
        if failed:
            print("failed dates:", file=sys.stderr)
            for date_str, msg in failed:
                print(f"  {date_str}: {msg}", file=sys.stderr)
            return 1
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
