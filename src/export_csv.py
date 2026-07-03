"""
Merges the scored ranking (data/scores.csv) with cached Spotify track URLs
(data/spotify_links.csv) and cached album art (data/album_art.csv) into a
single tidy CSV: output/music_index_full.csv.

Run after score.py (and optionally fetch_spotify_links.py / fetch_album_art.py)
to refresh the file. Songs above TOP_N simply have a blank spotify_url until
links are fetched for them; songs without cached art get a blank
album_art_url — the consuming app (Versed) fetches live for anything missing
here rather than treating a blank as permanent.
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.utils import artist_csv

BASE = os.path.dirname(__file__)
SCORES = os.path.join(BASE, "../data/scores.csv")
LINKS = os.path.join(BASE, "../data/spotify_links.csv")
ALBUM_ART = os.path.join(BASE, "../data/album_art.csv")
OUTPUT = os.path.join(BASE, "../output/music_index_full.csv")

# Output column order. Drop "decade" here if you want a leaner file — it's just
# (year // 10) * 10, derivable from "year" anytime.
# "year" is the song's first Billboard Hot 100 chart year (used for era
# normalization); "release_year" is the true release year from Spotify
# metadata where available — they can differ for late-charting singles.
# spotify_url must stay the last column before album_art_url — Versed's CSV
# parser reads the Spotify track ID out of a fixed column index.
COLUMNS = [
    "title", "artist", "year", "release_year", "decade", "duration_ms", "tempo",
    "bb_peak", "bb_chart_weeks", "bb_score",
    "spotify_streams", "sp_score",
    "youtube_views", "yt_score",
    "itunes_total", "itunes_score",
    "apple_total", "apple_score",
    "sales_peak", "sales_chart_weeks", "sales_score",
    "riaa_units", "riaa_score",
    "radio_peak", "radio_chart_weeks", "radio_score",
    "final_score", "spotify_url", "album_art_url",
]


def main():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return

    scores = pd.read_csv(SCORES, index_col=0)
    scores.index.name = "rank"

    if os.path.exists(LINKS):
        links = pd.read_csv(LINKS)
        links = links[links["spotify_url"].notna() & (links["spotify_url"] != "")]
        link_cols = [c for c in ["spotify_url", "duration_ms", "release_year", "tempo"] if c in links.columns]
        merged = scores.merge(
            links[["title", "artist"] + link_cols],
            on=["title", "artist"], how="left", validate="m:1",
        )
        merged.index = scores.index  # merge resets the index; restore the rank
    else:
        print("NOTE: data/spotify_links.csv not found — spotify_url left blank.")
        merged = scores.copy()
        merged["spotify_url"] = pd.NA

    if os.path.exists(ALBUM_ART):
        art = pd.read_csv(ALBUM_ART)
        art = art[art["album_art_url"].notna() & (art["album_art_url"] != "")]
        merged = merged.merge(
            art[["title", "artist", "album_art_url"]],
            on=["title", "artist"], how="left", validate="m:1",
        )
        merged.index = scores.index
    else:
        print("NOTE: data/album_art.csv not found — album_art_url left blank.")
        merged["album_art_url"] = pd.NA

    present = [c for c in COLUMNS if c in merged.columns]
    merged = merged[present]
    merged = merged.copy()
    merged["artist"] = merged["artist"].map(artist_csv)
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    merged.to_csv(OUTPUT)

    n_links = merged["spotify_url"].notna().sum()
    n_art = merged["album_art_url"].notna().sum()
    print(f"Wrote {OUTPUT}")
    print(f"  {len(merged)} songs, {n_links} with Spotify links, {n_art} with album art")


if __name__ == "__main__":
    main()
