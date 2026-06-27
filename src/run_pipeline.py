"""
One-command pipeline runner. Runs the downstream steps in order so you don't
have to invoke them by hand after tweaking scoring.

    python src/run_pipeline.py           # full: score -> links -> csv -> html
    python src/run_pipeline.py --quick   # fast: score -> csv only (no network, no html)

--quick skips the Spotify fetch (the only slow/network step) and the HTML
exports, which is what you usually want while iterating on score.py. Run a full
pass when you're ready to refresh links and the published pages.

Note: the Spotify fetch is cached, so a full run only looks up songs that newly
entered the top TOP_N — it's cheap if nothing changed.
"""

import os
import subprocess
import sys

BASE = os.path.dirname(__file__)


def run(script):
    print(f"\n=== {script} ===")
    result = subprocess.run([sys.executable, os.path.join(BASE, script)])
    if result.returncode != 0:
        print(f"\nABORTED: {script} exited with code {result.returncode}")
        sys.exit(result.returncode)


def main():
    quick = "--quick" in sys.argv

    run("score.py")
    if not quick:
        run("fetch_spotify_links.py")
    run("export_csv.py")
    if not quick:
        run("export.py")
        run("export_billboard.py")

    print("\nPipeline complete." + (" (quick mode)" if quick else ""))


if __name__ == "__main__":
    main()
