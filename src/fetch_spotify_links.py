"""
Searches Spotify for the top N scored songs and caches their track URLs.
Output: data/spotify_links.csv  (title, artist, spotify_url)
"""

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, TOP_N

SCORES = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
OUTPUT = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")


def get_spotify_url(sp, title, artist):
    query = f'track:"{title}" artist:"{artist}"'
    try:
        results = sp.search(q=query, type="track", limit=1)
        items = results["tracks"]["items"]
        if items:
            return items[0]["external_urls"]["spotify"]
    except Exception:
        pass
    # Fallback: broader search without field filters
    try:
        results = sp.search(q=f"{title} {artist}", type="track", limit=1)
        items = results["tracks"]["items"]
        if items:
            return items[0]["external_urls"]["spotify"]
    except Exception:
        pass
    return None


def fetch_all():
    if not os.path.exists(SCORES):
        print("ERROR: scores.csv not found. Run score.py first.")
        return

    scores = pd.read_csv(SCORES, index_col=0).head(TOP_N)
    existing = pd.read_csv(OUTPUT) if os.path.exists(OUTPUT) else pd.DataFrame()
    done = set(zip(existing["title"], existing["artist"])) if not existing.empty else set()

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    ))

    rows = []
    todo = [(r["title"], r["artist"]) for _, r in scores.iterrows() if (r["title"], r["artist"]) not in done]
    print(f"Fetching Spotify links for {len(todo)} songs...")

    for i, (title, artist) in enumerate(todo, 1):
        url = get_spotify_url(sp, title, artist)
        rows.append({"title": title, "artist": artist, "spotify_url": url or ""})
        if i % 20 == 0:
            print(f"  {i}/{len(todo)}")
        time.sleep(0.1)

    df = pd.DataFrame(rows)
    combined = pd.concat([existing, df], ignore_index=True) if not existing.empty else df
    combined = combined.drop_duplicates(subset=["title", "artist"])
    combined.to_csv(OUTPUT, index=False)

    found = combined[combined["spotify_url"] != ""]
    print(f"Done. {len(found)}/{len(combined)} songs matched on Spotify.")


if __name__ == "__main__":
    fetch_all()
