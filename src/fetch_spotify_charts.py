"""
Downloads Spotify Global Weekly Top 200 charts (2017-present).
Spotify Charts exposes CSV downloads — we iterate over available weeks.
Output: data/spotify_charts_raw.csv
"""

import requests
import pandas as pd
import time
import os
from datetime import date, timedelta

OUTPUT = os.path.join(os.path.dirname(__file__), "../data/spotify_charts_raw.csv")
# Spotify Charts weekly data starts here
START = date(2017, 1, 5)
END = date.today()
SLEEP_BETWEEN = 1.0

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def chart_weeks(start, end):
    # Spotify Charts weeks run Thursday → Wednesday; align to nearest Thursday
    current = start
    while current <= end:
        yield current
        current += timedelta(weeks=1)


def fetch_week(week_date):
    ds = week_date.strftime("%Y-%m-%d")
    url = f"https://charts.spotify.com/charts/view/regional-global-weekly/{ds}"
    # Try the CSV download endpoint
    csv_url = f"https://charts.spotify.com/charts/view/regional-global-weekly/{ds}/download"
    try:
        resp = requests.get(csv_url, headers=HEADERS, timeout=15)
        if resp.status_code == 200 and "text/csv" in resp.headers.get("Content-Type", ""):
            df = pd.read_csv(pd.io.common.StringIO(resp.text))
            df["week_date"] = ds
            return df
    except Exception:
        pass
    return None


def fetch_all():
    existing = pd.read_csv(OUTPUT) if os.path.exists(OUTPUT) else pd.DataFrame()
    done = set(existing["week_date"].tolist()) if not existing.empty else set()

    rows = []
    weeks = list(chart_weeks(START, END))
    total = len(weeks)
    failed = 0

    for i, w in enumerate(weeks):
        ds = w.strftime("%Y-%m-%d")
        if ds in done:
            continue

        df = fetch_week(w)
        if df is not None:
            rows.append(df)
            print(f"[{i+1}/{total}] {ds} — {len(df)} entries")
            failed = 0
        else:
            print(f"[{i+1}/{total}] {ds} — skipped (not available yet or blocked)")
            failed += 1
            if failed >= 5:
                print("5 consecutive failures — stopping early")
                break

        time.sleep(SLEEP_BETWEEN)

        if len(rows) % 50 == 0 and rows:
            _save(existing, rows)
            existing = pd.read_csv(OUTPUT)
            rows = []
            done = set(existing["week_date"].tolist())

    _save(existing, rows)
    print(f"\nDone. Saved to {OUTPUT}")


def _save(existing, new_rows):
    if not new_rows:
        return
    new_df = pd.concat(new_rows, ignore_index=True) if isinstance(new_rows[0], pd.DataFrame) else pd.DataFrame(new_rows)
    combined = pd.concat([existing, new_df], ignore_index=True) if not existing.empty else new_df
    combined.to_csv(OUTPUT, index=False)
    print(f"  → saved {len(combined)} total rows")


if __name__ == "__main__":
    fetch_all()
