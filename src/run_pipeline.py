"""
One-command pipeline runner. Runs the downstream steps in order so you don't
have to invoke them by hand after tweaking scoring.

    python src/run_pipeline.py                  # full: score -> links -> csv -> html
    python src/run_pipeline.py --quick          # fast: score -> csv only (no network, no html)
    python src/run_pipeline.py --force-links    # full run + re-fetch all Spotify links from scratch

--quick skips the Spotify fetch (the only slow/network step) and the HTML
exports, which is what you usually want while iterating on score.py. Run a full
pass when you're ready to refresh links and the published pages.

--force-links blows away the Spotify link cache and re-fetches everything. Use
this when existing links are wrong (e.g. after fixing the search logic).

Note: without --force-links the Spotify fetch is cached, so a full run only
looks up songs that newly entered the top TOP_N — it's cheap if nothing changed.
"""

import os
import subprocess
import sys

BASE = os.path.dirname(__file__)


def run(script, extra_args=None):
    print(f"\n=== {script} ===")
    cmd = [sys.executable, os.path.join(BASE, script)] + (extra_args or [])
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\nABORTED: {script} exited with code {result.returncode}")
        sys.exit(result.returncode)


def main():
    quick = "--quick" in sys.argv
    force_links = "--force-links" in sys.argv

    run("score.py")
    if not quick:
        run("fetch_spotify_links.py", ["--force"] if force_links else [])
    run("export_csv.py")
    if not quick:
        run("export.py")
        run("export_billboard.py")

    if quick:
        suffix = " (quick mode)"
    elif force_links:
        suffix = " (links refreshed)"
    else:
        suffix = ""
    print(f"\nPipeline complete.{suffix}")


if __name__ == "__main__":
    main()
