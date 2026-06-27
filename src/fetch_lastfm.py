"""
Fetches Last.fm playcounts for the top N songs by current score.
Much faster than querying all 33k songs — focuses on where Last.fm data
will actually move the rankings (songs with strong Billboard/Spotify scores).
Output: data/lastfm_raw.csv
"""

import requests
import pandas as pd
import time
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import LAST_FM_API_KEY

OUTPUT = os.path.join(os.path.dirname(__file__), "../data/lastfm_raw.csv")
SCORES = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
BASE_URL = "https://ws.audioscrobbler.com/2.0/"
TOP_N = 2000       # only query the top N songs by current score
WORKERS = 8        # concurrent requests


def fetch_track(title, artist):
    try:
        resp = requests.get(BASE_URL, params={
            "method": "track.getInfo",
            "artist": artist,
            "track": title,
            "api_key": LAST_FM_API_KEY,
            "format": "json",
        }, timeout=10)
        data = resp.json()
        if "error" in data:
            return {"title": title, "artist": artist, "playcount": 0, "listeners": 0}
        track = data.get("track", {})
        return {
            "title": title,
            "artist": artist,
            "playcount": int(track.get("playcount", 0)),
            "listeners": int(track.get("listeners", 0)),
        }
    except Exception:
        return {"title": title, "artist": artist, "playcount": 0, "listeners": 0}


def fetch_all():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return

    scores = pd.read_csv(SCORES, index_col=0)
    songs = scores.head(TOP_N)[["title", "artist"]].drop_duplicates()

    existing = pd.read_csv(OUTPUT) if os.path.exists(OUTPUT) else pd.DataFrame()
    done = set(zip(existing["title"], existing["artist"])) if not existing.empty else set()
    todo = [(r["title"], r["artist"]) for _, r in songs.iterrows() if (r["title"], r["artist"]) not in done]

    print(f"Fetching Last.fm for {len(todo)} songs ({WORKERS} concurrent)...")
    rows = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_track, title, artist): (title, artist) for title, artist in todo}
        for i, future in enumerate(as_completed(futures), 1):
            result = future.result()
            rows.append(result)
            if i % 100 == 0:
                print(f"  {i}/{len(todo)} — latest: {result['title']} ({result['playcount']:,} plays)")

    df = pd.DataFrame(rows)
    combined = pd.concat([existing, df], ignore_index=True) if not existing.empty else df
    combined = combined.drop_duplicates(subset=["title", "artist"])
    combined.to_csv(OUTPUT, index=False)

    found = combined[combined["playcount"] > 0]
    print(f"\nSaved {len(combined)} songs ({len(found)} with Last.fm data)")
    print("\nTop 10 by playcount:")
    print(found.nlargest(10, "playcount")[["title", "artist", "playcount"]].to_string(index=False))


if __name__ == "__main__":
    fetch_all()
