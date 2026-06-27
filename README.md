# Music Popularity Index

A data pipeline that ranks songs by an era-normalized popularity score, combining
**Billboard Hot 100** chart history with **Spotify all-time stream counts**. Built
as the source of truth for a Name-That-Tune-style music quiz game.

**Live:** [joavn.dev/mpi](https://joavn.dev/mpi)

> **Work in progress.** The scoring model is still being tuned. Rankings,
> weights, and the song pool will change. Don't treat the current numbers as final.

## What it does

- Scrapes the Billboard Hot 100 (1958–present) and kworb.net all-time Spotify streams.
- Era-normalizes both dimensions so songs from different decades are comparable.
- Produces a ranked list (`output/music_index_full.csv`) and two browsable pages
  (`output/index.html`, `output/billboard.html`).

### Scoring (summary)

- **Billboard** (60%): peak position and chart longevity, each percentile-ranked
  against songs released within a ±5-year window (`60%` peak / `40%` weeks).
- **Spotify** (40%): stream count, percentile-ranked within the song's release decade.
- Composite is normalized to 0–100. Weights live in `config.py`.

See `CLAUDE.md` for the full architecture and data-flow notes.

## Setup

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create a `.env` with Spotify API credentials:

```
SPOTIFY_CLIENT_ID=...
SPOTIFY_CLIENT_SECRET=...
```

## Running the pipeline

Scrape source data first (slow, resumable — only needed when refreshing data):

```bash
python src/fetch_billboard.py   # Billboard Hot 100
python src/fetch_kworb.py       # Spotify all-time streams
```

Then build everything with the one-command runner:

```bash
python src/run_pipeline.py           # score -> spotify links -> csv -> html
python src/run_pipeline.py --quick   # fast iteration: score -> csv only (no network, no html)
```

Outputs land in `output/` (`index.html`, `billboard.html`, `music_index_full.csv`).
Tune the song pool size with `TOP_N` in `config.py`.

## Deployment

The site is served from the [Portfolio](https://github.com/JoachimVN/Portfolio)
repo (Vercel, `joavn.dev`) under the `mpi/` path. The built HTML pages
(`output/index.html`, `output/billboard.html`) are committed to this repo and synced
across automatically.

**Automatic:** the `Sync to Portfolio` GitHub Action runs on every push to `main`
that changes a published page. It copies the pages into `Portfolio/mpi/` and pushes.
Requires a repo secret **`PORTFOLIO_TOKEN`** — a personal access token with write
access to `JoachimVN/Portfolio` (the same token CHORIDOR-web uses).

To publish a new build:

```bash
python src/run_pipeline.py      # rebuild the pages
git add output/index.html output/billboard.html
git commit -m "Rebuild index"
git push                        # the Action syncs to joavn.dev/mpi
```

**Manual** (if you'd rather sync from your machine, with `../Portfolio` checked out):

```bash
./sync-portfolio.sh
```
