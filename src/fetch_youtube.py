"""
Scrapes kworb.net/youtube/topvideos.html for all-time YouTube view counts.
Output: data/youtube_raw.csv  (artist, title, youtube_views)

kworb puts featured artists and metadata inside the title string, e.g.:
  "Despacito ft. Daddy Yankee"
  "Shape of You (Official Music Video)"
These are stripped before saving so the title matches Billboard's clean format.
"""

import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os

URL = "https://kworb.net/youtube/topvideos.html"
OUTPUT = os.path.join(os.path.dirname(__file__), "../data/youtube_raw.csv")
HEADERS = {"User-Agent": "Mozilla/5.0"}

# "ft. X" / "feat. X" suffixes that kworb puts in the title, not the artist
_FEAT_RE = re.compile(r'\s+(?:ft\.?|feat\.?|featuring)\s+.*$', re.IGNORECASE)
# Trailing bracketed metadata: (Official Video), [Official Music Video], etc.
_META_RE = re.compile(r'\s*[\(\[].*$')


def clean_title(title):
    title = _FEAT_RE.sub("", title)
    title = _META_RE.sub("", title)
    return title.strip()


def parse_views(s):
    return int(s.replace(",", "").strip())


def scrape():
    print(f"Fetching {URL} ...")
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    rows = table.find("tbody").find_all("tr")

    records = []
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        raw = cols[0].get_text(strip=True)
        parts = raw.split(" - ", 1)
        if len(parts) != 2:
            continue
        artist, title = parts[0].strip(), clean_title(parts[1].strip())

        try:
            views = parse_views(cols[1].get_text())
        except ValueError:
            continue

        records.append({"artist": artist, "title": title, "youtube_views": views})

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT, index=False)
    print(f"Saved {len(df)} videos to {OUTPUT}")
    print("\nTop 5:")
    print(df.head().to_string(index=False))
    return df


if __name__ == "__main__":
    scrape()
