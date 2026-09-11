#!/usr/bin/env python3
"""Extra chart, not one of the Stage 4 required 6: busiest stations by traffic,
passenger vs cargo, top 15 each. Reads the already-built marts in warehouse.duckdb.

"Traffic" = timetable events where the train actually stops (is_stopping),
counted separately for:
  Passenger = train_category in ('Commuter', 'Long-distance')
  Cargo     = train_category = 'Cargo'
(Shunting / Locomotive / On-track machines / Test drive movements are excluded
from both -- they are neither passenger nor freight traffic.)

Run it yourself:
  PowerShell:  .\.venv\Scripts\python.exe scripts\chart_station_traffic.py
  bash:        ./.venv/Scripts/python.exe scripts/chart_station_traffic.py

Writes docs/charts/07_station_traffic_passenger_cargo.png
"""
import os

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB = os.path.join(REPO, "warehouse.duckdb")
OUT = os.path.join(REPO, "docs", "charts", "07_station_traffic_passenger_cargo.png")

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
        select s.station_name, s.station_short_code, count(*) as events
        from fct_timetable_events f
        join dim_train_type d using (train_type_key)
        join dim_station s using (station_key)
        where f.is_stopping
          and d.train_category in ({placeholders})
        group by 1, 2
        order by events desc
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
    ax.barh(ypos, vals, color=colour, height=0.65)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(names, fontsize=8.5)
    ax.set_xlabel("Stop events, 14 days")
    ax.set_title(title, fontsize=11)
    for y, v in zip(ypos, vals):
        ax.text(v + max(vals) * 0.012, y, f"{v:,}", va="center", fontsize=8, color=INK)

fig.suptitle("Busiest stations by traffic — passenger vs cargo (14 days)",
             fontsize=13, fontweight="bold", y=1.02)
fig.savefig(OUT)
plt.close(fig)

print("wrote", OUT)
print("\nPassenger top 5:")
for r in passenger[:5]:
    print(" ", r)
print("\nCargo top 5:")
for r in cargo[:5]:
    print(" ", r)
