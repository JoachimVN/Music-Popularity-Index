"""
Resolves Spotify track URLs (plus duration and release year) for scored songs
from any Exportify-style CSV files in data/ (files containing Track URI +
Track Name + Artist Name(s)).

Drop any Spotify playlist export into data/ and it is picked up automatically.
Matching: title + primary artist, then title-only fallback (only when the
title is unambiguous, i.e. every row with that title shares the same primary
artist — otherwise we'd risk matching e.g. "Golden" by Harry Styles to the
HUNTR/X version).
No API calls — instant and rate-limit-free.

Output: data/spotify_links.csv  (title, artist, spotify_url, duration_ms, release_year)
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
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r" - .*$", "", s)   # strip " - Remastered 2011", " - Live", etc.
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


# Split off collaborators on the *raw* string before _nd() strips the ","/";"
# separators Exportify uses for multi-artist credits (e.g. "Rihanna;Mikky Ekko"),
# otherwise the separator disappears and _primary() returns mangled garbage.
#
# Keyword separators (featuring/feat/ft/with) and punctuation are stripped
# first, greedily removing everything after them — only *then* do we check
# the ambiguous "x"/"&" case. Order matters: without it, "Lil Nas X
# Featuring Billy Ray Cyrus" would match "x" (it's followed by "Featuring...",
# which satisfies "real content follows") before the featuring-strip ever
# runs, wrongly cutting the "X" off his stage name. Stripping "Featuring..."
# first removes that trailing content, so by the time the x/& check runs,
# "Lil Nas X" has nothing after it and is correctly left alone.
_KEYWORD_SEP_RE = re.compile(r"\b(?:featuring|feat\.?|ft\.?|with)\b.*", re.IGNORECASE)
_PUNCT_SEP_RE = re.compile(r"[;,:].*")
_AMBIGUOUS_SEP_RE = re.compile(r"\b(?:and|x)\b(?=\s*\S).*|&.*", re.IGNORECASE)


def _primary(a):
    a = str(a)
    a = _KEYWORD_SEP_RE.sub("", a, count=1)
    a = _PUNCT_SEP_RE.sub("", a, count=1)
    a = _AMBIGUOUS_SEP_RE.sub("", a, count=1)
    return _nd(a)


# Column names vary slightly between Exportify export types
# (single-playlist exports vs. the "Track Duration"/"Album Release Date"
# style used by the top_10000_* full-library exports).
_COLUMN_SYNONYMS = {
    "uri":          ["Track URI"],
    "title":        ["Track Name"],
    "artist":       ["Artist Name(s)"],
    "duration_ms":  ["Duration (ms)", "Track Duration (ms)"],
    "release_date": ["Release Date", "Album Release Date"],
}


def _load_exportify_file(path):
    """Load one CSV as a (uri, title, artist, duration_ms, release_date) frame,
    or None if it doesn't look like an Exportify export."""
    try:
        header = pd.read_csv(path, nrows=0).columns
        usecols, rename = [], {}
        for canonical, synonyms in _COLUMN_SYNONYMS.items():
            col = next((c for c in synonyms if c in header), None)
            if col:
                usecols.append(col)
                rename[col] = canonical

        if not {"uri", "title", "artist"} <= set(rename.values()):
            return None

        df = pd.read_csv(path, usecols=usecols).rename(columns=rename)
        for missing in ("duration_ms", "release_date"):
            if missing not in df.columns:
                df[missing] = pd.NA
        return df
    except Exception:
        return None


def _build_lookup():
    paths = sorted(glob.glob(os.path.join(DATA_DIR, "*.csv")))
    frames = [f for f in (_load_exportify_file(p) for p in paths) if f is not None]

    if not frames:
        return None, None

    combined = pd.concat(frames, ignore_index=True)
    combined["url"] = combined["uri"].str.replace(
        "spotify:track:", "https://open.spotify.com/track/", regex=False
    )
    combined["duration_ms"] = pd.to_numeric(combined["duration_ms"], errors="coerce")
    combined["release_year"] = pd.to_datetime(
        combined["release_date"], errors="coerce"
    ).dt.year
    # Some Exportify exports only have a bare year ("1999") which to_datetime
    # can fail to parse; fall back to pulling the first 4-digit run.
    missing = combined["release_year"].isna()
    combined.loc[missing, "release_year"] = pd.to_numeric(
        combined.loc[missing, "release_date"].astype(str).str.extract(r"(\d{4})")[0],
        errors="coerce",
    )

    combined["kt"] = combined["title"].map(_nd)
    combined["kp"] = combined["artist"].map(_primary)
    print(f"  Loaded {len(combined):,} tracks from {len(frames)} CSV file(s)", flush=True)

    meta_cols = ["url", "duration_ms", "release_year"]
    by_both = combined.drop_duplicates(subset=["kt", "kp"]).set_index(["kt", "kp"])[meta_cols]

    # Title-only fallback: only keep titles where every row shares the same
    # primary artist, so we never guess between two different songs that
    # happen to share a title (e.g. "Golden" by Harry Styles vs. HUNTR/X).
    unambiguous_titles = combined.groupby("kt")["kp"].nunique()
    unambiguous_titles = unambiguous_titles[unambiguous_titles == 1].index
    by_title = (
        combined[combined["kt"].isin(unambiguous_titles)]
        .drop_duplicates(subset=["kt"])
        .set_index("kt")[meta_cols]
    )
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
        kt = _nd(row["title"])
        kp = _primary(row["artist"])
        if (kt, kp) in by_both.index:
            match = by_both.loc[(kt, kp)]
        elif kt in by_title.index:
            match = by_title.loc[kt]
        else:
            match = None

        rows.append({
            "title": row["title"],
            "artist": row["artist"],
            "spotify_url": match["url"] if match is not None else "",
            "duration_ms": match["duration_ms"] if match is not None else pd.NA,
            "release_year": match["release_year"] if match is not None else pd.NA,
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUTPUT, index=False)
    found = (df["spotify_url"] != "").sum()
    print(f"Matched {found}/{len(df)} songs. Saved to {OUTPUT}")


if __name__ == "__main__":
    fetch_all()
