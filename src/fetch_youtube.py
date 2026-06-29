"""
Scrapes kworb.net/youtube/topvideos.html for all-time YouTube view counts.
Output: data/youtube_raw.csv  (artist, title, youtube_views)

kworb uses several separator formats between artist and title:
  "Artist - Title"   (regular hyphen -- most common)
  "Artist - Title"   (em dash)
  "Artist | Title"   (pipe)
  "Artist: Title"    (colon)
  "Artist 'Title' ..." (title in quotes, e.g. BTS uploads)
Featured-artist suffixes and metadata tags are stripped from titles.
"""

import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
import os

URL     = "https://kworb.net/youtube/topvideos.html"
OUTPUT  = os.path.join(os.path.dirname(__file__), "../data/youtube_raw.csv")
HEADERS = {"User-Agent": "Mozilla/5.0"}

_FEAT_RE      = re.compile(r"[ \t]+(?:ft\.?|feat\.?|featuring)[ \t]+.*$", re.IGNORECASE)
_META_RE      = re.compile(r"[\(\[].*$")
# Curly/straight single or double quotes, plus CJK brackets
_QUOTE_RE     = re.compile(
    u"[‘’‚‛“”„‟「」『』']"
    u"([^‘’‚‛“”„‟「」『』']+)"
    u"[‘’‚‛“”„‟「」『』']"
)
# Strips "[MV]", "(MV)", "[Official]" etc. from the front of a raw string
_MV_PREFIX_RE = re.compile(r"^\s*[\[\(][^\]\)]{0,10}[\]\)]\s*")


def clean_title(title):
    title = _FEAT_RE.sub("", title)
    title = _META_RE.sub("", title)
    return title.strip()


def parse_artist_title(raw):
    """Return (artist, title) or (None, None) if unparseable."""
    # 1. Regular hyphen: "Artist - Title"
    if " - " in raw:
        a, t = raw.split(" - ", 1)
        return a.strip(), clean_title(t.strip())

    # 2. Em dash or en dash
    if " – " in raw or " — " in raw:
        sep = " – " if " – " in raw else " — "
        a, t = raw.split(sep, 1)
        return a.strip(), clean_title(t.strip())

    # 3. Double pipe: "SHAKIRA || BZRP Music Sessions #53"
    if " || " in raw:
        a, t = raw.split(" || ", 1)
        return a.strip(), clean_title(t.strip())

    # 4. Pipe: "Artist | Title"
    if " | " in raw:
        a, t = raw.split(" | ", 1)
        return a.strip(), clean_title(t.strip())

    # 5. Underscore with spaces after stripping [MV] prefix:
    #    "[MV] BTS(방탄소년단) _ DOPE(쩔어)"
    stripped = _MV_PREFIX_RE.sub("", raw)
    if " _ " in stripped:
        a, t = stripped.split(" _ ", 1)
        return a.strip(), clean_title(t.strip())

    # 6. Colon: "Artist: Title"
    if ": " in raw:
        a, t = raw.split(": ", 1)
        return a.strip(), clean_title(t.strip())

    # 7. Quoted title (curly/CJK quotes): "BTS 'Dynamite' Official MV"
    m = _QUOTE_RE.search(raw)
    if m:
        title  = m.group(1).strip()
        artist = raw[: m.start()].strip()
        if artist and title:
            return artist, clean_title(title)

    return None, None


def parse_views(s):
    return int(s.replace(",", "").strip())


def scrape():
    print("Fetching {} ...".format(URL))
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"

    soup  = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    rows  = table.find("tbody").find_all("tr")

    records, skipped = [], 0
    for row in rows:
        cols = row.find_all("td")
        if len(cols) < 2:
            continue

        raw    = cols[0].get_text(strip=True)
        artist, title = parse_artist_title(raw)
        if not artist or not title:
            skipped += 1
            continue

        try:
            views = parse_views(cols[1].get_text())
        except ValueError:
            skipped += 1
            continue

        records.append({"artist": artist, "title": title, "youtube_views": views})

    df = pd.DataFrame(records)
    df.to_csv(OUTPUT, index=False)
    print("Saved {} videos to {} ({} unparseable rows skipped)".format(len(df), OUTPUT, skipped))
    print("\nTop 5:")
    print(df.head().to_string(index=False))
    return df


if __name__ == "__main__":
    scrape()
