"""
Generates output/index.html — a sortable table of the top N songs by composite score.
"""

import pandas as pd
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config import TOP_N, BILLBOARD_ERA_HALF_WINDOW, WEIGHTS
from src.utils import artist_html
from src.score import _PLATFORM_START

SCORES = os.path.join(os.path.dirname(__file__), "../data/scores.csv")
LINKS = os.path.join(os.path.dirname(__file__), "../data/spotify_links.csv")
OUTPUT = os.path.join(os.path.dirname(__file__), "../output/index.html")

# dimension key (matches config.WEIGHTS / score.py's _PLATFORM_START) -> score
# column in scores.csv. Kept in sync with score.py's dim_cols by hand — the
# in-browser weight adjuster below reimplements _apply_weights() in JS using
# these same columns, so the two must stay aligned.
DIM_COLS = {
    "billboard":          "bb_score",
    "spotify_streams":    "sp_score",
    "youtube_views":      "yt_score",
    "itunes_total":       "itunes_score",
    "apple_total":        "apple_score",
    "digital_sales":      "sales_score",
    "riaa_certification": "riaa_score",
    "radio_airplay":      "radio_score",
}
DIM_LABELS = {
    "billboard":          "Billboard",
    "spotify_streams":    "Spotify",
    "youtube_views":      "YouTube",
    "itunes_total":       "iTunes",
    "apple_total":        "Apple Music",
    "digital_sales":      "Digital Sales",
    "riaa_certification": "RIAA Certs",
    "radio_airplay":      "Radio Airplay",
}


def _fmt_int(val, is_floor=False):
    if pd.isna(val):
        return "—"
    # Songs missing from kworb but known (via a curated "N+ Million Streams"
    # playlist) to clear a threshold get that threshold as a floor, not an
    # exact count — mark it with "+" so it doesn't read as a precise number.
    suffix = "+" if is_floor else ""
    return f"{int(val):,}{suffix}"


def _fmt_peak_weeks(row, peak_col, weeks_col):
    peak = f"#{int(row[peak_col])}" if pd.notna(row.get(peak_col)) else "—"
    weeks = f"{int(row[weeks_col])}w" if pd.notna(row.get(weeks_col)) else "—"
    return peak, weeks


def _row_dims_json(row):
    # Per-dimension era-normalised scores (0-1, or null) plus the song's year,
    # so the in-browser weight adjuster can recompute final_score for any
    # weight combination without a server round-trip.
    dims = {key: (None if pd.isna(row.get(col)) else float(row[col])) for key, col in DIM_COLS.items()}
    dims["year"] = None if pd.isna(row.get("year")) else int(row["year"])
    return json.dumps(dims, separators=(",", ":")).replace('"', "&quot;")


def _row_html(rank, row, links):
    year = f"{int(row['year'])}" if pd.notna(row.get("year")) else "—"
    bb_peak, bb_weeks = _fmt_peak_weeks(row, "bb_peak", "bb_chart_weeks")
    sales_peak, sales_weeks = _fmt_peak_weeks(row, "sales_peak", "sales_chart_weeks")
    radio_peak, radio_weeks = _fmt_peak_weeks(row, "radio_peak", "radio_chart_weeks")
    riaa_units = _fmt_int(row.get("riaa_units"))
    sp_streams = _fmt_int(row.get("spotify_streams"), is_floor=bool(row.get("spotify_streams_is_floor")))
    yt_views = _fmt_int(row.get("youtube_views"))
    itunes_pts = _fmt_int(row.get("itunes_total"))
    apple_pts = _fmt_int(row.get("apple_total"))
    score = row.get("final_score", 0)

    sp_url = links.get((row["title"], row["artist"]), "")
    title_cell = (
        f'<a href="{sp_url}" target="_blank" rel="noopener">{row["title"]}</a>'
        if sp_url else row["title"]
    )

    return f"""
        <tr data-dims="{_row_dims_json(row)}">
          <td class="rank">{rank}</td>
          <td class="title">{title_cell}</td>
          <td class="artist">{artist_html(row['artist'])}</td>
          <td class="year">{year}</td>
          <td class="score">{score:.1f}</td>
          <td>{bb_peak}</td>
          <td>{bb_weeks}</td>
          <td>{sales_peak}</td>
          <td>{sales_weeks}</td>
          <td class="num">{riaa_units}</td>
          <td>{radio_peak}</td>
          <td>{radio_weeks}</td>
          <td class="num">{sp_streams}</td>
          <td class="num">{yt_views}</td>
          <td class="num">{itunes_pts}</td>
          <td class="num">{apple_pts}</td>
        </tr>"""


def _bar_path(x, y, w, h):
    # Rounded top corners, square baseline — the site's one bar-chart mark spec.
    r = min(4, h / 2, w / 2)
    return (
        f"M{x:.2f},{y + h:.2f} L{x:.2f},{y + r:.2f} "
        f"Q{x:.2f},{y:.2f} {x + r:.2f},{y:.2f} "
        f"L{x + w - r:.2f},{y:.2f} "
        f"Q{x + w:.2f},{y:.2f} {x + w:.2f},{y + r:.2f} "
        f"L{x + w:.2f},{y + h:.2f} Z"
    )


def _nice_step(max_val, target_lines=4):
    for step in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000):
        if max_val / step <= target_lines:
            return step
    return 5000


def _year_chart_html(df):
    years = df["year"].dropna().astype(int)
    missing = int(df["year"].isna().sum())
    if years.empty:
        return "", missing

    counts = years.value_counts()
    y0, y1 = int(years.min()), int(years.max())
    all_years = list(range(y0, y1 + 1))
    peak_year = counts.idxmax()
    peak_count = int(counts.max())

    step = _nice_step(peak_count)
    y_max = -(-peak_count // step) * step  # round up to next multiple of step

    view_w, view_h = 1000, 240
    margin = {"left": 34, "right": 8, "top": 16, "bottom": 26}
    plot_w = view_w - margin["left"] - margin["right"]
    plot_h = view_h - margin["top"] - margin["bottom"]

    n = len(all_years)
    slot_w = plot_w / n

    # Label every 5th year, plus the first/last year — but only if an edge
    # year isn't too close to its neighboring mod-5 label to overlap it
    # (labels are ~20px wide; slots can be a few px each at this many years).
    min_gap_years = max(2, -(-20 // slot_w))
    label_years = {yr for yr in all_years if yr % 5 == 0}
    for edge in (y0, y1):
        if all(abs(edge - ly) >= min_gap_years for ly in label_years):
            label_years.add(edge)

    gridlines = []
    for i in range(int(y_max / step) + 1):
        val = i * step
        gy = margin["top"] + plot_h * (1 - val / y_max)
        gridlines.append(
            f'<line class="grid" x1="{margin["left"]}" y1="{gy:.2f}" '
            f'x2="{view_w - margin["right"]}" y2="{gy:.2f}"/>'
            f'<text class="axis-y" x="{margin["left"] - 6}" y="{gy:.2f}" '
            f'text-anchor="end" dominant-baseline="middle">{val}</text>'
        )

    bars = []
    for i, yr in enumerate(all_years):
        count = int(counts.get(yr, 0))
        x = margin["left"] + i * slot_w
        bar_w = max(slot_w - 2, 1)
        h = plot_h * (count / y_max) if y_max else 0
        y = margin["top"] + plot_h - h
        is_peak = yr == peak_year
        bars.append(f"""
          <g class="bar-group" tabindex="0" data-year="{yr}" data-count="{count}">
            <rect class="bar-hit" x="{x:.2f}" y="{margin['top']:.2f}" width="{bar_w:.2f}" height="{plot_h:.2f}"/>
            <path class="bar{' bar-peak' if is_peak else ''}" d="{_bar_path(x, y, bar_w, h)}"/>
          </g>""")
        if yr in label_years:
            lx = x + bar_w / 2
            bars.append(
                f'<text class="axis-x" x="{lx:.2f}" y="{view_h - margin["bottom"] + 16}" '
                f'text-anchor="middle">{yr}</text>'
            )

    peak_i = all_years.index(peak_year)
    peak_x = margin["left"] + peak_i * slot_w + max(slot_w - 2, 1) / 2
    peak_y = margin["top"] + plot_h - plot_h * (peak_count / y_max) if y_max else margin["top"]
    peak_label = (
        f'<text class="bar-peak-label" x="{peak_x:.2f}" y="{max(peak_y - 8, 10):.2f}" '
        f'text-anchor="middle">{peak_count}</text>'
    )

    svg = f"""
      <svg class="year-chart" viewBox="0 0 {view_w} {view_h}" role="img"
           aria-label="Number of songs by release year, {y0}–{y1}, peaking at {peak_count} in {peak_year}">
        {''.join(gridlines)}
        {''.join(bars)}
        {peak_label}
      </svg>"""

    return svg, missing


def _weight_field_html(key):
    return f"""
        <div class="weight-field">
          <label for="w-{key}">{DIM_LABELS[key]}</label>
          <div class="weight-input-wrap">
            <input type="number" id="w-{key}" min="0" max="100" step="1"
                   value="{round(WEIGHTS.get(key, 0) * 100)}" oninput="updateTotal()"
                   onkeydown="if (event.key === 'Enter') applyWeights()">
            <span class="unit">%</span>
          </div>
        </div>"""


def export():
    if not os.path.exists(SCORES):
        print("ERROR: data/scores.csv not found. Run score.py first.")
        return

    df = pd.read_csv(SCORES, index_col=0).head(TOP_N)

    links = {}
    if os.path.exists(LINKS):
        ldf = pd.read_csv(LINKS).fillna("")
        links = {(r["title"], r["artist"]): r["spotify_url"] for _, r in ldf.iterrows()}

    rows_html = "".join(_row_html(rank, row, links) for rank, row in df.iterrows())
    weight_rows_html = "".join(_weight_field_html(key) for key in DIM_COLS)
    year_chart_svg, year_missing = _year_chart_html(df)
    year_missing_note = ""
    if year_missing:
        plural = "" if year_missing == 1 else "s"
        year_missing_note = f" · {year_missing} song{plural} missing a release year and excluded"
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
    .weights-panel {{ background: #161616; border: 1px solid #2a2a2a; border-radius: 8px;
                       padding: 0.9rem 1.4rem; margin-bottom: 1.5rem; }}
    .weights-panel[open] {{ padding-bottom: 1.2rem; }}
    .weights-panel summary {{ font-size: 0.95rem; color: #eee; font-weight: 600; cursor: pointer;
                               padding: 0.3rem 0; list-style: none; }}
    .weights-panel summary::-webkit-details-marker {{ display: none; }}
    .weights-panel summary::before {{ content: "▸ "; color: #666; display: inline-block; width: 1rem; }}
    .weights-panel[open] summary::before {{ content: "▾ "; }}
    .weights-panel summary:hover {{ color: #fff; }}
    .weights-hint {{ color: #777; font-size: 0.78rem; line-height: 1.4; margin: 0.7rem 0 1.1rem; max-width: 60rem; }}
    .weights-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
                      gap: 0.9rem 1.4rem; }}
    .weight-field {{ display: flex; flex-direction: column; gap: 0.35rem; }}
    .weight-field label {{ font-size: 0.78rem; color: #999; }}
    .weight-input-wrap {{ display: flex; align-items: center; background: #1e1e1e;
                           border: 1px solid #333; border-radius: 6px; overflow: hidden; }}
    .weight-input-wrap:focus-within {{ border-color: #1db954; }}
    .weight-field input[type="number"] {{ flex: 1 1 auto; width: 100%; min-width: 0; background: transparent;
                                           border: none; color: #fff; font: inherit; font-size: 0.95rem;
                                           font-variant-numeric: tabular-nums; padding: 0.45rem 0 0.45rem 0.7rem;
                                           appearance: textfield; -moz-appearance: textfield; }}
    .weight-field input[type="number"]:focus {{ outline: none; }}
    /* Hide the spinner arrows — typing/clearing is the intended interaction, not stepping. */
    .weight-field input[type="number"]::-webkit-inner-spin-button {{ appearance: none; -webkit-appearance: none; margin: 0; }}
    .weight-input-wrap .unit {{ color: #666; font-size: 0.85rem; padding: 0 0.7rem 0 0.3rem; }}
    .weights-footer {{ display: flex; align-items: center; gap: 1.2rem; margin-top: 1.1rem; }}
    .weights-total {{ font-size: 0.82rem; color: #999; font-variant-numeric: tabular-nums; }}
    .weights-total .value {{ color: #ccc; font-weight: 600; }}
    .weights-panel .reset-btn, .weights-panel .apply-btn {{
      font: inherit; font-size: 0.8rem; padding: 0.45rem 1rem; border-radius: 5px; cursor: pointer; }}
    .weights-panel .reset-btn {{ background: #222; border: 1px solid #3a3a3a; color: #ccc; }}
    .weights-panel .reset-btn:hover {{ background: #2a2a2a; color: #fff; }}
    .weights-panel .apply-btn {{ background: #1db954; border: 1px solid #1db954; color: #0f0f0f; font-weight: 600; }}
    .weights-panel .apply-btn:hover {{ background: #1ed760; }}
    .chart-card {{ background: #161616; border: 1px solid #2a2a2a; border-radius: 8px;
                   padding: 0.9rem 1.4rem; margin-bottom: 1.5rem; }}
    .chart-card[open] {{ padding-bottom: 0.9rem; }}
    .chart-card summary {{ font-size: 0.95rem; color: #eee; font-weight: 600; cursor: pointer;
                            padding: 0.3rem 0; list-style: none; }}
    .chart-card summary::-webkit-details-marker {{ display: none; }}
    .chart-card summary::before {{ content: "▸ "; color: #666; display: inline-block; width: 1rem; }}
    .chart-card[open] summary::before {{ content: "▾ "; }}
    .chart-card summary:hover {{ color: #fff; }}
    .chart-subtitle {{ color: #777; font-size: 0.78rem; margin: 0.5rem 0 0.4rem; }}
    .year-chart-wrap {{ position: relative; }}
    .year-chart {{ width: 100%; height: auto; display: block; overflow: visible; }}
    .year-chart .grid {{ stroke: #262626; stroke-width: 1; }}
    .year-chart .axis-y, .year-chart .axis-x {{ fill: #666; font-size: 9px; }}
    .year-chart .bar {{ fill: #1db954; }}
    .year-chart .bar-hit {{ fill: transparent; }}
    .year-chart .bar-group:hover .bar, .year-chart .bar-group:focus .bar {{ fill: #1ed760; }}
    .year-chart .bar-group:focus {{ outline: none; }}
    .year-chart .bar-peak-label {{ fill: #ccc; font-size: 11px; font-weight: 600; text-anchor: middle; }}
    .chart-tooltip {{ position: absolute; pointer-events: none; background: #0a0a0a;
                       border: 1px solid #333; border-radius: 5px; padding: 0.35rem 0.6rem;
                       font-size: 0.78rem; color: #eee; white-space: nowrap; opacity: 0;
                       transform: translate(-50%, -100%); transition: opacity 0.1s; z-index: 10; }}
    .chart-tooltip.visible {{ opacity: 1; }}
    .chart-tooltip .tt-value {{ font-weight: 700; color: #fff; }}
    .chart-tooltip .tt-label {{ color: #999; margin-left: 0.3rem; }}
  </style>
</head>
<body>
  <h1>Music Popularity Index</h1>
  <p class="subtitle">Top {TOP_N} songs · Billboard Hot 100 (1958–present) · Spotify all-time streams · Era-normalized within a ±{BILLBOARD_ERA_HALF_WINDOW}-year window</p>
  <div class="wip-banner"><strong>Work in progress</strong>, the scoring model is still being tuned, so these rankings will change.</div>
  <p class="updated">Last updated {updated} UTC</p>

  <details class="weights-panel">
    <summary>Adjust dimension weights</summary>
    <p class="weights-hint">Type a weight (in %) for each dimension and the {TOP_N} songs below re-rank in your
      browser — no server round-trip. Weights don't need to sum to 100%; each song is normalised by whichever
      dimensions actually apply to it (see the note on era-gated dimensions below). Only re-ranks this page's
      existing set — a song outside the current top {TOP_N} won't appear even if it would rank higher under
      different weights.</p>
    <div class="weights-grid">{weight_rows_html}
    </div>
    <div class="weights-footer">
      <button type="button" class="apply-btn" onclick="applyWeights()">Apply</button>
      <button type="button" class="reset-btn" onclick="resetWeights()">Reset to defaults</button>
      <span class="weights-total">Total: <span class="value" id="weights-total">100</span>%</span>
    </div>
  </details>

  <details class="chart-card">
    <summary>Release year distribution</summary>
    <p class="chart-subtitle">{len(df)} songs in the top {TOP_N} by release year{year_missing_note}</p>
    <div class="year-chart-wrap">{year_chart_svg}
      <div class="chart-tooltip" id="year-tooltip" role="tooltip"></div>
    </div>
  </details>

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
        <th><button type="button" class="sort-btn">Sales Peak</button></th>
        <th><button type="button" class="sort-btn">Sales Weeks</button></th>
        <th><button type="button" class="sort-btn">RIAA Units</button></th>
        <th><button type="button" class="sort-btn">Radio Peak</button></th>
        <th><button type="button" class="sort-btn">Radio Weeks</button></th>
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
    // Mirrors score.py's _apply_weights()/_PLATFORM_START — a dimension only
    // counts toward a song's denominator if the song's year is at/after the
    // platform's start (or the dimension has no start, i.e. it's all-era).
    const PLATFORM_START = {json.dumps(_PLATFORM_START)};
    const DIM_KEYS = {json.dumps(list(DIM_COLS.keys()))};

    function computeScore(dims, weights) {{
      let weightedSum = 0, denom = 0;
      for (const key of DIM_KEYS) {{
        const w = weights[key];
        const start = PLATFORM_START[key];
        const applicable = !start || (dims.year != null && dims.year >= start);
        if (!applicable) continue;
        denom += w;
        weightedSum += (dims[key] == null ? 0 : dims[key]) * w;
      }}
      return denom > 0 ? weightedSum / denom : 0;
    }}

    // Inputs hold whole percentage points (e.g. 30 for 30%); computeScore
    // wants fractions (0.30), matching config.WEIGHTS' scale.
    function currentWeights() {{
      const weights = {{}};
      for (const key of DIM_KEYS) {{
        const pct = Number.parseFloat(document.getElementById("w-" + key).value);
        weights[key] = Number.isFinite(pct) ? pct / 100 : 0;
      }}
      return weights;
    }}

    // Cheap: runs on every keystroke, just updates the total — no re-rank,
    // so typing into a field stays snappy even with {TOP_N} rows on the page.
    function updateTotal() {{
      let total = 0;
      for (const key of DIM_KEYS) {{
        const pct = Number.parseFloat(document.getElementById("w-" + key).value);
        total += Number.isFinite(pct) ? pct : 0;
      }}
      document.getElementById("weights-total").textContent = total.toFixed(0);
    }}

    // Expensive: re-ranks all {TOP_N} rows. Only runs on explicit confirm
    // (Apply button, Enter key, or Reset) rather than on every keystroke.
    function applyWeights() {{
      updateTotal();
      recomputeAndRerank();
    }}

    function resetWeights() {{
      const defaults = {json.dumps(WEIGHTS)};
      for (const key of DIM_KEYS) document.getElementById("w-" + key).value = Math.round((defaults[key] ?? 0) * 100);
      applyWeights();
    }}

    function recomputeAndRerank() {{
      const weights = currentWeights();
      const tbody = document.getElementById("table").tBodies[0];
      const rows = Array.from(tbody.rows);

      let maxScore = 0;
      const scored = rows.map(row => {{
        const dims = JSON.parse(row.dataset.dims);
        const score = computeScore(dims, weights);
        if (score > maxScore) maxScore = score;
        return {{ row, score }};
      }});
      scored.forEach(s => {{ s.pct = maxScore > 0 ? (s.score / maxScore) * 100 : 0; }});
      scored.sort((a, b) => b.pct - a.pct);
      scored.forEach((s, i) => {{
        s.row.cells[0].textContent = i + 1;
        s.row.cells[4].textContent = s.pct.toFixed(1);
        tbody.appendChild(s.row);
      }});

      // A weight-driven re-rank supersedes whatever column sort was active.
      sortCol = 4; sortDir = -1;
      document.querySelectorAll("#table thead .sort-btn").forEach((btn, i) => {{
        btn.className = "sort-btn" + (i === 4 ? " sorted-desc" : "");
      }});
    }}

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

    // Year-histogram hover/focus tooltip. Same info is already in the SVG's
    // aria-label and each bar's data-year/data-count, so the tooltip only
    // ever repeats what's already reachable without a pointer.
    const yearTooltip = document.getElementById("year-tooltip");
    const yearChartWrap = document.querySelector(".year-chart-wrap");
    function showYearTooltip(group) {{
      const {{ year, count }} = group.dataset;
      yearTooltip.innerHTML = "";
      const value = document.createElement("span");
      value.className = "tt-value";
      value.textContent = count;
      const label = document.createElement("span");
      label.className = "tt-label";
      label.textContent = count === "1" ? `song in ${{year}}` : `songs in ${{year}}`;
      yearTooltip.appendChild(value);
      yearTooltip.appendChild(label);
      const wrapRect = yearChartWrap.getBoundingClientRect();
      const hitRect = group.querySelector(".bar-hit").getBoundingClientRect();
      yearTooltip.style.left = `${{hitRect.left - wrapRect.left + hitRect.width / 2}}px`;
      yearTooltip.style.top = `${{hitRect.top - wrapRect.top - 6}}px`;
      yearTooltip.classList.add("visible");
    }}
    function hideYearTooltip() {{
      yearTooltip.classList.remove("visible");
    }}
    document.querySelectorAll(".year-chart .bar-group").forEach(group => {{
      group.addEventListener("pointerenter", () => showYearTooltip(group));
      group.addEventListener("pointerleave", hideYearTooltip);
      group.addEventListener("focus", () => showYearTooltip(group));
      group.addEventListener("blur", hideYearTooltip);
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
