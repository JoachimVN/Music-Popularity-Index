"""
Finds songs that are probably the same track but failed to merge across
sources — two rows in scores.csv with different key_title/key_artist that
should have joined into one, so one side's dimension data (Billboard, RIAA,
Spotify, etc.) never reached the other. This is the general form of bugs
found by hand this session (TIK-TOK vs TiK ToK, "Jay Z Kanye West" vs
"JAY-Z & KANYE WEST", reversed medley titles, ...).

Read-only: prints candidate pairs and writes data/duplicate_candidates.csv
for manual review. Doesn't modify any data — fixes (regex rules, aliases)
still need to be applied by hand in score.py/utils.py once a candidate is
confirmed to be a real duplicate.

Run after score.py.
"""

import pandas as pd
import os
import sys
from difflib import SequenceMatcher

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.score import _artist_tokens

DATA = os.path.join(os.path.dirname(__file__), "../data")
SCORES = os.path.join(DATA, "scores.csv")
OUTPUT = os.path.join(DATA, "duplicate_candidates.csv")

# A pair is only worth flagging if merging them would actually add
# information — i.e. the two rows have some data each other lacks, not the
# same dimensions on both sides (which is more likely two genuinely
# different recordings/versions than a missed merge).
DIM_PRESENCE_COLS = [
    "bb_score", "spotify_streams", "youtube_views", "itunes_total",
    "apple_total", "sales_score", "riaa_units", "radio_score",
]

TITLE_SIM_THRESHOLD = 0.82


def _title_block_key(key_title):
    """Coarse blocking key so we only compare plausibly-related songs
    instead of every pair in ~47k rows: first 3 chars of up to the first 3
    significant (len>2) words, sorted so word-order differences still land
    in the same bucket."""
    words = [w for w in key_title.split() if len(w) > 2]
    return tuple(sorted(w[:3] for w in words[:3]))


def _build_blocks(df):
    """Bucket row indices by _title_block_key so we only compare plausibly-
    related songs instead of every pair across ~47k rows."""
    buckets = {}
    for idx, row in df.iterrows():
        key = _title_block_key(str(row["key_title"]))
        if key:
            buckets.setdefault(key, []).append(idx)
    return buckets


def _bucket_pairs(idxs):
    """Every unordered pair of row indices within one blocking bucket."""
    for i in range(len(idxs)):
        for j in range(i + 1, len(idxs)):
            yield idxs[i], idxs[j]


def _evaluate_pair(a, b):
    """A candidate-row dict if (a, b) look like a missed cross-source merge
    (similar title, overlapping artist, complementary — not identical —
    dimension data), else None."""
    if a["key_title"] == b["key_title"] and a["key_artist"] == b["key_artist"]:
        return None

    title_sim = SequenceMatcher(None, str(a["key_title"]), str(b["key_title"])).ratio()
    if title_sim < TITLE_SIM_THRESHOLD:
        return None

    if not (_artist_tokens(a["artist"]) & _artist_tokens(b["artist"])):
        return None

    a_dims = {c for c in DIM_PRESENCE_COLS if pd.notna(a.get(c))}
    b_dims = {c for c in DIM_PRESENCE_COLS if pd.notna(b.get(c))}
    if not a_dims or not b_dims or a_dims == b_dims:
        return None

    return {
        "title_sim": round(title_sim, 3),
        "rank_a": a.name, "title_a": a["title"], "artist_a": a["artist"], "dims_a": ",".join(sorted(a_dims)),
        "rank_b": b.name, "title_b": b["title"], "artist_b": b["artist"], "dims_b": ",".join(sorted(b_dims)),
    }


def find_candidates(df):
    candidates = []
    seen_pairs = set()
    for idxs in _build_blocks(df).values():
        if len(idxs) < 2:
            continue
        for ia, ib in _bucket_pairs(idxs):
            pair_key = (ia, ib) if ia < ib else (ib, ia)
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            candidate = _evaluate_pair(df.loc[ia], df.loc[ib])
            if candidate:
                candidates.append(candidate)

    return pd.DataFrame(candidates).sort_values("title_sim", ascending=False).reset_index(drop=True)


def main():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return

    df = pd.read_csv(SCORES, index_col=0)
    candidates = find_candidates(df)
    candidates.to_csv(OUTPUT, index=False)
    print(f"Found {len(candidates)} candidate duplicate pairs")
    print(f"Wrote {OUTPUT}")
    with pd.option_context("display.max_rows", None, "display.width", 200):
        print(candidates.to_string())


if __name__ == "__main__":
    main()
