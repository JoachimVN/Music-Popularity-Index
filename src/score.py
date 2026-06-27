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
from config import WEIGHTS, BILLBOARD_MAX_WEEKS, SPOTIFY_STREAMS_MAX, LASTFM_MAX_PLAYCOUNT

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

    # p75 weeks per decade — the "ceiling" for a strong chart run in each era.
    # A song needs 2× the decade p75 to score 1.0 on weeks, making era comparison fair.
    decade_p75 = df.groupby("decade")["weeks_on_chart"].quantile(0.75).to_dict()

    agg = df.groupby(["key_title", "key_artist"]).agg(
        title=("title", "first"),
        artist=("artist", "first"),
        bb_peak=("peak_pos", "min"),
        bb_weeks=("weeks_on_chart", "max"),
        year=("year", "min"),
        decade=("decade", "first"),
    ).reset_index()

    agg["decade_p75"] = agg["decade"].map(decade_p75).clip(lower=1)
    era_weeks = (agg["bb_weeks"] / agg["decade_p75"]) / 2.0  # 2× p75 = score 1.0
    agg["bb_score"] = (
        0.5 * peak_score(agg["bb_peak"]) +
        0.5 * era_weeks.clip(upper=1.0)
    )
    return agg


def load_kworb():
    path = os.path.join(DATA, "kworb_raw.csv")
    if not os.path.exists(path):
        print("WARNING: kworb_raw.csv not found — Spotify streams dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)
    df["sp_score"] = np.clip(df["spotify_streams"] / SPOTIFY_STREAMS_MAX, 0, 1)
    return df[["key_title", "key_artist", "title", "artist", "spotify_streams", "sp_score"]]


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
    lfm = load_lastfm()

    # Build master song list from all available sources
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

    # Merge all dimensions
    merged = songs
    if not bb.empty:
        merged = merged.merge(
            bb[["key_title", "key_artist", "bb_score", "bb_peak", "bb_weeks", "year"]],
            on=["key_title", "key_artist"], how="left"
        )
    if not kworb.empty:
        merged = merged.merge(
            kworb[["key_title", "key_artist", "spotify_streams", "sp_score"]],
            on=["key_title", "key_artist"], how="left"
        )
    if not lfm.empty:
        merged = merged.merge(lfm, on=["key_title", "key_artist"], how="left")

    # Weighted score — redistribute weight for missing dimensions per song
    dim_cols = {
        "billboard": "bb_score",
        "spotify_streams": "sp_score",
        "lastfm": "lfm_score",
    }
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
