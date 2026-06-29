"""
Resolves Spotify track URLs for scored songs from the local
top_10000_1950-now.csv (which contains Track URIs).

Matching: title + primary artist, then title-only fallback.
No API calls — instant and rate-limit-free.

Output: data/spotify_links.csv  (title, artist, spotify_url)
"""

import re
import unicodedata
import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TOP_N

SCORES = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
OUTPUT = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")
CSV10K = os.path.join(os.path.dirname(__file__), "../data/top_10000_1950-now.csv")


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


def fetch_all():
    if not os.path.exists(SCORES):
        print("ERROR: scores.csv not found. Run score.py first.")
        return
    if not os.path.exists(CSV10K):
        print("ERROR: top_10000_1950-now.csv not found in data/.")
        return

    scores = pd.read_csv(SCORES, index_col=0).head(TOP_N)

    csv = pd.read_csv(CSV10K, usecols=["Track URI", "Track Name", "Artist Name(s)"])
    csv = csv.rename(columns={"Track URI": "uri", "Track Name": "title", "Artist Name(s)": "artist"})
    csv["url"] = csv["uri"].str.replace("spotify:track:", "https://open.spotify.com/track/", regex=False)
    csv["kt"]  = csv["title"].map(_nd)
    csv["kp"]  = csv["artist"].map(_primary)

    by_both  = csv.drop_duplicates(subset=["kt", "kp"]).set_index(["kt", "kp"])["url"]
    by_title = csv.drop_duplicates(subset=["kt"]).set_index("kt")["url"]

    rows = []
    for _, row in scores.iterrows():
        kt = _nd(row["title"])
        kp = _primary(row["artist"])
        url = by_both.get((kt, kp)) or by_title.get(kt) or ""
        rows.append({"title": row["title"], "artist": row["artist"], "spotify_url": url})

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT, index=False)
    found = (df["spotify_url"] != "").sum()
    print(f"Matched {found}/{len(df)} songs. Saved to {OUTPUT}")


if __name__ == "__main__":
    fetch_all()
