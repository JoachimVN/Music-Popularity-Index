"""
Builds a full per-song CSV for one artist: kworb all-time Spotify streams
joined with Spotify Web API track metadata (release date, duration, ISRC, ...).

Usage:
    python src/fetch_artist.py <spotify-artist-id-or-name>

    python src/fetch_artist.py 1Xyo4u8uXC1ZmMpatF05PJ   # The Weeknd, by ID
    python src/fetch_artist.py "The Weeknd"              # resolved via search

Output: output/artist_<slug>.csv

Why this shape, not Exportify: kworb's per-artist page
(kworb.net/spotify/artist/<id>_songs.html) links every song straight to its
Spotify track ID, so streams and metadata join on that ID directly — no
playlist-hunting, no Exportify export, no title-matching.

Why not the batch endpoints: this app's Spotify Web API access is
Development Mode. `GET /v1/tracks?ids=...` (batch) and `GET
/v1/audio-features` both 403 under dev-mode quota, so tempo isn't fetchable
at all here, and metadata has to come from the single-track endpoint
(`GET /v1/tracks/{id}`), which *is* open. A prior run that hit the batch
endpoints hard got the whole app rate-limited for 24 hours, so this fetches
one track at a time with a deliberate delay between requests, and caches
progress to disk so a re-run (or a run that does hit a 429) doesn't re-fetch
anything already fetched.
"""

import os
import re
import sys
import time
import unicodedata

import pandas as pd
import requests
from bs4 import BeautifulSoup
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET

BASE = os.path.dirname(__file__)
CACHE_DIR = os.path.join(BASE, "../data/artist_cache")
OUTPUT_DIR = os.path.join(BASE, "../output")

REQUEST_DELAY = 0.3  # seconds between single-track calls — keep this app well under dev-mode quota
KWORB_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _slug(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^\w]+", "_", s).strip("_").lower()
    return s


def _resolve_artist_id(sp, query):
    if re.fullmatch(r"[A-Za-z0-9]{22}", query):
        return query, sp.artist(query)["name"]
    results = sp.search(q=query, type="artist", limit=1)
    items = results["artists"]["items"]
    if not items:
        raise SystemExit(f"No Spotify artist found for {query!r}")
    return items[0]["id"], items[0]["name"]


def _scrape_kworb(artist_id):
    url = f"https://kworb.net/spotify/artist/{artist_id}_songs.html"
    print(f"Fetching {url} ...")
    resp = requests.get(url, headers=KWORB_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    table = soup.find("table", class_="addpos")
    rows = table.find("tbody").find_all("tr")

    records = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 3:
            continue
        link = cols[0].find("a")
        if link is None:
            continue
        track_id = link["href"].rstrip("/").rsplit("/", 1)[-1]
        streams = int(cols[1].get_text(strip=True).replace(",", ""))
        records.append({"track_id": track_id, "spotify_streams": streams})

    print(f"  {len(records)} songs on kworb")
    return pd.DataFrame(records)


def _load_cache(cache_path):
    if os.path.exists(cache_path):
        return pd.read_csv(cache_path, index_col="track_id")
    return pd.DataFrame().rename_axis("track_id")


def _fetch_track_metadata(sp, track_id):
    try:
        t = sp.track(track_id, market="US")
    except SpotifyException as e:
        if e.http_status == 429:
            retry_after = int((e.headers or {}).get("Retry-After", 5))
            print(f"  429 rate-limited — waiting {retry_after}s then retrying once...")
            time.sleep(retry_after)
            t = sp.track(track_id, market="US")  # let a second failure propagate and abort the run
        else:
            raise

    # release_date precision varies (year/month/day) — first 4 digits is always the year.
    release_year = int(t["album"]["release_date"][:4])

    return {
        "title": t["name"],
        "artist": ";".join(a["name"] for a in t["artists"]),
        "release_year": release_year,
        "duration_ms": t["duration_ms"],
        "spotify_url": t["external_urls"]["spotify"],
    }


def _fetch_all_metadata(sp, track_ids, cache_path, cache):
    missing = [tid for tid in track_ids if tid not in cache.index]
    if not missing:
        print("  All track metadata already cached.")
        return cache

    print(f"  Fetching metadata for {len(missing)} tracks (~{len(missing) * REQUEST_DELAY:.0f}s, "
          f"one request at a time to stay well under this app's dev-mode rate limit)...")
    rows = {}
    for i, tid in enumerate(missing, 1):
        try:
            rows[tid] = _fetch_track_metadata(sp, tid)
        except SpotifyException as e:
            print(f"  ABORTED after {i - 1}/{len(missing)} — {e}")
            print("  Progress saved; re-run the same command to resume from here.")
            break
        if i % 25 == 0 or i == len(missing):
            print(f"    {i}/{len(missing)}")
        time.sleep(REQUEST_DELAY)

    if rows:
        new_cache = pd.DataFrame.from_dict(rows, orient="index").rename_axis("track_id")
        cache = pd.concat([cache, new_cache])
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        cache.to_csv(cache_path)
    return cache


def fetch_artist(query):
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET
        ),
        requests_timeout=10,
        retries=0,  # handle 429s ourselves — spotipy's default backoff can compound fast across many single-track calls
    )

    artist_id, artist_name = _resolve_artist_id(sp, query)
    print(f"Artist: {artist_name} ({artist_id})")

    kworb = _scrape_kworb(artist_id)
    if kworb.empty:
        print("No songs found on kworb for this artist — nothing to do.")
        return

    slug = _slug(artist_name)
    cache_path = os.path.join(CACHE_DIR, f"{slug}.csv")
    cache = _load_cache(cache_path)
    cache = _fetch_all_metadata(sp, kworb["track_id"].tolist(), cache_path, cache)

    merged = kworb.merge(cache, on="track_id", how="left")
    merged = merged.sort_values("spotify_streams", ascending=False).reset_index(drop=True)
    merged.index += 1
    merged.index.name = "rank"

    merged["decade"] = (merged["release_year"] // 10) * 10

    # Tempo isn't fetchable via the API under this app's dev-mode access
    # (audio-features 403s) — left blank rather than silently omitted, so
    # it's visible as a gap to fill by hand if you ever need it.
    merged["tempo"] = pd.NA

    # Same column set/order as output/music_index_full.csv, minus the
    # dimensions this script has no data for (Billboard, YouTube, iTunes,
    # Apple Music, sales, RIAA, radio, composite score).
    columns = ["title", "artist", "release_year", "decade", "duration_ms", "tempo", "spotify_streams", "spotify_url"]
    merged = merged[[c for c in columns if c in merged.columns]]

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_DIR, f"artist_{slug}.csv")
    merged.to_csv(out_path)
    n_meta = merged["title"].notna().sum()
    print(f"\nWrote {out_path}")
    print(f"  {len(merged)} songs, {n_meta} with Spotify metadata")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python src/fetch_artist.py <spotify-artist-id-or-name>")
    fetch_artist(" ".join(sys.argv[1:]))
