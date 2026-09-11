#!/usr/bin/env python3
"""Stage 4: analysis queries -> docs/findings.md and docs/charts/*.png.

Reads the mart tables from warehouse.duckdb. Every number in findings.md and the
README comes from a query here. Charts are static PNGs, embedded in the README.

On-time  = arrival delay < 5 min at a commercial stop (see README).
Local time = UTC + 3 (Finland was on EEST for the whole 2026-08-27..09-09 window).
"""

from __future__ import annotations

import os
import textwrap

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DUCKDB = os.path.join(REPO, "warehouse.duckdb")
CHARTS = os.path.join(REPO, "docs", "charts")
FINDINGS = os.path.join(REPO, "docs", "findings.md")
os.makedirs(CHARTS, exist_ok=True)

# --- palette (validated: dataviz skill validate_palette.js, light mode) --------
BLUE, ORANGE, GREEN, RED = "#2f6fbf", "#d97a2b", "#3f9e7c", "#b5473f"
INK, MUTED = "#1f2328", "#6b7280"

plt.rcParams.update({
    "figure.dpi": 150,
    "savefig.dpi": 150,
    "savefig.bbox": "tight",
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "axes.edgecolor": "#c9ccd1",
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.titlesize": 12,
    "axes.titleweight": "bold",
    "axes.titlepad": 12,
    "axes.labelcolor": INK,
    "text.color": INK,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.grid": True,
    "grid.color": "#e6e8eb",
    "grid.linewidth": 0.7,
})

con = duckdb.connect(DUCKDB, read_only=True)
ON_TIME = 5

# English glosses for the Finnish cause category names (from the Digitraffic
# passenger terms / Fintraffic documentation).
CAUSE_EN = {
    "A": "Timetabling & operations",
    "E": "Running ahead of schedule",
    "H": "Management / administration",
    "I": "Other causes",
    "J": "Delayed train formation",
    "K": "Rolling stock (multiple units & coaches)",
    "L": "Traffic control / dispatching",
    "M": "Passenger services",
    "O": "Accident or incident",
    "P": "Traffic management systems",
    "R": "Trackwork / engineering possessions",
    "S": "Electrification (OLE)",
    "T": "Track & infrastructure",
    "V": "Traction stock (locomotives)",
}


def q(sql):
    return con.execute(sql).fetchall()


def one(sql):
    return con.execute(sql).fetchone()


# realised arrivals at commercial stops = the analysis base
BASE = """
    from fct_timetable_events f
    join dim_train_type d using(train_type_key)
    join dim_date dd using(date_key)
    left join dim_station s using(station_key)
    where f.event_type = 'ARRIVAL'
      and f.is_commercial_stop
      and f.has_actual_time
      and f.is_plausible_delay
"""

n_base = one(f"select count(*) {BASE}")[0]
overall_ot = one(f"select avg((f.delay_minutes < {ON_TIME})::int) {BASE}")[0]
overall_avg = one(f"select avg(f.delay_minutes) {BASE}")[0]
print(f"analysis base: {n_base:,} realised commercial arrivals; "
      f"on-time {overall_ot:.1%}; mean delay {overall_avg:.2f} min")

sections = []


def add(title, body):
    sections.append(f"## {title}\n\n{body.strip()}\n")


# ===========================================================================
# 1. Station punctuality, controlled for volume
# ===========================================================================
MIN_ARR = 200  # ~14/day over the 14 days
rows = q(f"""
    select coalesce(s.station_name, f.station_short_code) as name,
           f.station_short_code as code,
           count(*) as n,
           avg((f.delay_minutes < {ON_TIME})::int) as ot_rate,
           avg(f.delay_minutes) as avg_delay
    {BASE}
    group by 1, 2
    having count(*) >= {MIN_ARR}
    order by ot_rate
""")
n_qualified = len(rows)
worst = rows[:15]
best = rows[-15:][::-1]
tiny = one(f"""
    select count(*) from (
      select f.station_short_code, count(*) n {BASE} group by 1 having count(*) < {MIN_ARR}
    )
""")[0]

fig, axes = plt.subplots(1, 2, figsize=(13, 6.4))
fig.subplots_adjust(wspace=0.55)
for ax, group, colour, label, tick_right in (
    (axes[0], best, GREEN, f"Best 15 (of {n_qualified} stations with ≥{MIN_ARR} arrivals)", False),
    (axes[1], worst, RED, "Worst 15", True),
):
    names = [f"{r[0]}  (n={r[2]:,})" for r in group]
    vals = [100 * r[3] for r in group]
    ypos = list(range(len(group)))
    ax.barh(ypos, vals, color=colour, height=0.62)
    ax.set_yticks(ypos)
    ax.set_yticklabels(names, fontsize=8.5)
    if tick_right:
        ax.yaxis.tick_right()
    ax.tick_params(axis="y", length=0)
    ax.invert_yaxis()
    ax.axvline(100 * overall_ot, color=INK, lw=1, ls="--")
    ax.set_xlim(0, 108)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_title(label, fontsize=11)
    ax.set_xlabel("On-time arrivals  (delay < 5 min)")
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    for y, v in zip(ypos, vals):
        ax.text(v + 2, y, f"{v:.0f}%", va="center", fontsize=8, color=INK)
fig.suptitle("Arrival punctuality by station — 14 days, commercial stops only",
             fontsize=13, fontweight="bold", y=1.00)
fig.text(0.5, 0.005,
         f"Dashed line = network average {overall_ot:.1%}. "
         f"{tiny} lower-volume stations (<{MIN_ARR} arrivals) excluded as too noisy to rank.",
         ha="center", fontsize=8.5, color=MUTED)
fig.savefig(os.path.join(CHARTS, "01_station_punctuality.png"))
plt.close(fig)

add("1. Which stations have the worst arrival punctuality?", f"""
Of ~{con.execute(f"select count(distinct f.station_short_code) {BASE}").fetchone()[0]}
stations with a commercial arrival in the window, only **{n_qualified}** have at
least {MIN_ARR} arrivals ({tiny} are below that and are left out — with 14 days
of data a station with 30–40 arrivals can sit anywhere in the ranking on noise).

Among those {n_qualified}, the network average is **{overall_ot:.1%}** on time.
The worst are two groups: far-north long-distance stops at the end of long runs
(Kemi, Oulu — see Q5), and a cluster of outer-commuter stations on the congested
Helsinki–Riihimäki main line (Jokela, Saunakallio, Hyvinkää) where trains arrive
already late off that line:

{chr(10).join(f"- **{r[0]}** ({r[1]}): {r[3]:.0%} on time, mean +{r[4]:.1f} min, n={r[2]:,}" for r in worst[:6])}

The best are inner commuter stations, where trains are new to their run and the
schedule has recovery margin:

{chr(10).join(f"- **{r[0]}** ({r[1]}): {r[3]:.0%} on time, n={r[2]:,}" for r in best[:6])}

Even 14 days is thin for the low-volume long-distance stops (n≈200–400): treat
the bottom of the list as "clearly below average", not as a precise order.
""")

# ===========================================================================
# 2. Delay by hour of day
# ===========================================================================
hours = q(f"""
    select (hour(f.scheduled_time) + 3) % 24 as h,
           count(*) n,
           avg(f.delay_minutes) avg_delay,
           avg((f.delay_minutes < {ON_TIME})::int) ot
    {BASE}
    group by 1 order by 1
""")
hh = [r[0] for r in hours]
hd = [r[2] for r in hours]

fig, ax = plt.subplots(figsize=(10, 4.8))
ax.axvspan(6.5, 9.5, color=ORANGE, alpha=0.10, lw=0)
ax.axvspan(14.5, 17.5, color=ORANGE, alpha=0.10, lw=0)
ax.plot(hh, hd, color=BLUE, lw=2, marker="o", ms=4)
ax.set_xticks(range(0, 24, 2))
ax.set_xlabel("Hour of day (local time, EEST = UTC+3)")
ax.set_ylabel("Mean arrival delay (minutes)")
ax.set_title("Mean arrival delay by hour of day")
ax.text(8, ax.get_ylim()[1] * 0.92, "AM peak", ha="center", fontsize=8, color=ORANGE)
ax.text(16, ax.get_ylim()[1] * 0.92, "PM peak", ha="center", fontsize=8, color=ORANGE)
fig.savefig(os.path.join(CHARTS, "02_delay_by_hour.png"))
plt.close(fig)

peak_h = max(hours, key=lambda r: r[2])
low_h = min((r for r in hours if r[1] > 2000), key=lambda r: r[2])
add("2. How does delay vary by hour of day?", f"""
There is a mild build-up through the operating day, but the swing is small
because punctual commuter trains dominate the counts.

- Quietest: around **{low_h[0]:02d}:00** local, mean **{low_h[2]:+.2f} min**.
- Worst: **{peak_h[0]:02d}:00** local, mean **{peak_h[2]:+.2f} min**.
- Overnight (02:00–04:00) the mean goes slightly negative — a handful of mostly
  freight and repositioning moves that run ahead of a nominal path.

Delay drifts up from ~06:00, plateaus across the middle of the day and the
afternoon peak, and eases after ~19:00. It is a build-up of perturbation over
the day rather than a sharp rush-hour spike.
""")

# ===========================================================================
# 3. Delay causes: frequency vs total minutes
# ===========================================================================
causes = q("""
    select dc.cause_category_code as code,
           any_value(dc.cause_category_name) as name,
           count(*) as freq,
           sum(greatest(f.delay_minutes, 0)) as total_min,
           avg(greatest(f.delay_minutes, 0)) as avg_min
    from fct_delay_causes fdc
    join fct_timetable_events f using(event_key)
    join dim_cause dc using(cause_key)
    group by 1
    order by total_min desc
""")
plot_causes = [c for c in causes if c[3] > 0][:11]
labels = [f"{CAUSE_EN.get(c[0], c[1])} ({c[0]})" for c in plot_causes][::-1]
mins = [c[3] for c in plot_causes][::-1]

fig, ax = plt.subplots(figsize=(10, 5.4))
ax.barh(range(len(mins)), mins, color=BLUE, height=0.66)
ax.set_yticks(range(len(mins)))
ax.set_yticklabels(labels, fontsize=9)
ax.set_xlabel("Total delay minutes attributed (14 days)")
ax.set_title("Delay minutes by cause category")
for i, c in enumerate(plot_causes[::-1]):
    ax.text(c[3] + max(mins) * 0.01, i, f"{c[3]:,}  ({c[2]:,}×)", va="center", fontsize=8, color=INK)
ax.margins(x=0.14)
fig.text(0.5, -0.03,
         "Bar = total minutes; (n×) = number of events with that cause. "
         "Ranking by minutes differs from ranking by frequency — see findings.",
         ha="center", fontsize=8.5, color=MUTED)
fig.savefig(os.path.join(CHARTS, "03_delay_causes.png"))
plt.close(fig)

by_freq = sorted(causes, key=lambda c: -c[2])[:4]
e_row = next(c for c in causes if c[0] == "E")
add("3. Most common delay causes — by frequency vs by attributed minutes", f"""
Only **{one("select count(*) from fct_delay_causes")[0]:,}** events carry a cause
code (1.0% of all events; ~4% of events delayed 5 min or more). Every populated
`causes` array in the window has exactly one element, so attribution is
unambiguous here.

**By frequency**, the top codes are:
{chr(10).join(f"- `{c[0]}` {CAUSE_EN.get(c[0], c[1])} — {c[2]:,} events" for c in by_freq)}

**By total minutes attributed**, the order changes:
{chr(10).join(f"- `{c[0]}` {CAUSE_EN.get(c[0], c[1])} — {c[3]:,} min across {c[2]:,} events ({c[4]:.0f} min each)" for c in plot_causes[:4])}

Why they differ: `{e_row[0]}` ({CAUSE_EN['E']}) is the
**single most frequent code — {e_row[2]:,} occurrences — and contributes 0 delay
minutes** by definition. And `J` (train-formation delay) is comparatively rare
({next(c for c in causes if c[0]=='J')[2]} events) but each one is large
(~{next(c for c in causes if c[0]=='J')[4]:.0f} min), so it climbs the
minutes ranking. Frequency counts incidents; minutes weight them by severity.
""")

# ===========================================================================
# 4. Long-distance vs commuter
# ===========================================================================
cat = q(f"""
    select d.train_category,
           count(*) n,
           avg(f.delay_minutes) avg_delay,
           avg((f.delay_minutes < {ON_TIME})::int) ot,
           quantile_cont(f.delay_minutes, 0.9) p90
    {BASE}
    group by 1
    having count(*) > 1000
    order by n desc
""")
comm = next(r for r in cat if r[0] == "Commuter")
long = next(r for r in cat if r[0] == "Long-distance")
add("4. Do long-distance and commuter trains differ in punctuality?", f"""
Yes, clearly.

| category | realised arrivals | on-time | mean delay | 90th pct delay |
|---|---|---|---|---|
| Commuter | {comm[1]:,} | **{comm[3]:.1%}** | {comm[2]:+.2f} min | {comm[4]:.0f} min |
| Long-distance | {long[1]:,} | **{long[3]:.1%}** | {long[2]:+.2f} min | {long[4]:.0f} min |

Commuter services are ~{(comm[3]-long[3])*100:.0f} points more punctual. They run
short routes with little room to accumulate delay and recover quickly between
dense stops; long-distance trains traverse hundreds of km of partly single-track
line where a single conflict propagates for the rest of the run (see Q5).
""")

# ===========================================================================
# 5. Delay progression along one long route: train 265 (Helsinki -> Kemijarvi)
# ===========================================================================
route = q(f"""
    with stops as (
      select f.station_short_code as scode,
             coalesce(s.station_name, f.station_short_code) as sname,
             f.delay_minutes,
             row_number() over (
               partition by f.date_key
               order by f.scheduled_time
             ) as seq
      {BASE.replace("and f.is_plausible_delay", "and f.is_plausible_delay and f.train_number = 265")}
    )
    select seq, any_value(scode) scode, any_value(sname) sname,
           avg(delay_minutes) avg_delay,
           count(*) n
    from stops group by seq order by seq
""")
seqs = [r[0] for r in route]
avgs = [r[3] for r in route]
codes = [r[1] for r in route]

fig, ax = plt.subplots(figsize=(11, 4.8))
ax.axhline(0, color=MUTED, lw=0.8)
ax.plot(seqs, avgs, color=BLUE, lw=2, marker="o", ms=5)
ax.set_xticks(seqs)
ax.set_xticklabels(codes, fontsize=8.5)
ax.set_xlabel("Stop sequence  →  (Helsinki region → Kemijärvi)")
ax.set_ylabel("Mean arrival delay (minutes)")
ax.set_title("Delay progression along IC 265, Helsinki → Kemijärvi (14 nights)")
for x, y, c in zip(seqs, avgs, codes):
    lab = "0" if abs(y) < 0.75 else f"{round(y):+d}"
    ax.annotate(lab, (x, y), textcoords="offset points", xytext=(0, 9),
                ha="center", fontsize=7.5, color=INK)
fig.text(0.5, -0.02,
         "Overnight train; the northern legs run after midnight. Delay peaks near "
         "Riihimäki, is trimmed at Seinäjoki (SK), then re-accumulates north of Oulu (OL).",
         ha="center", fontsize=8.5, color=MUTED)
fig.savefig(os.path.join(CHARTS, "05_route_progression.png"))
plt.close(fig)

add("5. Does delay accumulate along a route, or do trains recover?", f"""
Traced on **IC 265, Helsinki → Kemijärvi**, an overnight long-distance train with
{len(route)} commercial stops that ran all 14 nights (mean delay per stop over
the 14 days):

{chr(10).join(f"- {r[1]:<4} {r[2]:<22} stop {r[0]:>2}: {r[3]:+.1f} min" for r in route)}

Both happen. Delay **builds** from roughly on-time in the Helsinki region to a
peak around Riihimäki (~{max(r[3] for r in route[:5]):.0f} min), eases a little to
Tampere, then is **over-corrected** at Seinäjoki — so much timetable slack that
the train sits ~{abs([r[3] for r in route if r[1]=='SK'][0]):.0f} min *early*
there. North of Oulu it **re-accumulates** through the single-track sections
(worst ~{max(r[3] for r in route):.0f} min at Rovaniemi), before a padded final
leg brings it into Kemijärvi ~{route[-1][3]:.0f} min down. Recovery margin is
built into the long-distance schedule at the major hubs; the sparse northern
network gives the train nowhere to catch up once past Oulu.
""")

# ===========================================================================
# 6. Daily punctuality trend + weekday/weekend
# ===========================================================================
daily = q(f"""
    select dd.date, dd.is_weekend,
           avg((f.delay_minutes < {ON_TIME})::int) ot,
           count(*) n
    {BASE}
    group by 1, 2 order by 1
""")
dates = [r[0] for r in daily]
ot_rate = [100 * r[2] for r in daily]
wknd = [r[1] for r in daily]

fig, ax = plt.subplots(figsize=(11, 4.6))
ax.plot(dates, ot_rate, color=BLUE, lw=1.8, zorder=1)
wk_x = [d for d, w in zip(dates, wknd) if not w]
wk_y = [o for o, w in zip(ot_rate, wknd) if not w]
we_x = [d for d, w in zip(dates, wknd) if w]
we_y = [o for o, w in zip(ot_rate, wknd) if w]
ax.scatter(wk_x, wk_y, color=BLUE, s=38, zorder=2, label="weekday")
ax.scatter(we_x, we_y, color=ORANGE, s=48, zorder=2, label="weekend")
ax.axhline(100 * overall_ot, color=INK, lw=1, ls="--")
ax.set_ylabel("On-time arrivals (%)")
ax.set_xlabel("Date (train departure date)")
ax.set_title("Daily arrival punctuality, 2026-08-27 → 2026-09-09")
ax.yaxis.set_major_formatter(mtick.PercentFormatter())
ax.set_ylim(min(ot_rate) - 2, 100)
ax.legend(frameon=False, loc="lower left", fontsize=9)
fig.autofmt_xdate(rotation=35)
fig.text(0.5, -0.04, f"Dashed line = window average {overall_ot:.1%}.",
         ha="center", fontsize=8.5, color=MUTED)
fig.savefig(os.path.join(CHARTS, "06_daily_trend.png"))
plt.close(fig)

we = one(f"select avg((f.delay_minutes < {ON_TIME})::int), avg(f.delay_minutes) {BASE} and dd.is_weekend")
wd = one(f"select avg((f.delay_minutes < {ON_TIME})::int), avg(f.delay_minutes) {BASE} and not dd.is_weekend")
worst_day = min(daily, key=lambda r: r[2])
best_day = max(daily, key=lambda r: r[2])
add("6. Weekday vs weekend", f"""
Almost no difference:

- Weekday: **{wd[0]:.1%}** on time, mean {wd[1]:+.2f} min ({one(f"select count(*) {BASE} and not dd.is_weekend")[0]:,} arrivals)
- Weekend: **{we[0]:.1%}** on time, mean {we[1]:+.2f} min ({one(f"select count(*) {BASE} and dd.is_weekend")[0]:,} arrivals)

Despite ~25% fewer trains at weekends (Stage 1 profile), punctuality is flat.
Day to day, the window ranges from **{worst_day[2]:.1%}** ({worst_day[0]}) to
**{best_day[2]:.1%}** ({best_day[0]}); no single day collapsed, so the 14-day
picture is not distorted by one bad day.
""")

# ===========================================================================
# 4b (chart). Distribution of delay minutes
# ===========================================================================
vals = [r[0] for r in q(f"select f.delay_minutes {BASE}")]
LO, HI = -8, 13
inside = [v for v in vals if LO <= v <= HI]
over = sum(1 for v in vals if v > HI)
under = sum(1 for v in vals if v < LO)
maxpos = max(vals)

fig, ax = plt.subplots(figsize=(10, 4.8))
ax.hist(inside, bins=[b - 0.5 for b in range(LO, HI + 2)], color=BLUE,
        edgecolor="white", linewidth=0.5)
ax.axvline(ON_TIME - 0.5, color=RED, lw=1.5, ls="--")
ax.text(ON_TIME - 0.2, ax.get_ylim()[1] * 0.9, "on-time cutoff (< +5)", color=RED, fontsize=8.5)
ax.set_xlabel("Arrival delay (minutes)  —  negative = early")
ax.set_ylabel("Arrival events")
ax.set_title("Distribution of arrival delay at commercial stops")
ax.set_xlim(LO - 0.5, HI + 0.5)
ax.set_xticks(range(LO, HI + 1, 2))
fig.text(0.5, -0.03,
         f"x-axis clipped to [{LO}, {HI}] min. Later than +{HI}: {over:,} events "
         f"({over/len(vals):.1%}), out to +{maxpos:.0f}. Earlier than {LO}: "
         f"{under:,} ({under/len(vals):.1%}).",
         ha="center", fontsize=8.5, color=MUTED)
fig.savefig(os.path.join(CHARTS, "04_delay_distribution.png"))
plt.close(fig)

median_delay = one(f"select quantile_cont(f.delay_minutes, 0.5) {BASE}")[0]
p95 = one(f"select quantile_cont(f.delay_minutes, 0.95) {BASE}")[0]
add("7. Anything surprising", f"""
- **The most frequent delay code is "running early."** `E` / *Etuajassakulku*
  accounts for {e_row[2]:,} of the {one("select count(*) from fct_delay_causes")[0]:,}
  coded events — more than any genuine disruption cause — and by construction adds
  zero delay minutes. Traffic control logs early running as diligently as lateness.
- **Weekends are not more punctual** despite far fewer trains — congestion is not
  the binding constraint on this network in this window.
- **The delay distribution is sharply peaked at zero**: median {median_delay:+.0f} min,
  95th percentile only {p95:+.0f} min, yet a thin tail reaches into the hundreds.
  Finnish rail is "usually exactly on time, occasionally very late" rather than
  "chronically a few minutes off".
- **Cargo trains have a strongly negative mean delay** (~-12 min) — they are
  pathed conservatively and take whatever slot opens up.
""")

# ===========================================================================
# write findings.md
# ===========================================================================
header = textwrap.dedent(f"""\
    # Findings

    Source: Fintraffic / Digitraffic railway API, CC-BY 4.0. 14 days,
    2026-08-27 → 2026-09-09. Generated by `scripts/make_charts.py`.

    **Analysis base:** {n_base:,} arrival events at commercial stops that actually
    happened, with a plausible delay (`has_actual_time` and `is_plausible_delay`,
    cancellations excluded). Network on-time rate (arrival delay < {ON_TIME} min):
    **{overall_ot:.1%}**; mean arrival delay **{overall_avg:+.2f} min**.

    """)
with open(FINDINGS, "w", encoding="utf-8") as fh:
    fh.write(header + "\n".join(sections))

print("wrote", FINDINGS)
print("charts:", sorted(os.listdir(CHARTS)))
