"""
Generates per-platform ranking pages showing raw values and era-normalised scores.
Outputs: output/spotify.html, output/youtube.html, output/itunes.html, output/apple.html
"""

import os
import sys
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.utils import artist_html

BASE   = os.path.dirname(__file__)
SCORES = os.path.join(BASE, "../data/scores.csv")

PLATFORMS = [
    {
        "name":      "Spotify",
        "raw_col":   "spotify_streams",
        "score_col": "sp_score",
        "label":     "Streams",
        "coverage":  "all-time streams",
        "color":     "#1db954",
        "output":    os.path.join(BASE, "../output/spotify.html"),
    },
    {
        "name":      "YouTube",
        "raw_col":   "youtube_views",
        "score_col": "yt_score",
        "label":     "Views",
        "coverage":  "all-time views (top ~2 000 videos)",
        "color":     "#ff0000",
        "output":    os.path.join(BASE, "../output/youtube.html"),
    },
    {
        "name":      "iTunes",
        "raw_col":   "itunes_total",
        "score_col": "itunes_score",
        "label":     "Chart Points",
        "coverage":  "cumulative chart points since Aug 2010",
        "color":     "#fc3c44",
        "output":    os.path.join(BASE, "../output/itunes.html"),
    },
    {
        "name":      "Apple Music",
        "raw_col":   "apple_total",
        "score_col": "apple_score",
        "label":     "Chart Points",
        "coverage":  "cumulative chart points since Jul 2017",
        "color":     "#fc3c44",
        "output":    os.path.join(BASE, "../output/apple.html"),
    },
]

TOP_N = 500


def export_platform(df, p):
    raw_col   = p["raw_col"]
    score_col = p["score_col"]
    color     = p["color"]

    if raw_col not in df.columns or score_col not in df.columns:
        print(f"  SKIP {p['name']} — columns missing from scores.csv")
        return

    sub = df[df[raw_col].notna()].copy()
    sub = sub.sort_values(raw_col, ascending=False).head(TOP_N).reset_index(drop=True)
    sub.index += 1

    rows_html = ""
    for rank, row in sub.iterrows():
        year    = f"{int(row['year'])}"  if pd.notna(row.get("year"))  else "—"
        decade  = f"{int(row['decade'])}s" if pd.notna(row.get("decade")) else "—"
        raw_val = f"{int(row[raw_col]):,}"
        era_pct = f"{row[score_col] * 100:.1f}%"
        rows_html += f"""
        <tr>
          <td class="rank">{rank}</td>
          <td class="title">{row['title']}</td>
          <td class="artist">{artist_html(row['artist'])}</td>
          <td class="year">{year}</td>
          <td class="decade">{decade}</td>
          <td class="num">{raw_val}</td>
          <td class="era">{era_pct}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{p['name']} — Era-Normalized Index</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            background: #0f0f0f; color: #e8e8e8; padding: 2rem; }}
    h1 {{ font-size: 1.8rem; margin-bottom: 0.25rem; }}
    .subtitle {{ color: #888; font-size: 0.85rem; margin-bottom: 2rem; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.88rem; }}
    th {{ text-align: left; border-bottom: 2px solid #333; white-space: nowrap; padding: 0; }}
    .sort-btn {{ width: 100%; background: none; border: none; color: #aaa; font: inherit;
                 font-weight: 600; text-align: left; padding: 0.6rem 0.8rem;
                 cursor: pointer; user-select: none; }}
    .sort-btn:hover {{ color: #fff; }}
    td {{ padding: 0.5rem 0.8rem; border-bottom: 1px solid #1e1e1e; }}
    tr:hover td {{ background: #1a1a1a; }}
    .rank   {{ color: #555; width: 3rem; }}
    .title  {{ font-weight: 600; color: #fff; max-width: 280px; }}
    .artist {{ color: #bbb; max-width: 200px; }}
    .feat   {{ color: #666; }}
    .year   {{ color: #666; width: 4rem; }}
    .decade {{ color: #555; width: 5rem; }}
    .num    {{ color: #999; text-align: right; font-variant-numeric: tabular-nums; }}
    .era    {{ font-weight: 700; color: {color}; text-align: right; }}
    .sort-btn.sorted-asc::after  {{ content: " ▲"; }}
    .sort-btn.sorted-desc::after {{ content: " ▼"; }}
  </style>
</head>
<body>
  <h1>{p['name']} — Era-Normalized</h1>
  <p class="subtitle">Top {TOP_N} · {p['coverage']} · Era score = percentile within release decade · sorted by {p['label'].lower()}</p>
  <table id="table">
    <thead>
      <tr>
        <th><button type="button" class="sort-btn">#</button></th>
        <th><button type="button" class="sort-btn">Title</button></th>
        <th><button type="button" class="sort-btn">Artist</button></th>
        <th><button type="button" class="sort-btn">Year</button></th>
        <th><button type="button" class="sort-btn">Decade</button></th>
        <th><button type="button" class="sort-btn">{p['label']}</button></th>
        <th><button type="button" class="sort-btn">Era Score</button></th>
      </tr>
    </thead>
    <tbody>{rows_html}
    </tbody>
  </table>
  <script>
    let sortCol = 0, sortDir = 1;
    function sortBy(col) {{
      const tbody = document.getElementById("table").tBodies[0];
      const rows  = Array.from(tbody.rows);
      if (sortCol === col) sortDir *= -1; else {{ sortCol = col; sortDir = 1; }}
      rows.sort((a, b) => {{
        const av = a.cells[col].textContent.replace(/[^0-9.]/g, "") || a.cells[col].textContent;
        const bv = b.cells[col].textContent.replace(/[^0-9.]/g, "") || b.cells[col].textContent;
        const an = parseFloat(av), bn = parseFloat(bv);
        return (!isNaN(an) && !isNaN(bn) ? an - bn : av.localeCompare(bv)) * sortDir;
      }});
      rows.forEach(r => tbody.appendChild(r));
      document.querySelectorAll("#table thead .sort-btn").forEach((btn, i) => {{
        btn.className = "sort-btn" + (i === col ? (sortDir === 1 ? " sorted-asc" : " sorted-desc") : "");
      }});
    }}
    document.querySelectorAll("#table thead .sort-btn").forEach((btn, i) => {{
      btn.addEventListener("click", () => sortBy(i));
    }});
  </script>
</body>
</html>"""

    os.makedirs(os.path.dirname(p["output"]), exist_ok=True)
    with open(p["output"], "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Exported to {p['output']}")


def export_all():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return
    df = pd.read_csv(SCORES, index_col=0)
    for p in PLATFORMS:
        export_platform(df, p)


if __name__ == "__main__":
    export_all()
