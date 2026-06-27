"""
Aggregates raw data from Billboard, Spotify Charts, and Last.fm into a
composite popularity score per song.

Run with --songs-only to just emit data/songs.csv (needed before fetch_lastfm.py).
Run normally to compute final scores and write data/scores.csv.
"""

import pandas as pd
import numpy as np
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import WEIGHTS, BILLBOARD_MAX_WEEKS, SPOTIFY_CHARTS_MAX_WEEKS, LASTFM_MAX_PLAYCOUNT

DATA = os.path.join(os.path.dirname(__file__), "../data")


def normalize_title(t):
    t = str(t).lower().strip()
    t = re.sub(r"\(.*?\)", "", t)   # remove parentheticals
    t = re.sub(r"\[.*?\]", "", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_artist(a):
    a = str(a).lower().strip()
    a = re.sub(r"\bfeat\..*", "", a)  # remove featuring
    a = re.sub(r"\bft\..*", "", a)
    a = re.sub(r"[^\w\s]", "", a)
    return re.sub(r"\s+", " ", a).strip()


def peak_score(peak):
    return (101 - np.clip(peak, 1, 100)) / 100


def weeks_score(weeks, max_weeks):
    return np.clip(weeks / max_weeks, 0, 1)


def load_billboard():
    path = os.path.join(DATA, "billboard_raw.csv")
    if not os.path.exists(path):
        print("WARNING: billboard_raw.csv not found — Billboard dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)

    agg = df.groupby(["key_title", "key_artist"]).agg(
        title=("title", "first"),
        artist=("artist", "first"),
        bb_peak=("peak_pos", "min"),
        bb_weeks=("weeks_on_chart", "max"),
        bb_appearances=("week_date", "count"),
    ).reset_index()

    agg["bb_score"] = (
        0.5 * peak_score(agg["bb_peak"]) +
        0.5 * weeks_score(agg["bb_weeks"], BILLBOARD_MAX_WEEKS)
    )
    return agg


def load_spotify_charts():
    path = os.path.join(DATA, "spotify_charts_raw.csv")
    if not os.path.exists(path):
        print("WARNING: spotify_charts_raw.csv not found — Spotify Charts dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    # Spotify Charts CSV columns vary by year; normalise
    df.columns = [c.lower().strip() for c in df.columns]
    title_col = next((c for c in df.columns if "track" in c or "title" in c), None)
    artist_col = next((c for c in df.columns if "artist" in c), None)
    rank_col = next((c for c in df.columns if "rank" in c or "position" in c), None)
    streams_col = next((c for c in df.columns if "stream" in c), None)

    if not title_col or not artist_col:
        print("WARNING: Could not parse Spotify Charts CSV columns")
        return pd.DataFrame()

    df = df.rename(columns={title_col: "title", artist_col: "artist"})
    if rank_col:
        df = df.rename(columns={rank_col: "rank"})
    if streams_col:
        df = df.rename(columns={streams_col: "streams"})

    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)

    agg_dict = {
        "title": ("title", "first"),
        "artist": ("artist", "first"),
        "sp_appearances": ("week_date", "count"),
    }
    if "rank" in df.columns:
        agg_dict["sp_peak"] = ("rank", "min")
    if "streams" in df.columns:
        df["streams"] = pd.to_numeric(df["streams"], errors="coerce").fillna(0)
        agg_dict["sp_total_streams"] = ("streams", "sum")

    agg = df.groupby(["key_title", "key_artist"]).agg(**agg_dict).reset_index()

    if "sp_peak" in agg.columns:
        peak_s = peak_score(agg["sp_peak"])
    else:
        peak_s = pd.Series(0.5, index=agg.index)

    weeks_s = weeks_score(agg["sp_appearances"], SPOTIFY_CHARTS_MAX_WEEKS)
    agg["sp_score"] = 0.5 * peak_s + 0.5 * weeks_s
    return agg


def load_lastfm():
    path = os.path.join(DATA, "lastfm_raw.csv")
    if not os.path.exists(path):
        print("WARNING: lastfm_raw.csv not found — Last.fm dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)
    df["lfm_score"] = np.clip(df["playcount"] / LASTFM_MAX_PLAYCOUNT, 0, 1)
    return df[["key_title", "key_artist", "playcount", "listeners", "lfm_score"]]


def compute_scores(songs_only=False):
    bb = load_billboard()
    sp = load_spotify_charts()
    lfm = load_lastfm()

    # Build master song list from all available sources
    dfs = []
    if not bb.empty:
        dfs.append(bb[["key_title", "key_artist", "title", "artist"]])
    if not sp.empty:
        dfs.append(sp[["key_title", "key_artist", "title", "artist"]])

    if not dfs:
        print("ERROR: No source data found. Run the fetchers first.")
        return

    songs = pd.concat(dfs).drop_duplicates(subset=["key_title", "key_artist"]).reset_index(drop=True)

    if songs_only:
        out = os.path.join(DATA, "songs.csv")
        songs[["title", "artist"]].to_csv(out, index=False)
        print(f"Wrote {len(songs)} unique songs to {out}")
        return

    # Merge all dimensions
    merged = songs
    if not bb.empty:
        merged = merged.merge(
            bb[["key_title", "key_artist", "bb_score", "bb_peak", "bb_weeks"]],
            on=["key_title", "key_artist"], how="left"
        )
    if not sp.empty:
        sp_cols = ["key_title", "key_artist", "sp_score", "sp_appearances"]
        if "sp_total_streams" in sp.columns:
            sp_cols.append("sp_total_streams")
        merged = merged.merge(sp[sp_cols], on=["key_title", "key_artist"], how="left")
    if not lfm.empty:
        merged = merged.merge(lfm, on=["key_title", "key_artist"], how="left")

    # Compute weighted score, adjusting for missing dimensions
    w = WEIGHTS.copy()
    available = {
        "billboard": "bb_score" in merged.columns,
        "spotify_charts": "sp_score" in merged.columns,
        "lastfm": "lfm_score" in merged.columns,
    }

    merged["final_score"] = 0.0
    for dim, col in [("billboard", "bb_score"), ("spotify_charts", "sp_score"), ("lastfm", "lfm_score")]:
        if available[dim]:
            # For songs missing this dimension's data, redistribute its weight
            has_data = merged[col].notna()
            merged.loc[has_data, "final_score"] += w[dim] * merged.loc[has_data, col]

    # Normalize to 0–100
    max_score = merged["final_score"].max()
    if max_score > 0:
        merged["final_score"] = (merged["final_score"] / max_score * 100).round(2)

    merged = merged.sort_values("final_score", ascending=False).reset_index(drop=True)
    merged.index += 1  # 1-based rank

    out = os.path.join(DATA, "scores.csv")
    merged.to_csv(out)
    print(f"Wrote {len(merged)} scored songs to {out}")
    return merged


if __name__ == "__main__":
    songs_only = "--songs-only" in sys.argv
    compute_scores(songs_only=songs_only)
