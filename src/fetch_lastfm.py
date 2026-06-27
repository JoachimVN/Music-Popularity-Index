"""
Fetches Last.fm top tracks via chart.getTopTracks (paginated).
Returns the most-scrobbled songs globally — no per-song querying needed.
Output: data/lastfm_raw.csv
"""

import requests
import pandas as pd
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import LAST_FM_API_KEY

OUTPUT = os.path.join(os.path.dirname(__file__), "../data/lastfm_raw.csv")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"
PAGES = 200       # 50 tracks per page → 10,000 tracks total
SLEEP_BETWEEN = 0.2


def fetch_page(page):
    resp = requests.get(BASE_URL, params={
        "method": "chart.getTopTracks",
        "api_key": LAST_FM_API_KEY,
        "format": "json",
        "limit": 50,
        "page": page,
    }, timeout=10)
    data = resp.json()
    tracks = data.get("tracks", {}).get("track", [])
    rows = []
    for t in tracks:
        rows.append({
            "title": t.get("name", ""),
            "artist": t.get("artist", {}).get("name", ""),
            "playcount": int(t.get("playcount", 0)),
            "listeners": int(t.get("listeners", 0)),
        })
    return rows


def fetch_all():
    rows = []
    for page in range(1, PAGES + 1):
        try:
            page_rows = fetch_page(page)
            rows.extend(page_rows)
            if page % 20 == 0:
                print(f"Page {page}/{PAGES} — {len(rows)} tracks so far")
        except Exception as e:
            print(f"Page {page} failed: {e}")
        time.sleep(SLEEP_BETWEEN)

    df = pd.DataFrame(rows).drop_duplicates(subset=["title", "artist"])
    df.to_csv(OUTPUT, index=False)
    print(f"\nSaved {len(df)} tracks to {OUTPUT}")
    print("\nTop 10 by playcount:")
    print(df.nlargest(10, "playcount")[["title", "artist", "playcount"]].to_string(index=False))
    return df


if __name__ == "__main__":
    fetch_all()
