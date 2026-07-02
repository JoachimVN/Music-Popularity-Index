"""
Scrapes RIAA's Gold & Platinum certification database for Single-format
awards (Gold/Platinum/Diamond) — the one sales signal that spans the
index's full 1958-present range, unlike Billboard's Digital Song Sales
chart (2004+ only).

The site's "Load More" pagination goes through a Cloudflare-protected
admin-ajax.php endpoint that blocks plain HTTP requests, but the first 30
results of any filtered/sorted query render server-side on a plain GET.
So this fetcher partitions the full date range into year-sized chunks and
recursively bisects any chunk that hits the 30-row page cap, staying
entirely on the unprotected path.

Resumable: years already present in the output are skipped on re-run.
Saves progress after each year so an interrupted run isn't wasted. A
single dense year can itself take many requests (bisected down to
day-level windows in the busiest recent years), so a full historical run
can take a while — that's expected, same tradeoff as fetch_billboard.py.
"""

import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import re
import time
from datetime import date, timedelta

OUTPUT = os.path.join(os.path.dirname(__file__), "../data/riaa_raw.csv")
PROGRESS = os.path.join(os.path.dirname(__file__), "../data/riaa_progress.txt")
BASE_URL = "https://www.riaa.com/gold-platinum/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
}
START_YEAR = 1958
SLEEP_BETWEEN = 1.5  # seconds, be polite (matches fetch_billboard.py)
# The site's data-perpage="30" suggests a 30-row cap, but empirically a
# truncated page renders only 29 <tr> elements (one slot appears to be
# consumed elsewhere in their template). Bisect on anything >= 25 rather
# than trusting the exact boundary — a false-positive split just costs a
# few extra requests, but trusting a wrong cutoff silently drops data.
PAGE_CAP = 25

_TIER_RE = re.compile(r"earned RIAA (.+?) Award for")


def _fetch_window(d_from, d_to, award="", type_=""):
    params = {
        "tab_active": "default-award",
        "ar": "", "ti": "", "lab": "", "genre": "",
        "format": "Single",
        "date_option": "certification",
        "from": d_from.isoformat(),
        "to": d_to.isoformat(),
        "award": award, "type": type_, "category": "",
        "adv": "SEARCH",
        "col": "certification_date",
        "ord": "asc",
    }
    for attempt in range(6):
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=20)
        except requests.exceptions.RequestException as e:
            # Transient network failure (timeout, connection reset, DNS
            # blip, ...) — a full historical run makes thousands of
            # requests over hours, so treat these the same as a 429 rather
            # than letting one hiccup kill the whole run.
            wait = 10 * (attempt + 1)
            print(f"    network error ({e.__class__.__name__}), backing off {wait}s...")
            time.sleep(wait)
            continue
        if resp.status_code == 429:
            wait = 10 * (attempt + 1)
            print(f"    429 rate-limited, backing off {wait}s...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.text
    raise RuntimeError(f"Gave up after repeated failures fetching {d_from}..{d_to} (award={award!r}, type={type_!r})")


def _text_or_none(tag):
    # Guards the .get_text() call directly against the tag it's called on,
    # rather than relying on a null check elsewhere in the caller — a Tag's
    # __bool__ falls back to child count, so an empty-but-present tag would
    # be falsy; check "is None" explicitly instead of truthiness.
    return tag.get_text(strip=True) if tag is not None else None


def _parse_rows(html):
    soup = BeautifulSoup(html, "lxml")
    records = []
    for tr in soup.select("tr.table_award_row"):
        award_tag = tr.find(attrs={"data-share-desc": True})
        tier = None
        if award_tag is not None:
            m = _TIER_RE.search(award_tag["data-share-desc"])
            if m:
                tier = m.group(1)

        others = tr.find_all("td", class_="others_cell")
        artist = _text_or_none(tr.find("td", class_="artists_cell"))
        title = _text_or_none(others[0]) if len(others) > 0 else None
        cert_date = _text_or_none(others[1]) if len(others) > 1 else None

        if artist is None or title is None or cert_date is None or tier is None:
            continue
        records.append({
            "artist": artist,
            "title": title,
            "cert_date": cert_date,
            "award_tier": tier,
        })
    return records


_AWARD_TIERS = ("G", "P", "D")
_CERT_TYPES = ("DI", "ST", "MT", "LA")


def _fetch_day_by_type(d, award):
    """A single day is still over the cap even filtered to one award tier —
    split further by certification type (Digital/Standard/Mastertone/Latin),
    the last axis the search form exposes. If even that overflows we accept
    the truncation; this only matters for the single busiest days/tiers."""
    all_rows = []
    for type_ in _CERT_TYPES:
        html = _fetch_window(d, d, award=award, type_=type_)
        time.sleep(SLEEP_BETWEEN)
        rows = _parse_rows(html)
        if len(rows) >= PAGE_CAP:
            print(f"    WARNING: {d} award={award} type={type_} still >= {PAGE_CAP} rows — accepting possible truncation")
        all_rows.extend(rows)
    return all_rows


def _fetch_day_by_tier(d):
    """A single calendar day can't be bisected by date any further — split
    by award tier (Gold/Platinum/Diamond) instead, since large batches of
    certifications are often posted on the same day."""
    all_rows = []
    for award in _AWARD_TIERS:
        html = _fetch_window(d, d, award=award)
        time.sleep(SLEEP_BETWEEN)
        rows = _parse_rows(html)
        if len(rows) >= PAGE_CAP:
            rows = _fetch_day_by_type(d, award)
        all_rows.extend(rows)
    return all_rows


def _fetch_range(d_from, d_to):
    """Recursively bisect [d_from, d_to] until each window is under the page cap."""
    html = _fetch_window(d_from, d_to)
    time.sleep(SLEEP_BETWEEN)
    rows = _parse_rows(html)

    if len(rows) < PAGE_CAP:
        return rows

    if d_from == d_to:
        return _fetch_day_by_tier(d_from)

    mid = d_from + (d_to - d_from) // 2
    left = _fetch_range(d_from, mid)
    right = _fetch_range(mid + timedelta(days=1), d_to)
    return left + right


def load_existing():
    if os.path.exists(OUTPUT):
        return pd.read_csv(OUTPUT)
    return pd.DataFrame()


def _load_progress():
    if os.path.exists(PROGRESS):
        with open(PROGRESS) as f:
            return {int(line.strip()) for line in f if line.strip()}
    return set()


def _mark_done(year):
    with open(PROGRESS, "a") as f:
        f.write(f"{year}\n")


def scrape():
    existing = load_existing()
    # Track completed years explicitly rather than inferring from the data —
    # a year with zero real certifications (e.g. the sparse early catalog)
    # would otherwise never be marked done and get re-fetched every re-run.
    done_years = _load_progress()

    years = list(range(START_YEAR, date.today().year + 1))
    for i, year in enumerate(years):
        if year in done_years:
            print(f"[{i+1}/{len(years)}] {year} — already fetched, skipping")
            continue

        d_from = date(year, 1, 1)
        d_to = min(date(year, 12, 31), date.today())
        print(f"[{i+1}/{len(years)}] {year} — fetching...")
        rows = _fetch_range(d_from, d_to)
        for r in rows:
            r["cert_year"] = year
        print(f"    {len(rows)} single certifications")

        existing = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
        existing.to_csv(OUTPUT, index=False)
        _mark_done(year)

    print(f"\nDone. Saved {len(existing)} rows to {OUTPUT}")
    return existing


if __name__ == "__main__":
    scrape()
