"""
Resolves Spotify track URLs for scored songs from any Exportify-style
CSV files in data/ (files containing Track URI + Track Name + Artist Name(s)).

Drop any Spotify playlist export into data/ and it is picked up automatically.
Matching: title + primary artist, then title-only fallback.
No API calls — instant and rate-limit-free.

Output: data/spotify_links.csv  (title, artist, spotify_url)
"""

import re
import unicodedata
import glob
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TOP_N

SCORES   = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
OUTPUT   = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")
DATA_DIR = os.path.join(os.path.dirname(__file__), "../data")


def _nd(s):
    s = "".join(c for c in unicodedata.normalize("NFD", str(s)) if unicodedata.category(c) != "Mn")
    s = s.lower().strip()
    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _primary(a):
    a = _nd(a)
    for sep in [" featuring ", " feat ", " ft ", " with ", " x ", " and "]:
        if sep in a:
            a = a.split(sep)[0]
    return a.split(",")[0].strip()


def _build_lookup():
    frames = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "*.csv"))):
        try:
            df = pd.read_csv(path, usecols=["Track URI", "Track Name", "Artist Name(s)"])
            df = df.rename(columns={"Track URI": "uri", "Track Name": "title", "Artist Name(s)": "artist"})
            frames.append(df)
        except Exception:
            pass

    if not frames:
        return None, None

    combined = pd.concat(frames, ignore_index=True)
    combined["url"] = combined["uri"].str.replace(
        "spotify:track:", "https://open.spotify.com/track/", regex=False
    )
    combined["kt"] = combined["title"].map(_nd)
    combined["kp"] = combined["artist"].map(_primary)
    print(f"  Loaded {len(combined):,} tracks from {len(frames)} CSV file(s)", flush=True)

    by_both  = combined.drop_duplicates(subset=["kt", "kp"]).set_index(["kt", "kp"])["url"]
    by_title = combined.drop_duplicates(subset=["kt"]).set_index("kt")["url"]
    return by_both, by_title


def fetch_all():
    if not os.path.exists(SCORES):
        print("ERROR: scores.csv not found. Run score.py first.")
        return

    scores = pd.read_csv(SCORES, index_col=0).head(TOP_N)
    by_both, by_title = _build_lookup()

    if by_both is None:
        print("ERROR: no Exportify-style CSVs found in data/.")
        return

    rows = []
    for _, row in scores.iterrows():
        kt  = _nd(row["title"])
        kp  = _primary(row["artist"])
        url = by_both.get((kt, kp)) or by_title.get(kt) or ""
        rows.append({"title": row["title"], "artist": row["artist"], "spotify_url": url})

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT, index=False)
    found = (df["spotify_url"] != "").sum()
    print(f"Matched {found}/{len(df)} songs. Saved to {OUTPUT}")


if __name__ == "__main__":
    fetch_all()
