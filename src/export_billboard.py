"""
Generates output/billboard.html — a pure Billboard Hot 100 era-normalized ranking.
No Spotify or Last.fm — just chart performance adjusted for era inflation.
"""

import pandas as pd
import numpy as np
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.score import load_billboard
from config import BILLBOARD_ERA_HALF_WINDOW, BILLBOARD_PEAK_WEIGHT

OUTPUT = os.path.join(os.path.dirname(__file__), "../output/billboard.html")
TOP_N = 200


def export():
    bb = load_billboard()
    bb["score"] = (bb["bb_score"] * 100).round(1)
    bb = bb.sort_values("score", ascending=False).reset_index(drop=True)
    bb.index += 1

    rows_html = ""
    for rank, row in bb.head(TOP_N).iterrows():
        year = int(row["year"]) if pd.notna(row.get("year")) else "—"
        peak = f"#{int(row['bb_peak'])}" if pd.notna(row.get("bb_peak")) else "—"
        weeks = int(row["bb_chart_weeks"]) if pd.notna(row.get("bb_chart_weeks")) else "—"
        score = row["score"]
        rows_html += f"""
        <tr>
          <td class="rank">{rank}</td>
          <td class="title">{row['title']}</td>
          <td class="artist">{row['artist']}</td>
          <td class="year">{year}</td>
          <td class="score">{score}</td>
          <td>{peak}</td>
          <td>{weeks}w</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Billboard Hot 100 — Era-Normalized Index</title>
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
    .title {{ font-weight: 600; color: #fff; max-width: 300px; }}
    .artist {{ color: #bbb; max-width: 220px; }}
    .year {{ color: #666; width: 4rem; }}
    .score {{ font-weight: 700; color: #1db954; }}
    th.sorted-asc::after {{ content: " ▲"; }}
    th.sorted-desc::after {{ content: " ▼"; }}
  </style>
</head>
<body>
  <h1>Billboard Hot 100 — Era-Normalized</h1>
  <p class="subtitle">Top {TOP_N} · Peak &amp; longevity percentile-ranked within a ±{BILLBOARD_ERA_HALF_WINDOW}-year window · {int(BILLBOARD_PEAK_WEIGHT*100)}% peak position, {int((1-BILLBOARD_PEAK_WEIGHT)*100)}% chart weeks</p>
  <table id="table">
    <thead>
      <tr>
        <th onclick="sortBy(0)">#</th>
        <th onclick="sortBy(1)">Title</th>
        <th onclick="sortBy(2)">Artist</th>
        <th onclick="sortBy(3)">Year</th>
        <th onclick="sortBy(4)">Score</th>
        <th onclick="sortBy(5)">Peak</th>
        <th onclick="sortBy(6)">Chart Weeks</th>
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
