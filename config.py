import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
LAST_FM_API_KEY = os.getenv("LAST_FM_API_KEY")

# Scoring weights (must sum to 1.0)
# Songs missing a dimension (e.g. pre-Spotify songs have no kworb data) get
# that weight redistributed to whichever dimensions they do have data for.
WEIGHTS = {
    "billboard": 0.45,
    "spotify_streams": 0.30,
    "lastfm": 0.25,
}

# Billboard: how many weeks counts as "very long" (used for normalization)

# Spotify streams: ceiling for normalization; top song (~5.5B) gets score 1.0
SPOTIFY_STREAMS_MAX = 6_000_000_000

# Last.fm: playcount ceiling for normalization (songs above this get score 1.0)
LASTFM_MAX_PLAYCOUNT = 50_000_000

# How many top songs to show in the output table
TOP_N = 100
