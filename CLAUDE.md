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
python src/fetch_youtube.py       # scrapes kworb.net all-time YouTube view counts
python src/fetch_itunes.py        # scrapes kworb.net worldwide iTunes chart point totals
python src/fetch_apple_music.py   # scrapes kworb.net Apple Music chart point totals
python src/fetch_riaa.py          # scrapes RIAA Gold/Platinum/Diamond single certifications (resumable, can take hours)
python src/fetch_album_art.py     # resolves album art via Spotify's public oEmbed endpoint (resumable, no API keys)
```

`fetch_album_art.py` is also not part of `run_pipeline.py` — run it manually after
`fetch_spotify_links.py` has resolved this run's tracks, then re-run `export_csv.py`
(or the full runner) to merge `data/album_art.csv` into the output.

Individual downstream steps (what the runner calls, in order):

```bash
python src/score.py               # merges data and writes data/scores.csv
python src/fetch_spotify_links.py # looks up Spotify URLs for top TOP_N songs (cached)
python src/export_csv.py          # merges scores + links + album art -> output/music_index_full.csv
python src/export.py              # writes output/index.html
python src/export_billboard.py    # writes output/billboard.html
```

## Architecture

This is a batch data pipeline with no tests or build system. All state lives in CSVs under `data/`.

**Data flow:**
```
fetch_billboard.py    →  data/hot100.csv            ↘
fetch_kworb.py        →  data/kworb_raw.csv          →  score.py → data/scores.csv ─┬─ export.py → output/index.html
fetch_youtube.py      →  data/youtube_raw.csv        ↗                              ├─ fetch_spotify_links.py → data/spotify_links.csv ─┐
fetch_itunes.py       →  data/itunes_raw.csv         ↗                              └─ export_csv.py → output/music_index_full.csv ←──┴─ fetch_album_art.py → data/album_art.csv
fetch_apple_music.py  →  data/apple_music_raw.csv   ↗
       (no fetcher)   →  data/digital.csv           ↗
       (no fetcher)   →  data/radio.csv             ↗
fetch_riaa.py          →  data/riaa_raw.csv          ↗
                                                             load_billboard() → export_billboard.py → output/billboard.html
```

`data/digital.csv` and `data/radio.csv` (Billboard's Digital Song Sales and Radio
Songs charts, same shape as `hot100.csv`) have no fetcher scripts yet — they were
scraped by hand/other tooling and just need to stay in `data/` for `score.py`'s
`load_digital_sales()`/`load_radio()` to pick them up. All three (`load_billboard`,
`load_digital_sales`, `load_radio`) share one implementation, `_load_billboard_style_chart()`,
since they're identically-shaped exports of different Billboard component charts.
Digital Song Sales only goes back to 2004-10-20 (no digital sales before iTunes) and
Radio Songs to 1990-10-24, so songs released before those dates are excluded from
that dimension's weight rather than penalized (see `_PLATFORM_START`).

**`fetch_riaa.py`** scrapes RIAA's Gold & Platinum certification database (Single
format only) for `load_riaa()`. Unlike Billboard's Digital Song Sales chart, RIAA
certifications go back to 1958, so this dimension is treated as all-era (like
Spotify/YouTube), not excluded via `_PLATFORM_START` — the point is to give
pre-streaming songs a second all-era signal besides Billboard. The site's
pagination ("Load More") is behind Cloudflare and blocks plain HTTP POST
requests, but the first page of any date-filtered query renders server-side on
a plain GET, so the fetcher partitions 1958–present into year chunks and
recursively bisects (by date, then by award tier, then by certification type)
any chunk that hits the ~25-row page cap. It's resumable per-year (progress
tracked in `data/riaa_progress.txt`, separate from the CSV, so sparse years
with zero real certifications don't get endlessly re-fetched) and can take
hours for a full historical run given the request volume in recent
high-certification years.

`export_csv.py` joins `data/scores.csv` with the cached `data/spotify_links.csv` and
`data/album_art.csv` into `output/music_index_full.csv` (full ranking, all columns +
`spotify_url` + `album_art_url`). `run_pipeline.py` chains score → fetch_spotify_links
→ export_csv → export → export_billboard (album art is fetched separately, see below).

**`fetch_album_art.py`** resolves each song's album art through Spotify's public
oEmbed endpoint (`open.spotify.com/oembed?url=<track_url>`) — the same
unauthenticated endpoint Slack/Discord/etc. use for link-preview cards. It needs
no client credentials and isn't part of the Web API's per-app quota, unlike
`fetch_artist.py`'s single-track endpoint (see that script's docstring — a prior
run against the authenticated Web API got this app rate-limited for 24 hours).
Reads track URLs straight from `data/spotify_links.csv` (title/artist matching is
already solved there), fetches one at a time with a small delay, and saves
progress every 25 songs so an interrupted or re-run pass only fetches what's
still missing from `data/album_art.csv`. The consuming app (Versed) reads
`album_art_url` from the merged CSV and only falls back to a live Spotify call
for tracks this hasn't covered yet.

**Scoring logic (`src/score.py`):**
- All three streaming dimensions are era-normalized via within-decade percentile rank so songs from different eras are directly comparable.
- Billboard score: `0.6 × peak_pct + 0.4 × weeks_pct` (percentiles within the song's release decade)
- Spotify score: percentile rank of `spotify_streams` within the song's release decade
- YouTube score: percentile rank of `youtube_views` (top video per song) within the song's release decade
- iTunes score: percentile rank of `itunes_total` (cumulative chart points since Aug 2010) within the song's release decade
- Apple Music score: percentile rank of `apple_total` (cumulative chart points since Jul 2017) within the song's release decade
- Digital sales score: `0.6 × peak_pct + 0.4 × weeks_pct` on the Digital Song Sales chart (same rolling-window formula as Billboard, since Oct 2004)
- Radio airplay score: `0.6 × peak_pct + 0.4 × weeks_pct` on the Radio Songs chart (same rolling-window formula as Billboard, since Oct 1990)
- RIAA certification score: percentile rank of certified units (Gold=500k, Platinum=1M×tier, Diamond=10M×tier) within the song's release decade, all-era
- Composite: weighted sum of all available dimension scores, then normalized to 0–100
- Weights and `TOP_N` are configured in `config.py`

**Song matching across sources** uses normalized keys: titles have parentheticals and punctuation stripped; artists have featured-artist suffixes stripped. These are `key_title` and `key_artist` columns used for joins — not stored in output.

**`fetch_billboard.py`** samples every 4 weeks (configurable via `SAMPLE_EVERY_N_WEEKS`) and saves progress every 50 batches so it can be safely interrupted and resumed. It writes to `data/billboard_raw.csv`; note that `score.py` reads from `data/hot100.csv` — if these differ, check which file is the authoritative scraped source.

**`fetch_youtube.py`** scrapes kworb's top ~1000 YouTube videos. kworb puts featured artists and metadata in the title string (e.g. "Despacito ft. Daddy Yankee", "Shape of You (Official Music Video)") — these are stripped during scraping so the title matches Billboard's clean format. When a song has multiple videos in the top list, the highest view count is kept (see deduplication in `load_youtube()`).

**`fetch_lastfm.py`** is currently non-functional: it imports `LAST_FM_API_KEY` from `config.py`, which no longer defines that key (Last.fm was dropped as a scoring dimension per recent commits).
