import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
LAST_FM_API_KEY = os.getenv("LAST_FM_API_KEY")

# Scoring weights (must sum to 1.0)
# For songs missing Spotify chart data (pre-2017), spotify_charts weight
# is redistributed proportionally to the other two.
WEIGHTS = {
    "billboard": 0.45,
    "spotify_charts": 0.30,
    "lastfm": 0.25,
}

# Billboard: how many weeks counts as "very long" (used for normalization)
BILLBOARD_MAX_WEEKS = 52

# Spotify charts: same concept
SPOTIFY_CHARTS_MAX_WEEKS = 52

# Last.fm: playcount ceiling for normalization (songs above this get score 1.0)
LASTFM_MAX_PLAYCOUNT = 50_000_000

# How many top songs to show in the output table
TOP_N = 100
