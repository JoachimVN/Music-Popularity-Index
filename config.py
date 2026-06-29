import os
from dotenv import load_dotenv

load_dotenv()

SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Scoring weights (must sum to 1.0)
# Both dimensions are era-normalised so they're directly comparable across eras:
# Billboard via a centred rolling-window percentile (see BILLBOARD_ERA_HALF_WINDOW),
# Spotify streams via within-decade percentile ranking.
WEIGHTS = {
    "billboard":       0.40,
    "spotify_streams": 0.25,
    "youtube_views":   0.15,
    "itunes_total":    0.10,
    "apple_total":     0.10,
}

# Billboard era-normalisation: each song's peak and longevity are ranked against
# every song released within ±N years of it (a 2N+1 year window centred on the
# song's debut year). Replaces hard calendar-decade buckets, so there are no
# discontinuities at decade boundaries and edge years degrade gracefully.
BILLBOARD_ERA_HALF_WINDOW = 5

# Billboard composite: how much weight peak position gets vs chart longevity.
# The remainder (1 - this) goes to weeks-on-chart. Both are era-normalised percentiles.
BILLBOARD_PEAK_WEIGHT = 0.60

# How many top songs to show in the output table
TOP_N = 500
