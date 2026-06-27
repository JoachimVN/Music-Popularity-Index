"""
Scrapes Billboard Hot 100 weekly charts and saves aggregated per-song stats.
Samples every 4 weeks to keep request count manageable (~875 requests total).
Saves progress incrementally so it can be interrupted and resumed.
"""

import billboard
import pandas as pd
import time
import os
from datetime import date, timedelta

OUTPUT = os.path.join(os.path.dirname(__file__), "../data/billboard_raw.csv")
START = date(1958, 8, 4)  # First Hot 100 chart
END = date.today()
SAMPLE_EVERY_N_WEEKS = 4
SLEEP_BETWEEN = 1.5  # seconds, be polite


def date_range(start, end, step_weeks):
    current = start
    while current <= end:
        yield current
        current += timedelta(weeks=step_weeks)


def load_existing():
    if os.path.exists(OUTPUT):
        return pd.read_csv(OUTPUT)
    return pd.DataFrame()


def scrape():
    existing = load_existing()
    already_done = set(existing["week_date"].tolist()) if not existing.empty else set()

    rows = []
    dates = list(date_range(START, END, SAMPLE_EVERY_N_WEEKS))
    total = len(dates)

    for i, d in enumerate(dates):
        ds = d.strftime("%Y-%m-%d")
        if ds in already_done:
            print(f"[{i+1}/{total}] {ds} — already fetched, skipping")
            continue

        try:
            chart = billboard.ChartData("hot-100", date=ds)
            for entry in chart:
                rows.append({
                    "week_date": ds,
                    "rank": entry.rank,
                    "title": entry.title,
                    "artist": entry.artist,
                    "weeks_on_chart": entry.weeks,
                    "peak_pos": entry.peakPos,
                })
            print(f"[{i+1}/{total}] {ds} — {len(chart)} entries")
        except Exception as e:
            print(f"[{i+1}/{total}] {ds} — ERROR: {e}")

        time.sleep(SLEEP_BETWEEN)

        # Save progress every 50 weeks
        if len(rows) > 0 and (i + 1) % 50 == 0:
            _save(existing, rows)
            existing = load_existing()
            rows = []
            already_done = set(existing["week_date"].tolist())

    _save(existing, rows)
    print(f"\nDone. Saved to {OUTPUT}")


def _save(existing, new_rows):
    if not new_rows:
        return
    new_df = pd.DataFrame(new_rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    combined.to_csv(OUTPUT, index=False)
    print(f"  → saved {len(combined)} total rows")


if __name__ == "__main__":
    scrape()
