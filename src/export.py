"""
Generates output/index.html — a sortable table of the top N songs by composite score.
"""

import pandas as pd
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TOP_N, BILLBOARD_ERA_HALF_WINDOW
from src.utils import artist_html

SCORES = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
LINKS = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")
OUTPUT = os.path.join(os.path.dirname(__file__), "../output/index.html")


def export():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return

    df = pd.read_csv(SCORES, index_col=0).head(TOP_N)

    links = {}
    if os.path.exists(LINKS):
        ldf = pd.read_csv(LINKS).fillna("")
        links = {(r["title"], r["artist"]): r["spotify_url"] for _, r in ldf.iterrows()}

    def fmt_int(val, is_floor=False):
        if pd.isna(val):
            return "—"
        # Songs missing from kworb but known (via a curated "N+ Million
        # Streams" playlist) to clear a threshold get that threshold as a
        # floor, not an exact count — mark it with "+" so it doesn't read as
        # a precise number.
        suffix = "+" if is_floor else ""
        return f"{int(val):,}{suffix}"

    rows_html = ""
    for rank, row in df.iterrows():
        year        = f"{int(row['year'])}" if pd.notna(row.get("year")) else "—"
        bb_peak     = f"#{int(row['bb_peak'])}" if pd.notna(row.get("bb_peak")) else "—"
        bb_weeks    = f"{int(row['bb_chart_weeks'])}w" if pd.notna(row.get("bb_chart_weeks")) else "—"
        sp_streams  = fmt_int(row.get("spotify_streams"), is_floor=bool(row.get("spotify_streams_is_floor")))
        yt_views    = fmt_int(row.get("youtube_views"))
        itunes_pts  = fmt_int(row.get("itunes_total"))
        apple_pts   = fmt_int(row.get("apple_total"))
        score       = row.get("final_score", 0)

        sp_url = links.get((row["title"], row["artist"]), "")
        title_cell = (
            f'<a href="{sp_url}" target="_blank" rel="noopener">{row["title"]}</a>'
            if sp_url else row["title"]
        )

        rows_html += f"""
        <tr>
          <td class="rank">{rank}</td>
          <td class="title">{title_cell}</td>
          <td class="artist">{artist_html(row['artist'])}</td>
          <td class="year">{year}</td>
          <td class="score">{score:.1f}</td>
          <td>{bb_peak}</td>
          <td>{bb_weeks}</td>
          <td class="num">{sp_streams}</td>
          <td class="num">{yt_views}</td>
          <td class="num">{itunes_pts}</td>
          <td class="num">{apple_pts}</td>
        </tr>"""

    updated = datetime.now(timezone.utc).strftime("%d %b %Y")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Music Popularity Index</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f0f0f; color: #e8e8e8; padding: 2rem; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 1.25rem; }}
    .wip-banner {{ background: #2a2410; border: 1px solid #5c4d18; color: #e8c34a;
                   padding: 0.6rem 0.9rem; border-radius: 6px; font-size: 0.85rem;
                   margin-bottom: 2rem; }}
    .wip-banner strong {{ color: #ffd75e; }}
    .updated {{ color: #555; font-size: 0.78rem; margin-bottom: 2rem; margin-top: -1.5rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; border-bottom: 2px solid #333; white-space: nowrap; padding: 0; }}
    .sort-btn {{ width: 100%; background: none; border: none; color: #aaa; font: inherit;
                 font-weight: 600; text-align: left; padding: 0.6rem 0.8rem;
                 cursor: pointer; user-select: none; }}
    .sort-btn:hover {{ color: #fff; }}
    td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e1e1e; }}
    tr:hover td {{ background: #1a1a1a; }}
    .rank {{ color: #555; width: 3rem; }}
    .title {{ font-weight: 600; color: #fff; max-width: 240px; }}
    .title a {{ color: #fff; text-decoration: none; }}
    .title a:hover {{ color: #1db954; text-decoration: underline; }}
    .artist {{ color: #bbb; max-width: 180px; }}
    .feat {{ color: #666; }}
    .year {{ color: #666; width: 4rem; }}
    .score {{ font-weight: 700; color: #1db954; }}
    .num {{ color: #999; text-align: right; font-variant-numeric: tabular-nums; }}
    .sort-btn.sorted-asc::after {{ content: " ▲"; }}
    .sort-btn.sorted-desc::after {{ content: " ▼"; }}
    .group-header {{ font-size: 0.75rem; color: #555; text-transform: uppercase;
                     letter-spacing: 0.05em; padding: 0.4rem 0.8rem; }}
  </style>
</head>
<body>
  <h1>Music Popularity Index</h1>
  <p class="subtitle">Top {TOP_N} songs · Billboard Hot 100 (1958–present) · Spotify all-time streams · Era-normalized within a ±{BILLBOARD_ERA_HALF_WINDOW}-year window</p>
  <div class="wip-banner"><strong>Work in progress</strong>, the scoring model is still being tuned, so these rankings will change.</div>
  <p class="updated">Last updated {updated} UTC</p>
  <table id="table">
    <thead>
      <tr>
        <th><button type="button" class="sort-btn">#</button></th>
        <th><button type="button" class="sort-btn">Title</button></th>
        <th><button type="button" class="sort-btn">Artist</button></th>
        <th><button type="button" class="sort-btn">Year</button></th>
        <th><button type="button" class="sort-btn">Score</button></th>
        <th><button type="button" class="sort-btn">BB Peak</button></th>
        <th><button type="button" class="sort-btn">BB Weeks</button></th>
        <th><button type="button" class="sort-btn">Spotify</button></th>
        <th><button type="button" class="sort-btn">YouTube</button></th>
        <th><button type="button" class="sort-btn">iTunes</button></th>
        <th><button type="button" class="sort-btn">Apple Music</button></th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>

  <script>
    let sortCol = 0, sortDir = 1;
    function sortBy(col) {{
      const table = document.getElementById("table");
      const tbody = table.tBodies[0];
      const rows = Array.from(tbody.rows);
      if (sortCol === col) sortDir *= -1; else {{ sortCol = col; sortDir = 1; }}
      rows.sort((a, b) => {{
        const av = a.cells[col].textContent.replace(/[^0-9.-]/g, "") || a.cells[col].textContent;
        const bv = b.cells[col].textContent.replace(/[^0-9.-]/g, "") || b.cells[col].textContent;
        const an = Number.parseFloat(av), bn = Number.parseFloat(bv);
        if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * sortDir;
        return av.localeCompare(bv) * sortDir;
      }});
      rows.forEach(r => tbody.appendChild(r));
      document.querySelectorAll("#table thead .sort-btn").forEach((btn, i) => {{
        let cls = "sort-btn";
        if (i === col) cls += sortDir === 1 ? " sorted-asc" : " sorted-desc";
        btn.className = cls;
      }});
    }}

    // Native <button> headers handle Enter/Space activation for free.
    document.querySelectorAll("#table thead .sort-btn").forEach((btn, i) => {{
      btn.addEventListener("click", () => sortBy(i));
    }});
  </script>
</body>
</html>"""

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Exported to {OUTPUT}")


if __name__ == "__main__":
    export()
