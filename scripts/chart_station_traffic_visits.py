#!/usr/bin/env python3
"""Extra chart, not one of the Stage 4 required 6 -- variant of
chart_station_traffic.py that fixes the Pasila/Helsinki double-count.

chart_station_traffic.py counted TIMETABLE EVENTS: a through-station gets an
ARRIVAL and a DEPARTURE event per train visit (2), while a terminus typically
gets only one of the two (that train_number ends or begins there) -- so a
through station like Pasila shows ~2x a comparable terminus like Helsinki for
reasons that have nothing to do with real traffic volume.

This script counts VISITS instead: one row per (train, day, station) where the
train stops, regardless of whether that produced one event or two. Passenger =
Commuter + Long-distance; Cargo = Cargo. Reads the already-built marts in
warehouse.duckdb.

Run it yourself:
  PowerShell:  .\.venv\Scripts\python.exe scripts\chart_station_traffic_visits.py
  bash:        ./.venv/Scripts/python.exe scripts/chart_station_traffic_visits.py

Writes docs/charts/08_station_traffic_by_visit.png
"""
import os

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB = os.path.join(REPO, "warehouse.duckdb")
OUT = os.path.join(REPO, "docs", "charts", "08_station_traffic_by_visit.png")

BLUE, ORANGE, INK, MUTED = "#2f6fbf", "#d97a2b", "#1f2328", "#6b7280"

plt.rcParams.update({
    "figure.dpi": 150, "savefig.dpi": 150, "savefig.bbox": "tight",
    "font.family": "DejaVu Sans", "font.size": 10,
    "axes.edgecolor": "#c9ccd1", "axes.linewidth": 0.8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlepad": 12,
    "axes.grid": True, "grid.color": "#e6e8eb", "grid.linewidth": 0.7,
})

con = duckdb.connect(DUCKDB, read_only=True)


def top_stations(categories, n=15):
    placeholders = ", ".join(f"'{c}'" for c in categories)
    sql = f"""
        with visits as (
            -- one row per train per day per station it stops at, regardless of
            -- whether that produced one timetable event (terminus) or two
            -- (arrival + departure at a through station)
            select distinct
                f.train_number, f.date_key, f.station_key
            from fct_timetable_events f
            join dim_train_type d using (train_type_key)
            where f.is_stopping
              and d.train_category in ({placeholders})
        )
        select s.station_name, s.station_short_code, count(*) as visit_count
        from visits v
        join dim_station s using (station_key)
        group by 1, 2
        order by visit_count desc
        limit {n}
    """
    return con.execute(sql).fetchall()


passenger = top_stations(["Commuter", "Long-distance"])
cargo = top_stations(["Cargo"])

fig, axes = plt.subplots(1, 2, figsize=(13, 6.6))
fig.subplots_adjust(wspace=0.55)
for ax, rows, colour, title in (
    (axes[0], passenger, BLUE, "Passenger (Commuter + Long-distance)"),
    (axes[1], cargo, ORANGE, "Cargo"),
):
    rows = rows[::-1]
    names = [f"{r[0]}  ({r[1]})" for r in rows]
    vals = [r[2] for r in rows]
    ypos = range(len(rows))
    ax.barh(ypos, vals, color=colour, height=0.72)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(names, fontsize=11)
    ax.set_xlabel("Train visits (arrival + departure counted once), 14 days", fontsize=10.5)
    ax.tick_params(axis="x", labelsize=10)
    ax.set_title(title, fontsize=13)
    for y, v in zip(ypos, vals):
        ax.text(v + max(vals) * 0.012, y, f"{v:,}", va="center", fontsize=10, color=INK)

fig.suptitle("Busiest stations by train visits — passenger vs cargo",
             fontsize=15, fontweight="bold", y=1.02)
fig.text(0.5, -0.02,
         "One visit = one train stopping at a station once, whether that produced "
         "one timetable event (terminus) or two (through-station arrival + departure).",
         ha="center", fontsize=8, color=MUTED)
fig.savefig(OUT)
plt.close(fig)

print("wrote", OUT)
print("\nPassenger top 5 (by visits):")
for r in passenger[:5]:
    print(" ", r)
print("\nCargo top 5 (by visits):")
for r in cargo[:5]:
    print(" ", r)
