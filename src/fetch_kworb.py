"""
Scrapes kworb.net/spotify/songs.html for all-time Spotify stream counts.
Returns the top 2500 most-streamed songs of all time.
Output: data/kworb_raw.csv
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import os

URL = "https://kworb.net/spotify/songs.html"
OUTPUT = os.path.join(os.path.dirname(__file__), "../data/kworb_raw.csv")
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_streams(s):
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
        # Split on first " - " only; handles "AC/DC - Back In Black" etc.
        parts = raw.split(" - ", 1)
        if len(parts) != 2:
            continue
        artist, title = parts[0].strip(), parts[1].strip()

        try:
            streams = parse_streams(cols[1].get_text())
        except ValueError:
            continue

        records.append({"artist": artist, "title": title, "spotify_streams": streams})

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT, index=False)
    print(f"Saved {len(df)} songs to {OUTPUT}")
    print(f"\nTop 5:")
    print(df.head().to_string(index=False))
    return df


if __name__ == "__main__":
    scrape()
