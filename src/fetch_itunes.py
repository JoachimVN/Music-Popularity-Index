"""
Scrapes kworb.net/ww/totals.html for worldwide iTunes chart point totals.
"Total" is cumulative chart points since August 2010, not download counts.
Output: data/itunes_raw.csv  (artist, title, itunes_total)
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import os

URL = "https://kworb.net/ww/totals.html"
OUTPUT = os.path.join(os.path.dirname(__file__), "../data/itunes_raw.csv")
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_number(s):
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
        if len(cols) < 5:
            continue

        raw = cols[0].get_text(strip=True)
        parts = raw.split(" - ", 1)
        if len(parts) != 2:
            continue
        artist, title = parts[0].strip(), parts[1].strip()

        try:
            total = parse_number(cols[4].get_text())
        except ValueError:
            continue

        records.append({"artist": artist, "title": title, "itunes_total": total})

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT, index=False)
    print(f"Saved {len(df)} songs to {OUTPUT}")
    print("\nTop 5:")
    print(df.head().to_string(index=False))
    return df


if __name__ == "__main__":
    scrape()
