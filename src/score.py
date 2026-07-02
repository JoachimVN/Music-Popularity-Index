"""
Aggregates raw data from Billboard, kworb (Spotify streams), and kworb
(YouTube views) into a composite popularity score per song.

Run with --songs-only to emit data/songs.csv.
Run normally to compute final scores and write data/scores.csv.
"""

import pandas as pd
import numpy as np
import unicodedata
import os
import sys
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import WEIGHTS, BILLBOARD_ERA_HALF_WINDOW, BILLBOARD_PEAK_WEIGHT

DATA = os.path.join(os.path.dirname(__file__), "../data")


def _strip_diacritics(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def normalize_title(t):
    t = _strip_diacritics(str(t).lower().strip())
    t = re.sub(r"\([^\)]*\)", "", t)
    t = re.sub(r"\[[^\]]*\]", "", t)
    # Exportify's " - Single Version"/" - Remastered 2011"/" - Radio Edit"
    # style edition suffixes aren't part of the song identity — strip them
    # the same way fetch_spotify_links.py's _nd() already does, otherwise
    # e.g. "Take My Breath - Single Version" never matches Billboard's plain
    # "Take My Breath" and its floor/streams data goes unmatched.
    t = re.sub(r" - .*$", "", t)
    # A bare hyphen with no surrounding spaces (e.g. RIAA's "TIK-TOK" vs
    # Billboard/kworb's "TiK ToK") is a word separator, not punctuation to
    # discard outright — stripping it below without first turning it into a
    # space would silently join the two halves into one word ("tiktok")
    # instead of matching the space-separated key ("tik tok").
    t = t.replace("-", " ")
    # Double-A-side/medley titles joined by "/" can be listed in a different
    # order across sources — e.g. Billboard's "Candle In The Wind 1997/
    # Something About The Way You Look Tonight" vs RIAA's "Something About
    # The Way You Look Tonight / Candle In The Wind 1997". Sort the parts so
    # word order doesn't matter, same reasoning as the hyphen fix above: a
    # bare "/" is a separator the join depends on, not noise to discard.
    if "/" in t:
        parts = sorted(p.strip() for p in t.split("/") if p.strip())
        t = " ".join(parts)
    # Contracted "-in'" vs full "-ing" is the single most common cross-source
    # title mismatch (e.g. "Walkin'" vs "Walking", "Comin'" vs "Coming") —
    # normalize to "ing" whenever the source actually spelled it with the
    # apostrophe, so this doesn't false-positive on real words like "cabin"
    # that just happen to end in "in" with no apostrophe.
    t = re.sub(r"in'(\s|$)", r"ing\1", t)
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()


# A few artist credits differ between sources in a way no generic rule
# safely covers — not a separator pattern, not a "the"-prefix, just a
# different spelling/abbreviation for the same act. A short explicit alias
# list beats a fragile regex that risks merging unrelated artists.
_ARTIST_ALIASES = {
    # Billboard spells this act's name out in full; kworb/Spotify shorten it.
    "soulja boy tellem": "soulja boy",
    # Billboard mis-scrapes the full band name down to just the first word.
    "lillywood": "lilly wood and the prick",
    # Band's post-2020 rebrand; Billboard still credits the old name on older chart entries.
    "lady a": "lady antebellum",
    # Billboard's own scrape for this credit has no separator at all between
    # the two artists ("Jay Z Kanye West"), unlike every other multi-artist
    # credit in the same file — nothing for a generic separator rule to key
    # off, so it's listed here instead of guessed at with a fragile regex.
    "jay z kanye west": "jayz",
}


def normalize_artist(a):
    a = _strip_diacritics(str(a).lower().strip())
    a = a.replace("$", "s")  # stylized stage names, e.g. "Ke$ha" -> kworb's "Kesha"
    # A leading "The" is inconsistently included across sources for the same
    # act (Billboard: "The Black Eyed Peas", kworb: "Black Eyed Peas") — drop
    # it so they key-match instead of silently fragmenting into two rows.
    a = re.sub(r"^the\s+", "", a)
    a = re.sub(r"\(.*", "", a)  # drop "(with ...)" / "(Remix)" style suffixes
    # Strip collaboration suffixes. kworb always lists the primary artist only,
    # while Billboard spells out all collaborators in several formats:
    #   "feat."/"ft."/"featuring" — e.g. "The Weeknd Featuring Daft Punk"
    #   "with"                    — e.g. "Sam Smith with Calvin Harris"
    #   ", X"                     — e.g. "Cardi B, Bad Bunny & J Balvin"
    #   "& X" / "x X" / "+ X"    — e.g. "Lady Gaga & Bruno Mars", "Jawsh 685 x Jason Derulo",
    #                               "Jay-Z + Alicia Keys"
    #   "vs. X"                   — e.g. "Lana Del Rey vs. Cedric Gervais" (remix credits)
    a = re.sub(r"\b(feat\.?|ft\.?|featuring)\b.*", "", a)
    a = re.sub(r"\bwith\b.*", "", a)
    a = re.sub(r"\bvs\.?\b.*", "", a)
    a = re.sub(r",.*", "", a)
    a = re.sub(r"\s*\+.*", "", a)
    # Require a non-whitespace char after & or x so "Lil Nas X" isn't eaten
    a = re.sub(r"[ \t][&x][ \t]\S.*", "", a)
    a = re.sub(r"/.*", "", a)  # "A/B Band" → "A"; AC/DC → "ac" in both sources, still matches
    a = re.sub(r"[^\w\s]", "", a)
    a = re.sub(r"\s+", " ", a).strip()
    return _ARTIST_ALIASES.get(a, a)


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


def _load_billboard_style_chart(filename, date_col, prefix, label):
    """
    Load a Billboard chart export in hot100.csv's shape (peak position + weeks
    charted per song per week) and score it the way Billboard's own bb_score
    is scored: 0.6*peak_pct + 0.4*weeks_pct, era-normalised via a centred
    rolling window (see rolling_percentile). Shared by load_billboard,
    load_digital_sales, and load_radio — they only differ in which file they
    read, that file's date column header, and the prefix used for the
    peak/chart_weeks/score output columns.
    """
    path = os.path.join(DATA, filename)
    if not os.path.exists(path):
        print(f"WARNING: {filename} not found — {label} dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path, usecols=[date_col, "Song", "Artist", "Peak Position", "Weeks in Charts"])
    df = df.rename(columns={
        date_col: "date",
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

    peak_col, weeks_col, score_col = f"{prefix}_peak", f"{prefix}_chart_weeks", f"{prefix}_score"

    # Count distinct chart weeks per song from actual dataset rows.
    chart_weeks_count = df.groupby(["key_title", "key_artist"])["date"].nunique().rename(weeks_col)

    agg = df.groupby(["key_title", "key_artist"]).agg(
        title=("title", "first"),
        artist=("artist", "first"),
        year=("year", "min"),
        **{peak_col: ("peak_pos", "min")},
    ).reset_index()

    agg = agg.join(chart_weeks_count, on=["key_title", "key_artist"])
    agg[peak_col] = agg[peak_col].astype(int)
    agg[weeks_col] = agg[weeks_col].astype(int)
    agg["year"] = agg["year"].astype(int)
    # Derive decade from the song's debut year (kept for reference/export only;
    # scoring no longer buckets by decade).
    agg["decade"] = (agg["year"] // 10) * 10

    # Era-normalise via a centred rolling window: each song's peak and longevity
    # are ranked against every song released within ±BILLBOARD_ERA_HALF_WINDOW
    # years of it. No decade-boundary discontinuities; edge years (1958, today)
    # just see a shorter one-sided window.
    peak_pct = rolling_percentile(agg["year"], agg[peak_col], BILLBOARD_ERA_HALF_WINDOW, higher_is_better=False)
    weeks_pct = rolling_percentile(agg["year"], agg[weeks_col], BILLBOARD_ERA_HALF_WINDOW, higher_is_better=True)
    agg[score_col] = BILLBOARD_PEAK_WEIGHT * peak_pct + (1 - BILLBOARD_PEAK_WEIGHT) * weeks_pct
    return agg


def load_billboard():
    return _load_billboard_style_chart("hot100.csv", "1Date", "bb", "Billboard")


def load_digital_sales():
    return _load_billboard_style_chart("digital.csv", "Date", "sales", "digital sales")


def load_radio():
    return _load_billboard_style_chart("radio.csv", "Date", "radio", "radio airplay")


def load_kworb():
    path = os.path.join(DATA, "kworb_raw.csv")
    if not os.path.exists(path):
        print("WARNING: kworb_raw.csv not found — Spotify streams dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)

    # kworb sometimes tracks a plain title and a "(Remix)"-tagged title as two
    # separate rows for the same song (e.g. "Save Your Tears" vs "Save Your
    # Tears (Remix)", both credited to "The Weeknd" — kworb never credits the
    # remix's featured artist at all). normalize_title collapses both to one
    # key, and we keep whichever has more streams. When the plain version
    # wins, kworb's own artist credit for it is more trustworthy for display
    # than another source's credit, which may carry a collaborator specific
    # to the losing remix (Billboard credits "The Weeknd & Ariana Grande" for
    # every historical week, including ones that predate the remix) — flag
    # these rows so compute_scores() can prefer kworb's own title/artist.
    df["_is_remix"] = df["title"].str.contains(r"\bremix\b", case=False, regex=True, na=False)
    has_remix_sibling = df.groupby(["key_title", "key_artist"])["_is_remix"].transform("any")
    has_plain_sibling = df.groupby(["key_title", "key_artist"])["_is_remix"].transform(lambda s: (~s).any())
    df["authoritative"] = has_remix_sibling & has_plain_sibling & ~df["_is_remix"]
    df = df.drop(columns="_is_remix")

    df = df.sort_values("spotify_streams", ascending=False).drop_duplicates(subset=["key_title", "key_artist"])
    # sp_score assigned after merge with Billboard (needs year for era normalisation)
    return df[["key_title", "key_artist", "title", "artist", "spotify_streams", "authoritative"]]


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


# RIAA award tier -> unit threshold (Nx prefix multiplies the base, e.g.
# "3x Platinum" = 3,000,000). Unlike every other dimension, this one spans
# the index's entire 1958-present range, so it isn't era-gated in
# _PLATFORM_START — it's meant to give pre-streaming songs a second all-era
# signal alongside Billboard.
# Digit run is bounded (real RIAA multipliers top out around 30x) so a
# non-matching string can't force super-linear backtracking via .search().
# The multiplier can be fractional (e.g. "0.6x Diamond" — RIAA re-expresses
# a certification against a threshold that was revised after the original
# filing), so allow an optional decimal part.
_RIAA_TIER_RE = re.compile(r"(?:(\d{1,3}(?:\.\d+)?)x\s*)?(gold|platinum|diamond)", re.I)
_RIAA_BASE_UNITS = {"gold": 500_000, "platinum": 1_000_000, "diamond": 10_000_000}
# RIAA's Latin track uses much lower unit thresholds than the standard track
# — Oro=30,000, Platino=60,000, Diamante=600,000 (10x Platino) — see
# https://www.riaa.com/gold-platinum/certification-criteria/ and
# https://www.riaa.com/j-balvin-earns-first-ever-latin-digital-diamond-honor/.
# The site labels all three tracks' tiers "Gold"/"Platinum"/"Diamond"
# identically, so a scraped tier string alone can't tell them apart (see
# fetch_riaa.py's scrape_latin()).
_RIAA_LATIN_BASE_UNITS = {"gold": 30_000, "platinum": 60_000, "diamond": 600_000}


def _riaa_tier_to_units(tier, is_latin=False):
    m = _RIAA_TIER_RE.search(str(tier))
    if not m:
        return None
    mult = float(m.group(1)) if m.group(1) else 1
    base_units = _RIAA_LATIN_BASE_UNITS if is_latin else _RIAA_BASE_UNITS
    return mult * base_units[m.group(2).lower()]


def _load_latin_cert_keys():
    """
    (key_title, key_artist, cert_date, award_tier) for every certification
    scraped under RIAA's type=LA filter (fetch_riaa.py's scrape_latin()).
    riaa_raw.csv is scraped with no type filter, so it already includes
    every Latin certification too — this set is only used to flag which of
    those rows were actually certified under the Latin track's lower
    thresholds, since the tier text itself doesn't say.
    """
    path = os.path.join(DATA, "riaa_latin_raw.csv")
    if not os.path.exists(path):
        return set()
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        # Written by an in-progress scrape that hasn't found a Latin
        # certification yet (early decades predate the Latin track).
        return set()
    if df.empty:
        return set()
    keys = zip(df["title"].map(normalize_title), df["artist"].map(normalize_artist),
               df["cert_date"], df["award_tier"])
    return set(keys)


def load_riaa():
    path = os.path.join(DATA, "riaa_raw.csv")
    if not os.path.exists(path):
        print("WARNING: riaa_raw.csv not found — RIAA certification dimension skipped")
        return pd.DataFrame()

    df = pd.read_csv(path)
    df["key_title"] = df["title"].map(normalize_title)
    df["key_artist"] = df["artist"].map(normalize_artist)

    latin_keys = _load_latin_cert_keys()
    is_latin = [
        (kt, ka, cd, tier) in latin_keys
        for kt, ka, cd, tier in zip(df["key_title"], df["key_artist"], df["cert_date"], df["award_tier"])
    ]
    df["riaa_units"] = [
        _riaa_tier_to_units(tier, is_latin=latin)
        for tier, latin in zip(df["award_tier"], is_latin)
    ]
    df = df.dropna(subset=["riaa_units"])
    # A song is re-certified every time it crosses a higher tier — keep only
    # the highest one reached (same "keep highest" pattern as _load_chart_points).
    df = df.sort_values("riaa_units", ascending=False).drop_duplicates(subset=["key_title", "key_artist"])
    return df[["key_title", "key_artist", "title", "artist", "riaa_units"]]


def _load_exportify_keys(filename):
    """(key_title, key_artist) set for every track in an Exportify playlist export."""
    path = os.path.join(DATA, filename)
    if not os.path.exists(path):
        return set()
    df = pd.read_csv(path, usecols=["Track Name", "Artist Name(s)"])
    title = df["Track Name"].map(normalize_title)
    # Exportify's "Artist Name(s)" is semicolon-separated; the primary artist
    # is enough to match against key_artist, which is itself already reduced
    # to the primary artist by normalize_artist().
    artist = df["Artist Name(s)"].str.split(";").str[0].map(normalize_artist)
    return set(zip(title, artist))


# kworb only scrapes the top ~2500 all-time Spotify streams (currently topping
# out around 685M at the bottom of that list), so a song can be known — via a
# curated "N+ Million Streams" playlist export — to clear a streaming
# threshold while still being absent from kworb entirely. Without a floor such
# songs are scored as if they had zero Spotify streams. Order matters: the
# 500M floor is applied first so the 100M floor never overwrites it.
_STREAM_FLOORS = [
    ("500+_Million_Streams_[Top_50_ordered_by_Streams]_Most_played_tracks_on_Spotify.csv", 500_000_000),
    ("100+_Million_Streams_[2009_and_Older].csv", 100_000_000),
]


def _apply_stream_floors(merged):
    merged["spotify_streams_is_floor"] = False
    missing = merged["spotify_streams"].isna()
    keys = list(zip(merged["key_title"], merged["key_artist"]))

    for filename, floor in _STREAM_FLOORS:
        song_keys = _load_exportify_keys(filename)
        if not song_keys:
            continue
        in_playlist = pd.Series([k in song_keys for k in keys], index=merged.index)
        n = int((missing & in_playlist).sum())
        if n:
            merged.loc[missing & in_playlist, "spotify_streams"] = floor
            merged.loc[missing & in_playlist, "spotify_streams_is_floor"] = True
            print(f"  Backfilled {n} songs missing from kworb with a {floor:,}-stream floor from {filename}")
        missing = merged["spotify_streams"].isna()  # recompute so the next floor can't overwrite this one
    return merged


def _artist_tokens(raw_artist):
    """
    Every individual artist name mentioned in a raw credit string, e.g.
    "Rihanna Featuring Calvin Harris" -> {"rihanna", "calvin harris"}.
    Reuses utils.split_all_artists (handles "&", ",", " x ", "/", feat/ft/
    featuring/with/vs, quote-stripping) then normalizes each name so it's
    comparable to key_artist.
    """
    from src.utils import split_all_artists
    return {normalize_artist(p) for p in split_all_artists(raw_artist)} - {""}


class _UnionFind:
    def __init__(self):
        self._parent = {}

    def find(self, x):
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[ra] = rb


def _cluster_key_artists(frames):
    """
    Different sources often disagree on which collaborator is "primary" for
    the same song — Billboard credits "We Found Love" to "Rihanna Featuring
    Calvin Harris" (key_artist "rihanna"), kworb credits it to "Calvin Harris"
    solo (key_artist "calvin harris"). Matching strictly on (title, primary
    artist) then splits one song into unmatched fragments across sources.

    Cluster (key_title, key_artist) pairs that share a title and at least one
    artist name in common, via the *full* collaborator list rather than just
    the primary name, and return a map from every pair to one canonical
    representative pair. Clustering is scoped per key_title, so a "(Remix)"
    tag that survived normalize_title (kept deliberately distinct — see
    normalize_title) never merges with the original.
    """
    uf = _UnionFind()
    token_owner = {}  # (key_title, artist_token) -> owning (key_title, key_artist) node
    all_nodes = set()
    for df in frames:
        for kt, ka, raw_artist in zip(df["key_title"], df["key_artist"], df["artist"]):
            node = (kt, ka)
            all_nodes.add(node)
            for tok in _artist_tokens(raw_artist):
                owner_key = (kt, tok)
                if owner_key in token_owner:
                    uf.union(node, token_owner[owner_key])
                else:
                    token_owner[owner_key] = node

    return {node: uf.find(node) for node in all_nodes}


def _apply_artist_clusters(df, cluster_map, value_col=None):
    """
    Remap key_artist to its cluster's canonical value. Clustering can make
    several rows within the same source share a (key_title, key_artist) pair
    (e.g. iTunes tracking "Save Your Tears" separately for "The Weeknd" solo
    and "The Weeknd & Ariana Grande") — collapse those to one row, keeping
    the highest value_col (falls back to keeping the first row).
    """
    df = df.copy()
    df["key_artist"] = [cluster_map[(kt, ka)][1] for kt, ka in zip(df["key_title"], df["key_artist"])]
    if value_col and value_col in df.columns:
        df = df.sort_values(value_col, ascending=False)
    return df.drop_duplicates(subset=["key_title", "key_artist"])


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
# RIAA certifications are also NOT listed here, for the same reason — the
# program has run since 1958, so this is meant to be a second all-era signal
# (alongside Billboard) for pre-streaming songs that have nothing else to lean on.
_PLATFORM_START = {
    "itunes_total":   2010,
    "apple_total":    2017,
    "digital_sales":  2004,
    "radio_airplay":  1990,
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
        weighted_sum += era_applicable * merged[col].fillna(0) * w

    # Normalise by era-appropriate weight; songs with no applicable platform get 0.
    denom = denominator.where(denominator > 0, other=1.0)
    return (weighted_sum / denom).where(denominator > 0, other=0.0)


def _cluster_all_sources(bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio):
    """
    Apply _cluster_key_artists across all eight sources, so a song credited to
    a different "primary" artist per source still merges into one row.
    """
    frames_and_cols = [(bb, "bb_score"), (kworb, "spotify_streams"), (youtube, "youtube_views"),
                        (itunes, "itunes_total"), (apple, "apple_total"),
                        (digital_sales, "sales_score"), (riaa, "riaa_units"),
                        (radio, "radio_score")]
    non_empty = [df for df, _ in frames_and_cols if not df.empty]
    if not non_empty:
        return bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio

    cluster_map = _cluster_key_artists(non_empty)
    return tuple(
        _apply_artist_clusters(df, cluster_map, value_col=col) if not df.empty else df
        for df, col in frames_and_cols
    )


def _build_song_list(bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio):
    """
    Concat every source's (key_title, key_artist, title, artist) rows into
    one list, preferring kworb's own credit for songs flagged "authoritative"
    (see load_kworb) over Billboard's — drop_duplicates downstream keeps
    whichever row appears first per key.
    """
    cols = ["key_title", "key_artist", "title", "artist"]
    dfs = []
    if not kworb.empty and "authoritative" in kworb.columns:
        auth_kworb = kworb[kworb["authoritative"]]
        if not auth_kworb.empty:
            dfs.append(auth_kworb[cols])
    dfs.extend(df[cols] for df in (bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio) if not df.empty)
    return dfs


def compute_scores(songs_only=False):
    bb = load_billboard()
    kworb = load_kworb()
    youtube = load_youtube()
    itunes = load_itunes()
    apple = load_apple_music()
    digital_sales = load_digital_sales()
    riaa = load_riaa()
    radio = load_radio()

    bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio = _cluster_all_sources(
        bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio
    )

    dfs = _build_song_list(bb, kworb, youtube, itunes, apple, digital_sales, riaa, radio)
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
    merged = _apply_stream_floors(merged)
    merged = _left_merge(merged, youtube, ["youtube_views"])
    merged = _left_merge(merged, itunes,  ["itunes_total"])
    merged = _left_merge(merged, apple,   ["apple_total"])
    merged = _left_merge(merged, digital_sales, ["sales_score", "sales_peak", "sales_chart_weeks"])
    merged = _left_merge(merged, riaa, ["riaa_units"])
    merged = _left_merge(merged, radio, ["radio_score", "radio_peak", "radio_chart_weeks"])

    # Era-normalise all streaming/chart-point dimensions by release decade.
    # Songs missing a decade (source-only, no Billboard year) fall into a
    # shared "unknown" bucket and are ranked among themselves.
    merged["decade"] = ((merged["year"].fillna(0) // 10) * 10).astype(int)
    for raw_col, score_col in [
        ("spotify_streams", "sp_score"),
        ("youtube_views",   "yt_score"),
        ("itunes_total",    "itunes_score"),
        ("apple_total",     "apple_score"),
        ("riaa_units",      "riaa_score"),
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
        "digital_sales":   "sales_score",
        "riaa_certification": "riaa_score",
        "radio_airplay":   "radio_score",
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
