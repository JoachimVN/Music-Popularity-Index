"""
Aggregates raw data from Billboard, kworb (Spotify streams), and Last.fm into
a composite popularity score per song.

Run with --songs-only to emit data/songs.csv (needed before fetch_lastfm.py).
Run normally to compute final scores and write data/scores.csv.
"""

import pandas as pd
import numpy as np
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import WEIGHTS

DATA = os.path.join(os.path.dirname(__file__), "../data")


def normalize_title(t):
    t = str(t).lower().strip()
    t = re.sub(r"\([^\)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_artist(a):
    a = str(a).lower().strip()
    a = re.sub(r"\bfeat\..*", "", a)
    a = re.sub(r"\bft\..*", "", a)
    a = re.sub(r"/.*", "", a)  # "A/B Band" → "A"; AC/DC → "ac" in both sources, still matches
    a = re.sub(r"[^\w\s]", "", a)
    return re.sub(r"\s+", " ", a).strip()


def peak_score(peak):
    return (101 - np.clip(peak, 1, 100)) / 100


def weeks_score(weeks, max_weeks):
    return np.clip(weeks / max_weeks, 0, 1)


def load_billboard():
    path = os.path.join(DATA, "hot100.csv")
    if not os.path.exists(path):
        print("WARNING: hot100.csv not found — Billboard dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path, usecols=["1Date", "Song", "Artist", "Peak Position", "Weeks in Charts"])
    df = df.rename(columns={
        "1Date": "date",
        "Song": "title",
        "Artist": "artist",
        "Peak Position": "peak_pos",
        "Weeks in Charts": "weeks_on_chart",
    })
    df["peak_pos"] = pd.to_numeric(df["peak_pos"], errors="coerce")
    df["weeks_on_chart"] = pd.to_numeric(df["weeks_on_chart"], errors="coerce")
    df["year"] = pd.to_datetime(df["date"], errors="coerce").dt.year
    df["decade"] = (df["year"] // 10) * 10
    df = df.dropna(subset=["peak_pos", "weeks_on_chart", "year"])

    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)

    # Count distinct chart weeks per song from actual dataset rows.
    chart_weeks_count = df.groupby(["key_title", "key_artist"])["date"].nunique().rename("bb_chart_weeks")

    agg = df.groupby(["key_title", "key_artist"]).agg(
        title=("title", "first"),
        artist=("artist", "first"),
        bb_peak=("peak_pos", "min"),
        year=("year", "min"),
        decade=("decade", "first"),
    ).reset_index()

    agg = agg.join(chart_weeks_count, on=["key_title", "key_artist"])

    # Percentile rank within each decade — continuous, no ceiling, naturally era-normalised.
    # Peak: ascending=False so #1 → pct=1.0, #100 → pct≈0.
    # Weeks: ascending=True so more weeks → higher pct.
    agg["peak_pct"] = agg.groupby("decade")["bb_peak"].rank(ascending=False, pct=True)
    agg["weeks_pct"] = agg.groupby("decade")["bb_chart_weeks"].rank(ascending=True, pct=True)

    # 60% peak dominance, 40% chart longevity
    agg["bb_score"] = 0.6 * agg["peak_pct"] + 0.4 * agg["weeks_pct"]
    return agg


def load_kworb():
    path = os.path.join(DATA, "kworb_raw.csv")
    if not os.path.exists(path):
        print("WARNING: kworb_raw.csv not found — Spotify streams dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)
    # sp_score assigned after merge with Billboard (needs year for era normalisation)
    return df[["key_title", "key_artist", "title", "artist", "spotify_streams"]]


def _apply_weights(merged, available_dims):
    # No redistribution: songs missing a dimension simply don't earn those points.
    # Final normalization (divide by max) makes everything relative at the end.
    scores = pd.Series(0.0, index=merged.index)
    for dim, col in available_dims.items():
        scores += WEIGHTS[dim] * merged[col].fillna(0)
    return scores


def compute_scores(songs_only=False):
    bb = load_billboard()
    kworb = load_kworb()

    dfs = []
    if not bb.empty:
        dfs.append(bb[["key_title", "key_artist", "title", "artist"]])
    if not kworb.empty:
        dfs.append(kworb[["key_title", "key_artist", "title", "artist"]])

    if not dfs:
        print("ERROR: No source data found. Run the fetchers first.")
        return

    songs = pd.concat(dfs).drop_duplicates(subset=["key_title", "key_artist"]).reset_index(drop=True)

    if songs_only:
        out = os.path.join(DATA, "songs.csv")
        songs[["title", "artist"]].to_csv(out, index=False)
        print(f"Wrote {len(songs)} unique songs to {out}")
        return

    # Merge Billboard then Spotify
    merged = songs
    if not bb.empty:
        merged = merged.merge(
            bb[["key_title", "key_artist", "bb_score", "bb_peak", "bb_chart_weeks", "year"]],
            on=["key_title", "key_artist"], how="left"
        )
    if not kworb.empty:
        merged = merged.merge(
            kworb[["key_title", "key_artist", "spotify_streams"]],
            on=["key_title", "key_artist"], how="left"
        )

    # Era-normalise Spotify streams: percentile rank within release decade.
    # Songs missing a decade (kworb-only, no Billboard year) fall into a
    # shared "unknown" bucket and are ranked among themselves.
    if "spotify_streams" in merged.columns:
        merged["decade"] = ((merged["year"].fillna(0) // 10) * 10).astype(int)
        merged["sp_score"] = merged.groupby("decade")["spotify_streams"].rank(
            ascending=True, pct=True, na_option="keep"
        )

    dim_cols = {"billboard": "bb_score", "spotify_streams": "sp_score"}
    available_dims = {k: v for k, v in dim_cols.items() if v in merged.columns}
    merged["final_score"] = _apply_weights(merged, available_dims)

    # Normalize to 0–100
    max_score = merged["final_score"].max()
    if max_score > 0:
        merged["final_score"] = (merged["final_score"] / max_score * 100).round(2)

    merged = merged.sort_values("final_score", ascending=False).reset_index(drop=True)
    merged.index += 1

    out = os.path.join(DATA, "scores.csv")
    merged.to_csv(out)
    print(f"Wrote {len(merged)} scored songs to {out}")
    print("\nTop 10:")
    print(merged[["title", "artist", "final_score"]].head(10).to_string())
    return merged


if __name__ == "__main__":
    songs_only = "--songs-only" in sys.argv
    compute_scores(songs_only=songs_only)
