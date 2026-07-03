"""
Resolves album art for each song via Spotify's public oEmbed endpoint
(https://open.spotify.com/oembed?url=<track_url>) — the same unauthenticated
endpoint Slack/Discord/Twitter use to render link-preview cards. No app
credentials, no OAuth, and it isn't part of the Web API's per-app quota (the
Web API's dev-mode quota is what got this app rate-limited for 24 hours
before — see fetch_artist.py), so this can run at a normal pace without that
risk. Reads track URLs from the already-resolved data/spotify_links.csv — no
title/artist re-matching needed, that ambiguity is already solved there.

oEmbed's thumbnail_url is 300x300 — the same "medium" size the Web API's
images[1] already gave us, just under a different name.

Output: data/album_art.csv  (title, artist, album_art_url)

Progress is saved every 25 fetches and on any interruption, so a re-run only
fetches what's still missing. Consumed by export_csv.py, which merges it into
music_index_full.csv so downstream apps (Versed) never call Spotify for art
at runtime.
"""

import os
import time

import pandas as pd
import requests

BASE = os.path.dirname(__file__)
LINKS = os.path.join(BASE, "../data/spotify_links.csv")
OUTPUT = os.path.join(BASE, "../data/album_art.csv")

OEMBED_URL = "https://open.spotify.com/oembed"
REQUEST_DELAY = 0.15  # no documented limit on oEmbed, but stay a polite scraper
SAVE_EVERY = 25
TIMEOUT = 10


def _fetch_thumbnail(track_url):
    """Returns (thumbnail_url, retry_after_delay_or_None)."""
    try:
        resp = requests.get(OEMBED_URL, params={"url": track_url}, timeout=TIMEOUT)
        if resp.status_code == 200:
            return resp.json().get("thumbnail_url", ""), None
        if resp.status_code == 429:
            return "", float(resp.headers.get("Retry-After", 5))
        return "", None  # 404/other: no art for this track, not a retry case
    except requests.RequestException:
        return "", None


def fetch_all():
    if not os.path.exists(LINKS):
        print("ERROR: data/spotify_links.csv not found. Run fetch_spotify_links.py first.")
        return

    links = pd.read_csv(LINKS)
    links = links[links["spotify_url"].notna() & (links["spotify_url"] != "")]

    rows = []
    done_keys = set()
    if os.path.exists(OUTPUT):
        done = pd.read_csv(OUTPUT)
        rows = done.to_dict("records")
        done_keys = set(zip(done["title"], done["artist"]))

    todo = links[~links.apply(lambda r: (r["title"], r["artist"]) in done_keys, axis=1)]
    if todo.empty:
        print(f"Nothing to fetch — {len(rows)} songs already cached in {OUTPUT}")
        return

    print(f"Fetching art for {len(todo)} songs ({len(rows)} already cached)...", flush=True)
    fetched = 0
    try:
        for _, row in todo.iterrows():
            url, retry_after = _fetch_thumbnail(row["spotify_url"])
            if retry_after is not None:
                print(f"  Rate limited — sleeping {retry_after:.0f}s")
                time.sleep(retry_after)
                url, retry_after = _fetch_thumbnail(row["spotify_url"])

            rows.append({"title": row["title"], "artist": row["artist"], "album_art_url": url})
            fetched += 1
            if fetched % SAVE_EVERY == 0:
                pd.DataFrame(rows).to_csv(OUTPUT, index=False)
                print(f"  ...{fetched}/{len(todo)}", flush=True)
            time.sleep(REQUEST_DELAY)
    finally:
        pd.DataFrame(rows).to_csv(OUTPUT, index=False)

    found = sum(1 for r in rows if r.get("album_art_url"))
    print(f"Wrote {OUTPUT}: {len(rows)} songs, {found} with art")


if __name__ == "__main__":
    fetch_all()
