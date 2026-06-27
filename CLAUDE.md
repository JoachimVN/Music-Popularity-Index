# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` file with:
```
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

## Running the pipeline

Scripts run from the repo root with the venv active.

**Most of the time, use the one-command runner** (orchestrates the downstream steps in order):

```bash
python src/run_pipeline.py           # full: score -> spotify links -> csv -> html
python src/run_pipeline.py --quick   # fast iteration: score -> csv only (no network, no html)
```

Use `--quick` while tweaking `score.py`; run a full pass to refresh Spotify links
and the published HTML pages. The Spotify fetch is cached, so a full run only looks
up songs that newly entered the top `TOP_N`.

The runner does not scrape — run the fetchers manually when you need fresh source data:

```bash
python src/fetch_billboard.py     # scrapes Hot 100 weekly (resumable, ~875 requests)
python src/fetch_kworb.py         # scrapes kworb.net all-time Spotify streams
```

Individual downstream steps (what the runner calls, in order):

```bash
python src/score.py               # merges data and writes data/scores.csv
python src/fetch_spotify_links.py # looks up Spotify URLs for top TOP_N songs (cached)
python src/export_csv.py          # merges scores + links -> output/music_index_full.csv
python src/export.py              # writes output/index.html
python src/export_billboard.py    # writes output/billboard.html
```

## Architecture

This is a batch data pipeline with no tests or build system. All state lives in CSVs under `data/`.

**Data flow:**
```
fetch_billboard.py  →  data/hot100.csv      ↘
fetch_kworb.py      →  data/kworb_raw.csv   →  score.py → data/scores.csv ─┬─ export.py → output/index.html
                                                                          ├─ fetch_spotify_links.py → data/spotify_links.csv
                                                                          └─ export_csv.py → output/music_index_full.csv
                                                            load_billboard() → export_billboard.py → output/billboard.html
```

`export_csv.py` joins `data/scores.csv` with the cached `data/spotify_links.csv` into
`output/music_index_full.csv` (full ranking, all columns + `spotify_url`). `run_pipeline.py`
chains score → fetch_spotify_links → export_csv → export → export_billboard.

**Scoring logic (`src/score.py`):**
- Both dimensions are era-normalized via within-decade percentile rank so songs from different eras are directly comparable.
- Billboard score: `0.6 × peak_pct + 0.4 × weeks_pct` (percentiles within the song's release decade)
- Spotify score: percentile rank of `spotify_streams` within the song's release decade
- Composite: `WEIGHTS["billboard"] × bb_score + WEIGHTS["spotify_streams"] × sp_score`, then normalized to 0–100
- Weights and `TOP_N` are configured in `config.py`

**Song matching across sources** uses normalized keys: titles have parentheticals and punctuation stripped; artists have featured-artist suffixes stripped. These are `key_title` and `key_artist` columns used for joins — not stored in output.

**`fetch_billboard.py`** samples every 4 weeks (configurable via `SAMPLE_EVERY_N_WEEKS`) and saves progress every 50 batches so it can be safely interrupted and resumed. It writes to `data/billboard_raw.csv`; note that `score.py` reads from `data/hot100.csv` — if these differ, check which file is the authoritative scraped source.

**`fetch_lastfm.py`** is currently non-functional: it imports `LAST_FM_API_KEY` from `config.py`, which no longer defines that key (Last.fm was dropped as a scoring dimension per recent commits).
