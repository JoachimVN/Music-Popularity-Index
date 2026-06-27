import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Scoring weights (must sum to 1.0)
# Both dimensions are era-normalised via within-decade percentile ranking,
# so they're directly comparable across eras.
WEIGHTS = {
    "billboard": 0.60,
    "spotify_streams": 0.40,
}

# How many top songs to show in the output table
TOP_N = 100
