"""
Generates output/index.html — a sortable table of the top N songs by composite score.
"""

import pandas as pd
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TOP_N, BILLBOARD_ERA_HALF_WINDOW

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

    rows_html = ""
    for rank, row in df.iterrows():
        year = f"{int(row['year'])}" if pd.notna(row.get("year")) else "—"
        bb_peak = f"#{int(row['bb_peak'])}" if pd.notna(row.get("bb_peak")) else "—"
        bb_chart_weeks = f"{int(row['bb_chart_weeks'])}w" if pd.notna(row.get("bb_chart_weeks")) else "—"
        sp_streams = f"{int(row['spotify_streams']):,}" if pd.notna(row.get("spotify_streams")) else "—"
        score = row.get("final_score", 0)

        sp_url = links.get((row["title"], row["artist"]), "")
        title_cell = (
            f'<a href="{sp_url}" target="_blank" rel="noopener">{row["title"]}</a>'
            if sp_url else row["title"]
        )

        rows_html += f"""
        <tr>
          <td class="rank">{rank}</td>
          <td class="title">{title_cell}</td>
          <td class="artist">{row['artist']}</td>
          <td class="year">{year}</td>
          <td class="score">{score:.1f}</td>
          <td>{bb_peak}</td>
          <td>{bb_chart_weeks}</td>
          <td>{sp_streams}</td>
        </tr>"""

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
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 2rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 2px solid #333;
          color: #aaa; font-weight: 600; cursor: pointer; user-select: none; white-space: nowrap; }}
    th:hover {{ color: #fff; }}
    td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e1e1e; }}
    tr:hover td {{ background: #1a1a1a; }}
    .rank {{ color: #555; width: 3rem; }}
    .title {{ font-weight: 600; color: #fff; max-width: 260px; }}
    .title a {{ color: #fff; text-decoration: none; }}
    .title a:hover {{ color: #1db954; text-decoration: underline; }}
    .artist {{ color: #bbb; max-width: 200px; }}
    .year {{ color: #666; width: 4rem; }}
    .score {{ font-weight: 700; color: #1db954; }}
    th.sorted-asc::after {{ content: " ▲"; }}
    th.sorted-desc::after {{ content: " ▼"; }}
    .group-header {{ font-size: 0.75rem; color: #555; text-transform: uppercase;
                     letter-spacing: 0.05em; padding: 0.4rem 0.8rem; }}
  </style>
</head>
<body>
  <h1>Music Popularity Index</h1>
  <p class="subtitle">Top {TOP_N} songs · Billboard Hot 100 (1958–present) · Spotify all-time streams · Era-normalized within a ±{BILLBOARD_ERA_HALF_WINDOW}-year window</p>
  <table id="table">
    <thead>
      <tr>
        <th onclick="sortBy(0)">#</th>
        <th onclick="sortBy(1)">Title</th>
        <th onclick="sortBy(2)">Artist</th>
        <th onclick="sortBy(3)">Year</th>
        <th onclick="sortBy(4)">Score</th>
        <th onclick="sortBy(5)">BB Peak</th>
        <th onclick="sortBy(6)">BB Weeks</th>
        <th onclick="sortBy(7)">Spotify Streams</th>
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
        const an = parseFloat(av), bn = parseFloat(bv);
        if (!isNaN(an) && !isNaN(bn)) return (an - bn) * sortDir;
        return av.localeCompare(bv) * sortDir;
      }});
      rows.forEach(r => tbody.appendChild(r));
      document.querySelectorAll("th").forEach((th, i) => {{
        th.className = i === col ? (sortDir === 1 ? "sorted-asc" : "sorted-desc") : "";
      }});
    }}
  </script>
</body>
</html>"""

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Exported to {OUTPUT}")


if __name__ == "__main__":
    export()
