"""
Merges the scored ranking (data/scores.csv) with cached Spotify track URLs
(data/spotify_links.csv) into a single tidy CSV: output/music_index_full.csv.

Run after score.py (and optionally fetch_spotify_links.py) to refresh the file.
Songs above TOP_N simply have a blank spotify_url until links are fetched for them.
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = os.path.dirname(__file__)
SCORES = os.path.join(BASE, "../data/scores.csv")
LINKS = os.path.join(BASE, "../data/spotify_links.csv")
OUTPUT = os.path.join(BASE, "../output/music_index_full.csv")

# Output column order. Drop "decade" here if you want a leaner file — it's just
# (year // 10) * 10, derivable from "year" anytime.
COLUMNS = [
    "title", "artist", "year", "decade", "bb_peak", "bb_chart_weeks",
    "spotify_streams", "bb_score", "sp_score", "final_score", "spotify_url",
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
        merged = scores.merge(
            links[["title", "artist", "spotify_url"]],
            on=["title", "artist"], how="left",
        )
        merged.index = scores.index  # merge resets the index; restore the rank
    else:
        print("NOTE: data/spotify_links.csv not found — spotify_url left blank.")
        merged = scores.copy()
        merged["spotify_url"] = pd.NA

    merged = merged[COLUMNS]
    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    merged.to_csv(OUTPUT)

    n_links = merged["spotify_url"].notna().sum()
    print(f"Wrote {OUTPUT}")
    print(f"  {len(merged)} songs, {n_links} with Spotify links")


if __name__ == "__main__":
    main()
