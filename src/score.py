"""
Aggregates raw data from Billboard, kworb (Spotify streams), and kworb
(YouTube views) into a composite popularity score per song.

Run with --songs-only to emit data/songs.csv.
Run normally to compute final scores and write data/scores.csv.
"""

import pandas as pd
import numpy as np
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import WEIGHTS, BILLBOARD_ERA_HALF_WINDOW, BILLBOARD_PEAK_WEIGHT

DATA = os.path.join(os.path.dirname(__file__), "../data")


def normalize_title(t):
    t = str(t).lower().strip()
    t = re.sub(r"\([^\)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_artist(a):
    a = str(a).lower().strip()
    a = re.sub(r"\(.*", "", a)  # drop "(with ...)" / "(Remix)" style suffixes
    # Strip collaboration suffixes. kworb always lists the primary artist only,
    # while Billboard spells out all collaborators in several formats:
    #   "feat."/"ft."/"featuring" — e.g. "The Weeknd Featuring Daft Punk"
    #   "with"                    — e.g. "Sam Smith with Calvin Harris"
    #   ", X"                     — e.g. "Cardi B, Bad Bunny & J Balvin"
    #   "& X" / "x X"            — e.g. "Lady Gaga & Bruno Mars", "Jawsh 685 x Jason Derulo"
    a = re.sub(r"\b(feat\.?|ft\.?|featuring)\b.*", "", a)
    a = re.sub(r"\bwith\b.*", "", a)
    a = re.sub(r",.*", "", a)
    a = re.sub(r"\s+[&x]\s+.*", "", a)
    a = re.sub(r"/.*", "", a)  # "A/B Band" → "A"; AC/DC → "ac" in both sources, still matches
    a = re.sub(r"[^\w\s]", "", a)
    return re.sub(r"\s+", " ", a).strip()


def rolling_percentile(years, values, half_window, higher_is_better):
    """Percentile rank of each value against all songs released within
    ±half_window years of it (a centred rolling cohort instead of fixed
    calendar decades). Uses mid-rank percentiles so ties share a rank:

        pct = (#cohort this song beats + 0.5 * #ties) / cohort size

    For peak position, lower is better (#1 beats #100), so set
    higher_is_better=False. For chart longevity, more weeks is better.

    Values must be small non-negative integers (peak 1–100, weeks 1–~112);
    the cohort distribution per year is built once via a histogram, then a
    sliding window sum over the year axis makes each lookup O(1).
    """
    years = np.asarray(years, dtype=np.int64)
    values = np.asarray(values, dtype=np.int64)

    y_min = years.min()
    v_min = values.min()
    n_years = int(years.max() - y_min + 1)
    n_vals = int(values.max() - v_min + 1)

    # hist[year_idx, value_idx] = count of songs
    hist = np.zeros((n_years, n_vals), dtype=np.int64)
    np.add.at(hist, (years - y_min, values - v_min), 1)

    # Prefix sum over the year axis: cum_year[k] = total counts for years < k,
    # so the cohort for window [lo, hi] is cum_year[hi + 1] - cum_year[lo].
    cum_year = np.vstack([np.zeros(n_vals, np.int64), np.cumsum(hist, axis=0)])

    out = np.empty(len(years), dtype=float)
    cohort_cache = {}
    for i in range(len(years)):
        yi = int(years[i] - y_min)
        if yi not in cohort_cache:
            lo = max(0, yi - half_window)
            hi = min(n_years - 1, yi + half_window)
            cohort = cum_year[hi + 1] - cum_year[lo]
            cohort_cache[yi] = (cohort, np.cumsum(cohort), int(cohort.sum()))
        cohort, cum_val, total = cohort_cache[yi]

        v = int(values[i] - v_min)
        eq = int(cohort[v])
        le = int(cum_val[v])        # songs with value <= this one
        lt = le - eq                # strictly less
        gt = total - le             # strictly greater
        beaten = lt if higher_is_better else gt
        out[i] = (beaten + 0.5 * eq) / total
    return out


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
    ).reset_index()

    agg = agg.join(chart_weeks_count, on=["key_title", "key_artist"])
    agg["bb_peak"] = agg["bb_peak"].astype(int)
    agg["bb_chart_weeks"] = agg["bb_chart_weeks"].astype(int)
    agg["year"] = agg["year"].astype(int)
    # Derive decade from the song's debut year (kept for reference/export only;
    # scoring no longer buckets by decade).
    agg["decade"] = (agg["year"] // 10) * 10

    # Era-normalise via a centred rolling window: each song's peak and longevity
    # are ranked against every song released within ±BILLBOARD_ERA_HALF_WINDOW
    # years of it. No decade-boundary discontinuities; edge years (1958, today)
    # just see a shorter one-sided window.
    agg["peak_pct"] = rolling_percentile(
        agg["year"], agg["bb_peak"], BILLBOARD_ERA_HALF_WINDOW, higher_is_better=False
    )
    agg["weeks_pct"] = rolling_percentile(
        agg["year"], agg["bb_chart_weeks"], BILLBOARD_ERA_HALF_WINDOW, higher_is_better=True
    )

    agg["bb_score"] = (
        BILLBOARD_PEAK_WEIGHT * agg["peak_pct"]
        + (1 - BILLBOARD_PEAK_WEIGHT) * agg["weeks_pct"]
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
    df = df.sort_values("spotify_streams", ascending=False).drop_duplicates(subset=["key_title", "key_artist"])
    # sp_score assigned after merge with Billboard (needs year for era normalisation)
    return df[["key_title", "key_artist", "title", "artist", "spotify_streams"]]


def load_youtube():
    path = os.path.join(DATA, "youtube_raw.csv")
    if not os.path.exists(path):
        print("WARNING: youtube_raw.csv not found — YouTube dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)
    # A song can appear as multiple videos (music video + lyric video, etc.).
    # Keep the highest view count so we capture the song's peak YouTube presence.
    df = df.sort_values("youtube_views", ascending=False)
    df = df.drop_duplicates(subset=["key_title", "key_artist"])
    # yt_score assigned after merge with Billboard (needs year for era normalisation)
    return df[["key_title", "key_artist", "title", "artist", "youtube_views"]]


def _load_chart_points(filename, col, label):
    path = os.path.join(DATA, filename)
    if not os.path.exists(path):
        print(f"WARNING: {filename} not found — {label} dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)
    # After normalization multiple rows can share the same key (e.g. original
    # and remix both map to the primary artist). Keep the highest value.
    df = df.sort_values(col, ascending=False).drop_duplicates(subset=["key_title", "key_artist"])
    return df[["key_title", "key_artist", "title", "artist", col]]


def load_itunes():
    return _load_chart_points("itunes_raw.csv", "itunes_total", "iTunes")


def load_apple_music():
    return _load_chart_points("apple_music_raw.csv", "apple_total", "Apple Music")


def _left_merge(merged, df, cols):
    """Left-join `df[cols]` onto `merged` on key columns; no-op when df is empty."""
    if df.empty:
        return merged
    return merged.merge(df[["key_title", "key_artist"] + cols], on=["key_title", "key_artist"], how="left")


# Platforms that only started tracking at a specific year. Songs released before
# these dates couldn't have charted there, so we exclude those weights from the
# denominator rather than penalising them for an absence beyond their control.
# Spotify and YouTube are NOT listed here: kworb covers all eras, so absence
# from those top lists is a genuine popularity signal, not an era artefact.
_PLATFORM_START = {
    "itunes_total": 2010,
    "apple_total":  2017,
}


def _apply_weights(merged, available_dims):
    weighted_sum = pd.Series(0.0, index=merged.index)
    denominator  = pd.Series(0.0, index=merged.index)
    year = merged.get("year", pd.Series(0, index=merged.index)).fillna(0)

    for dim, col in available_dims.items():
        w = WEIGHTS[dim]
        start = _PLATFORM_START.get(dim)
        # Platform counts toward denominator only for songs released after it launched.
        era_applicable = (year >= start) if start else pd.Series(True, index=merged.index)
        denominator  += era_applicable * w
        weighted_sum += merged[col].fillna(0) * w

    # Normalise by era-appropriate weight; songs with no applicable platform get 0.
    denom = denominator.where(denominator > 0, other=1.0)
    return (weighted_sum / denom).where(denominator > 0, other=0.0)


def compute_scores(songs_only=False):
    bb = load_billboard()
    kworb = load_kworb()
    youtube = load_youtube()
    itunes = load_itunes()
    apple = load_apple_music()

    dfs = []
    if not bb.empty:
        dfs.append(bb[["key_title", "key_artist", "title", "artist"]])
    if not kworb.empty:
        dfs.append(kworb[["key_title", "key_artist", "title", "artist"]])
    if not youtube.empty:
        dfs.append(youtube[["key_title", "key_artist", "title", "artist"]])
    if not itunes.empty:
        dfs.append(itunes[["key_title", "key_artist", "title", "artist"]])
    if not apple.empty:
        dfs.append(apple[["key_title", "key_artist", "title", "artist"]])

    if not dfs:
        print("ERROR: No source data found. Run the fetchers first.")
        return

    songs = pd.concat(dfs).drop_duplicates(subset=["key_title", "key_artist"]).reset_index(drop=True)

    if songs_only:
        out = os.path.join(DATA, "songs.csv")
        songs[["title", "artist"]].to_csv(out, index=False)
        print(f"Wrote {len(songs)} unique songs to {out}")
        return

    # Merge all sources
    merged = songs
    merged = _left_merge(merged, bb,      ["bb_score", "bb_peak", "bb_chart_weeks", "year"])
    merged = _left_merge(merged, kworb,   ["spotify_streams"])
    merged = _left_merge(merged, youtube, ["youtube_views"])
    merged = _left_merge(merged, itunes,  ["itunes_total"])
    merged = _left_merge(merged, apple,   ["apple_total"])

    # Era-normalise all streaming/chart-point dimensions by release decade.
    # Songs missing a decade (source-only, no Billboard year) fall into a
    # shared "unknown" bucket and are ranked among themselves.
    merged["decade"] = ((merged["year"].fillna(0) // 10) * 10).astype(int)
    for raw_col, score_col in [
        ("spotify_streams", "sp_score"),
        ("youtube_views",   "yt_score"),
        ("itunes_total",    "itunes_score"),
        ("apple_total",     "apple_score"),
    ]:
        if raw_col in merged.columns:
            merged[score_col] = merged.groupby("decade")[raw_col].rank(
                ascending=True, pct=True, na_option="keep"
            )

    dim_cols = {
        "billboard":      "bb_score",
        "spotify_streams": "sp_score",
        "youtube_views":   "yt_score",
        "itunes_total":    "itunes_score",
        "apple_total":     "apple_score",
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
