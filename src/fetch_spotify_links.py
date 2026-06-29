"""
Fetches Spotify track URLs for the top N scored songs.
Output: data/spotify_links.csv  (title, artist, spotify_url)

Strategy (in order):
  1. Match against local top_10000_1950-now.csv by title + primary artist
     (no API calls, covers ~75% of top 1000)
  2. For songs not matched, fall back to Spotify search API
     (requires SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET in .env)

Pass --force to ignore the existing cache and re-match everything.
"""

import re
import unicodedata
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import pandas as pd
import time
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, TOP_N

SCORES  = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
OUTPUT  = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")
CSV10K  = os.path.join(os.path.dirname(__file__), "../data/top_10000_1950-now.csv")

_FEAT_RE = re.compile(r'\s+(?:featuring|feat\.?|ft\.?)\s+.*$', re.IGNORECASE)


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def _nd(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"\(.*?\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _primary(a):
    a = _nd(a)
    for sep in [" featuring ", " feat ", " ft ", " with ", " x ", " and "]:
        if sep in a:
            a = a.split(sep)[0]
    return a.split(",")[0].strip()


# ---------------------------------------------------------------------------
# Strategy 1: match from local CSV
# ---------------------------------------------------------------------------

def _build_csv_lookup():
    if not os.path.exists(CSV10K):
        return None, None
    csv = pd.read_csv(CSV10K, usecols=["Track URI", "Track Name", "Artist Name(s)"])
    csv = csv.rename(columns={"Track URI": "uri", "Track Name": "title", "Artist Name(s)": "artist"})
    csv["url"] = csv["uri"].str.replace("spotify:track:", "https://open.spotify.com/track/", regex=False)
    csv["kt"]  = csv["title"].map(_nd)
    csv["kp"]  = csv["artist"].map(_primary)
    by_both  = csv.drop_duplicates(subset=["kt", "kp"]).set_index(["kt", "kp"])["url"]
    by_title = csv.drop_duplicates(subset=["kt"]).set_index("kt")["url"]
    return by_both, by_title


def _csv_lookup(by_both, by_title, title, artist):
    kt = _nd(title)
    kp = _primary(artist)
    key = (kt, kp)
    if key in by_both.index:
        return by_both[key]
    if kt in by_title.index:
        return by_title[kt]
    return None


# ---------------------------------------------------------------------------
# Strategy 2: Spotify search API
# ---------------------------------------------------------------------------

def _main_artist(artist):
    return _FEAT_RE.sub("", artist).strip()


def _artist_matches(track, main_artist):
    main_lower = main_artist.lower()
    for a in track["artists"]:
        name = a["name"].lower()
        if main_lower in name or name in main_lower:
            return True
    return False


def _best(items, main_artist):
    matched = [t for t in items if _artist_matches(t, main_artist)]
    pool = matched if matched else items
    return max(pool, key=lambda t: t["popularity"])


def _api_lookup(sp, title, artist):
    main = _main_artist(artist)
    queries = [f'track:"{title}" artist:"{main}"']
    if main != artist:
        queries.append(f'track:"{title}" artist:"{artist}"')
    queries += [f"{title} {main}", f"{title} {artist}"]

    for q in queries:
        try:
            results = sp.search(q=q, type="track", limit=5)
            items = results["tracks"]["items"]
            if items:
                return _best(items, main)["external_urls"]["spotify"]
        except spotipy.exceptions.SpotifyException as e:
            if e.http_status == 429:
                retry_after = int(e.headers.get("Retry-After", 60)) if e.headers else 60
                print(f"\nRate limited — quota exceeded (retry after {retry_after}s). Saving progress and exiting.", flush=True)
                sys.exit(1)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _save(existing, new_rows):
    df = pd.DataFrame(new_rows)
    combined = pd.concat([existing, df], ignore_index=True) if not existing.empty else df
    combined = combined.drop_duplicates(subset=["title", "artist"])
    combined.to_csv(OUTPUT, index=False)


def fetch_all(force=False):
    if not os.path.exists(SCORES):
        print("ERROR: scores.csv not found. Run score.py first.")
        return

    scores   = pd.read_csv(SCORES, index_col=0).head(TOP_N)
    existing = pd.DataFrame() if (force or not os.path.exists(OUTPUT)) else pd.read_csv(OUTPUT)
    done     = set(zip(existing["title"], existing["artist"])) if not existing.empty else set()
    todo     = [(r["title"], r["artist"]) for _, r in scores.iterrows()
                if (r["title"], r["artist"]) not in done]

    print(f"Looking up {len(todo)} songs{' (full refresh)' if force else ''}...", flush=True)

    # --- Pass 1: local CSV (free, fast) ---
    by_both, by_title = _build_csv_lookup()
    csv_rows, api_todo = [], []
    if by_both is not None:
        for title, artist in todo:
            url = _csv_lookup(by_both, by_title, title, artist)
            if url:
                csv_rows.append({"title": title, "artist": artist, "spotify_url": url})
            else:
                api_todo.append((title, artist))
        print(f"  CSV match: {len(csv_rows)} found, {len(api_todo)} need API", flush=True)
        _save(existing, csv_rows)
    else:
        api_todo = todo

    # --- Pass 2: Spotify search API for remainder ---
    if not api_todo:
        print("No API calls needed.", flush=True)
    else:
        print(f"  Fetching {len(api_todo)} remaining via Spotify API...", flush=True)
        sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID,
            client_secret=SPOTIFY_CLIENT_SECRET,
        ))
        existing2 = pd.read_csv(OUTPUT) if os.path.exists(OUTPUT) else pd.DataFrame()
        new_rows  = []
        for i, (title, artist) in enumerate(api_todo, 1):
            url = _api_lookup(sp, title, artist)
            new_rows.append({"title": title, "artist": artist, "spotify_url": url or ""})
            if i % 20 == 0:
                print(f"  API: {i}/{len(api_todo)}", flush=True)
            if i % 50 == 0:
                _save(existing2, new_rows)
            time.sleep(0.1)
        _save(existing2, new_rows)

    combined = pd.read_csv(OUTPUT)
    found = (combined["spotify_url"] != "").sum()
    print(f"Done. {found}/{len(combined)} songs have links.", flush=True)


if __name__ == "__main__":
    fetch_all(force="--force" in sys.argv)
