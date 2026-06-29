"""
Searches Spotify for the top N scored songs and caches their track URLs.
Output: data/spotify_links.csv  (title, artist, spotify_url)

Pass --force to re-fetch all songs, ignoring the cache (useful after fixing
search logic or when existing links point to wrong tracks).
"""

import re
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

# Billboard uses "Artist Featuring Guest" — Spotify only knows "Artist".
_FEAT_RE = re.compile(r'\s+(?:featuring|feat\.?|ft\.?)\s+.*$', re.IGNORECASE)


def _main_artist(artist):
    """Return the primary artist name, dropping any 'Featuring ...' suffix."""
    return _FEAT_RE.sub("", artist).strip()


def _artist_matches(track, main_artist):
    """True if any of the track's credited artists resembles the main artist."""
    main_lower = main_artist.lower()
    for a in track["artists"]:
        name = a["name"].lower()
        if main_lower in name or name in main_lower:
            return True
    return False


def _best(items, main_artist):
    """
    From a list of candidate tracks pick the best one:
    1. Prefer tracks whose artist matches the expected main artist.
    2. Among those, prefer the highest Spotify popularity (original > cover/remix).
    """
    matched = [t for t in items if _artist_matches(t, main_artist)]
    pool = matched if matched else items
    return max(pool, key=lambda t: t["popularity"])


def get_spotify_url(sp, title, artist):
    main = _main_artist(artist)

    # Strategy 1: strict field filter with main artist (most precise)
    queries = [f'track:"{title}" artist:"{main}"']
    # Strategy 2: strict field filter with full Billboard artist (handles group names)
    if main != artist:
        queries.append(f'track:"{title}" artist:"{artist}"')
    # Strategy 3 & 4: broad keyword search
    queries += [f"{title} {main}", f"{title} {artist}"]

    for q in queries:
        try:
            results = sp.search(q=q, type="track", limit=5)
            items = results["tracks"]["items"]
            if items:
                track = _best(items, main)
                return track["external_urls"]["spotify"]
        except Exception:
            pass

    return None


def fetch_all(force=False):
    if not os.path.exists(SCORES):
        print("ERROR: scores.csv not found. Run score.py first.")
        return

    scores = pd.read_csv(SCORES, index_col=0).head(TOP_N)

    if force or not os.path.exists(OUTPUT):
        existing = pd.DataFrame()
    else:
        existing = pd.read_csv(OUTPUT)

    done = set(zip(existing["title"], existing["artist"])) if not existing.empty else set()

    sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET,
    ))

    rows = []
    todo = [(r["title"], r["artist"]) for _, r in scores.iterrows() if (r["title"], r["artist"]) not in done]
    print(f"Fetching Spotify links for {len(todo)} songs{' (full refresh)' if force else ''}...")

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
    fetch_all(force="--force" in sys.argv)
